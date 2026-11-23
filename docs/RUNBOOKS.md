# Runbooks por serviço

Um runbook responde: como sei se o serviço está saudável, o que olhar, como investigar, o que costuma dar errado e como recuperar. Todos os comandos são para o PowerShell, na pasta do projeto.

Atalhos usados em todos os runbooks:

```powershell
docker compose ps                         # estado dos containers
docker compose logs <serviço> --tail 100  # últimas linhas do log (adicione -f para acompanhar)
docker compose restart <serviço>          # reinicia um serviço
curl.exe http://localhost:8000/api/services   # estado e métricas de todos os serviços
curl.exe "http://localhost:8000/api/alerts?active=true"   # alertas ativos
```

Nomes dos serviços no compose: `nginx`, `postgres`, `coredns`, `mailpit`, `monitor`, `loadgen`.

---

## 1. Web (nginx)

**Verificar a saúde**
- Painel: página Web com disponibilidade 1 e card verde.
- Linha de comando: `curl.exe -i http://localhost:8081/` deve responder `200 OK`.
- `curl.exe -i http://localhost:8081/admin` deve responder `401` (a proteção está ativa).

**Métricas a olhar**
`up` (HTTP check), `latency_ms`, `rps`, `active_connections`, `error_rate_4xx`, `error_rate_5xx` e a contagem por código HTTP.
Regras: `web_disponibilidade` (vermelho se `up < 1`), `web_latencia_p95` (amarelo > 300 ms, vermelho > 1000 ms), `web_erros_5xx` (amarelo > 5%, vermelho > 15%).

**Diagnóstico**
```powershell
docker compose ps nginx
docker compose logs nginx --tail 50
docker exec rd-nginx nginx -t                                  # valida a sintaxe do nginx.conf
docker exec rd-nginx tail -n 20 /var/log/nginx-json/access.log # últimas requisições (JSON)
curl.exe http://localhost:8081/nginx_status                    # stub_status (conexões e total de requisições)
```

**Causas comuns**
| Sintoma | Causa provável |
|---|---|
| Card vermelho "Web fora do ar" | Container parado ou travado; erro de sintaxe no `nginx.conf` |
| Container reinicia sem parar | `nginx.conf` inválido (veja `nginx -t` e os logs) |
| Taxa de 5xx alta | Rota `/erro500` sendo muito chamada; backend com falha |
| Muitos 404 | Robôs varrendo caminhos inexistentes ou link quebrado |
| Muitos 401 no `/admin` | Brute force (veja o playbook) |
| Latência alta e RPS alto | Pico de tráfego ou ataque (veja o playbook de DDoS) |

**Recuperação**
1. `docker compose restart nginx`.
2. Se não subir: `docker compose logs nginx` para ver o erro; corrija o `services/nginx/nginx.conf` (ou restaure com `git checkout -- services/nginx/nginx.conf`) e rode `docker compose up -d nginx`.
3. Confirme no painel: card verde e e-mail `[RECUPERADO]` no Mailpit.

---

## 2. Banco de dados (PostgreSQL)

**Verificar a saúde**
- Painel: página Banco com disponibilidade 1, conexões baixas e card verde.
- `docker exec rd-postgres pg_isready -U app -d appdb` deve responder `accepting connections`.

**Métricas a olhar**
`up`, `connect_ms`, `qps`, `rollbacks_per_s`, `connections` e `connections_percent`, `cpu_percent`, `memory_mb`, `io_bytes_per_s`, `db_size_bytes`, `db_growth_mb_per_h`, `slow_queries`.
Regras: `db_disponibilidade`, `db_conexoes` (amarelo > 70%, vermelho > 90%), `db_slow_queries` (amarelo > 8, vermelho > 20 por minuto), `db_rollbacks` (amarelo > 0,5/s, vermelho > 2/s).

**Diagnóstico**
```powershell
docker compose logs postgres --tail 100
docker exec rd-postgres psql -U app -d appdb -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"
docker exec rd-postgres psql -U app -d appdb -c "SELECT calls, round(mean_exec_time::numeric,1) AS media_ms, left(query,80) AS query FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 5;"
docker exec rd-postgres psql -U app -d appdb -c "SELECT pg_size_pretty(pg_database_size('appdb'));"
docker stats rd-postgres --no-stream                            # CPU e memória do container
```

**Causas comuns**
| Sintoma | Causa provável |
|---|---|
| Card vermelho "PostgreSQL fora do ar" | Container parado, falha ao iniciar (erro em `postgresql.conf`), disco cheio |
| Conexões perto do limite | Aplicação sem pool, conexões vazando; ataque de brute force abrindo conexões |
| Muitas slow queries | Query sem índice, tabela crescendo, concorrência |
| Rollbacks altos | Erros na aplicação dentro de transações |
| "password authentication failed" no log | Senha errada ou brute force (veja o playbook) |
| Banco crescendo rápido | Tabela de pedidos sem limpeza; veja `db_growth_gb_per_day` |

**Recuperação**
1. `docker compose restart postgres`; espere ficar `healthy` em `docker compose ps`.
2. Se não subir, leia `docker compose logs postgres` (erro de configuração aparece na primeira linha de erro).
3. Conexões esgotadas: identifique e encerre as ociosas com `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle' AND pid <> pg_backend_pid();`.
4. Os dados ficam no volume `pgdata` e sobrevivem ao reinício. **Não** use `docker compose down -v` (apaga os dados).

---

## 3. DNS (CoreDNS)

**Verificar a saúde**
- Painel: página DNS com disponibilidade 1, tempo de resolução de poucos milissegundos.
- Consulta direta (o `nslookup` do Windows não aceita bem porta diferente; use o container do monitor):

```powershell
docker exec rd-monitor python -c "import dns.resolver as r;x=r.Resolver(configure=False);x.nameservers=['172.28.77.12'];print(x.resolve('web.lab.local','A')[0])"
```
Resposta esperada: `172.28.77.10`.

**Métricas a olhar**
`up`, `resolve_ms`, `qps`, `failure_rate` (falhas do servidor) e `nxdomain_rate` (nomes que não existem; **não** é falha do servidor).
Regras: `dns_disponibilidade`, `dns_latencia_p95` (amarelo > 100 ms, vermelho > 500 ms), `dns_falhas` (amarelo > 2%, vermelho > 10%).

**Diagnóstico**
```powershell
docker compose logs coredns --tail 50                 # uma linha por consulta
curl.exe http://localhost:9153/metrics | Select-String "coredns_dns_responses_total"
Get-Content services\coredns\Corefile                 # configuração
Get-Content services\coredns\lab.local.db             # zona (registros)
```

**Causas comuns**
| Sintoma | Causa provável |
|---|---|
| Card vermelho "DNS não responde" | Container parado; erro no `Corefile` ou no arquivo de zona |
| `failure_rate` alto | SERVFAIL ou REFUSED: zona inválida, consulta a domínio fora de `lab.local` |
| `nxdomain_rate` alto | Clientes consultando nomes que não existem (normal em pequena quantidade) |
| Latência alta | CPU do host disputada (por exemplo durante um ataque ou durante os testes) |

**Recuperação**
1. `docker compose restart coredns`.
2. Se não subir: `docker compose logs coredns`. Erros de zona (serial, ponto final faltando em nomes) aparecem no log. Corrija `services/coredns/lab.local.db`.
3. Confirme com a consulta direta acima.

---

## 4. SMTP (Mailpit)

**Verificar a saúde**
- Painel: página SMTP com disponibilidade 1, taxa de entrega 100% e fila 0.
- Interface: http://localhost:8025 abre a caixa de entrada.
- API: `curl.exe "http://localhost:8025/api/v1/messages?limit=1"` retorna JSON com `total`.

**Métricas a olhar**
`up`, `delivery_rate`, `queue_size`, `send_latency_ms`, `error_rate`, `volume_per_min`.
Regras: `smtp_disponibilidade`, `smtp_entrega` (amarelo < 95%, vermelho < 80%), `smtp_fila` (amarelo > 5, vermelho > 20), `smtp_latencia` (amarelo > 500 ms, vermelho > 2000 ms).

**Diagnóstico**
```powershell
docker compose logs mailpit --tail 50
docker compose logs monitor --tail 50 | Select-String "e-mail|alerta"      # falhas de envio de alerta
Test-NetConnection localhost -Port 1025                                      # a porta SMTP responde?
```

**Causas comuns**
| Sintoma | Causa provável |
|---|---|
| Card vermelho "SMTP fora do ar" | Container do Mailpit parado |
| Fila crescendo | Mailpit lento ou indisponível; as sondas se acumulam na fila interna do monitor |
| Taxa de entrega baixa | O e-mail é aceito mas não aparece na API (Mailpit sobrecarregado) |
| Alertas sem e-mail | Mailpit parado no momento do alerta (o aviso fica só no painel e no log) |
| Caixa de entrada cheia | `MP_MAX_MESSAGES=2000` descarta os mais antigos (normal) |

**Recuperação**
1. `docker compose restart mailpit` (a caixa de entrada é em memória e esvazia no reinício).
2. A fila interna se esvazia sozinha quando o Mailpit volta.
3. Alertas disparados enquanto o Mailpit estava fora não são reenviados; consulte a página Alertas do painel.

---

## 5. Monitor (a própria plataforma)

**Verificar a saúde**
- `curl.exe http://localhost:8000/api/health`: `"status":"ok"` e `ultimo_ciclo_ts` recente.
- Painel: "Última atualização" mudando a cada 5 s. Se a API parar, aparece uma faixa vermelha.

**Métricas a olhar**
`linhas_no_banco` (cresce com o tempo, limitado pela retenção de 24 h) e `status` (`degradado` quando a coleta atrasa mais de 15 s).

**Diagnóstico**
```powershell
docker compose ps monitor
docker compose logs monitor --tail 100                       # warnings dos coletores e do motor de alertas
docker exec rd-monitor python -c "import sqlite3;c=sqlite3.connect('/data/metrics.db');print(c.execute('select service,count(*) from metrics group by service').fetchall())"
docker stats rd-monitor --no-stream
```

**Causas comuns**
| Sintoma | Causa provável |
|---|---|
| Faixa vermelha "A API do monitor não está respondendo" | Container parado ou reiniciando |
| Status `degradado` | Um coletor lento (timeout) ou máquina sobrecarregada |
| Um card sem dados | O coletor daquele serviço falhou (veja `WARNING coletor ... falhou` no log) |
| Sem dados de CPU/memória do banco | `docker.sock` não montado ou sem permissão |
| Aba Segurança sem z-score | Menos de 2 minutos de histórico (esperado logo após subir) |
| Aba Segurança sem vulnerabilidades | O scan do Trivy ainda não foi executado |
| Alerta de configuração logo após editar `services/` | Esperado. Use "Aceitar nova baseline" se foi proposital |

**Recuperação**
1. `docker compose restart monitor`. As métricas e os incidentes ficam no volume `monitor-data` e são recarregados.
2. Reconstruir depois de mudar código ou `alerts.yaml`: `docker compose up -d --build monitor`.
3. Banco do monitor corrompido ou fora de controle (último recurso, apaga o histórico): `docker compose down` e `docker volume rm monitor-redes_monitor-data`, depois `docker compose up -d`.

---

## 6. Loadgen (gerador de tráfego)

**Verificar**: `curl.exe http://localhost:8090/mode` mostra o modo atual.
**Voltar ao normal**: `Invoke-RestMethod -Method Post http://localhost:8090/mode/normal` ou `.\scripts\demo_reset.ps1`.
**Se o painel mostrar "pico" ou "brute force" sem você ter pedido**: o modo ficou ligado depois de uma demo interrompida; mande o modo `normal`.
