# Playbooks de incidentes

Um playbook diz **o que fazer** quando um tipo de incidente acontece: qual alerta dispara, quão grave é, como investigar, como conter o problema, como resolver, quem avisar e o que aprender depois. Para os comandos de cada serviço, veja o [RUNBOOKS.md](RUNBOOKS.md).

Severidade do painel: **Amarelo** = atenção (investigar no horário normal) e **Vermelho** = crítico (agir agora). Os limiares ficam em `monitor/alerts.yaml`.

Conteúdo: 1. Serviço fora do ar, 2. Latência alta, 3. Taxa de erro alta, 4. DDoS, 5. Brute force, 6. Alteração de configuração, 7. CVE crítico.

---

## 1. Serviço fora do ar

| Item | Detalhe |
|---|---|
| **Gatilho** | `web_disponibilidade`, `db_disponibilidade`, `dns_disponibilidade` ou `smtp_disponibilidade`. E-mail `[CRÍTICO] <serviço>: ... fora do ar` |
| **Severidade** | **Vermelho** (crítico) |

**Triagem**
1. Abra o painel: qual card está vermelho? Os outros serviços estão bem?
2. `docker compose ps`: o container está `Up`, `Exited` ou `Restarting`?
3. `docker compose logs <serviço> --tail 100`: qual foi o último erro?
4. Houve mudança recente? Veja a página Alertas e o alerta de configuração alterada (playbook 6).

**Contenção**
- Se vários serviços caíram juntos, suspeite do host (Docker Desktop, memória, disco) e não do serviço individual.
- Se a causa for uma mudança de configuração, restaure o arquivo anterior (`git checkout -- services/<arquivo>`).

**Resolução**
1. `docker compose restart <serviço>` (ou `docker compose up -d <serviço>` se o container sumiu).
2. Se não subir, corrija a causa vista no log (configuração inválida, volume cheio, porta ocupada) e suba de novo.
3. Aguarde o card voltar ao verde (cerca de 15 s) e o e-mail `[RECUPERADO]`.

**Comunicação**
- Avise quem depende do serviço no início (quando o alerta crítico chega) e ao final (quando recupera).
- Mensagem sugerida: "Serviço X indisponível desde HH:MM. Causa em investigação. Próxima atualização em 15 minutos."
- Enquanto o Mailpit estiver fora, não há e-mail: a comunicação é pelo painel.

**Pós-incidente**
- Registre horário de início, fim, duração (o e-mail de recuperação traz a duração) e causa raiz.
- A detecção funcionou em quanto tempo? (esperado: 10 a 15 s)
- Ação preventiva: validar a configuração antes de aplicar (`nginx -t`), adicionar verificação, melhorar o limite de recursos.

---

## 2. Latência alta

| Item | Detalhe |
|---|---|
| **Gatilho** | `web_latencia_p95` (amarelo > 300 ms, vermelho > 1000 ms), `dns_latencia_p95` (amarelo > 100 ms, vermelho > 500 ms), `smtp_latencia` (amarelo > 500 ms, vermelho > 2000 ms), `db_slow_queries` |
| **Severidade** | **Amarelo** a **Vermelho**, conforme o limiar |

**Triagem**
1. Os gráficos de RPS, QPS e CPU subiram junto? Latência alta com tráfego alto indica saturação (ou ataque, playbook 4).
2. Latência alta com tráfego normal indica problema do próprio serviço ou do host.
3. No banco: veja as queries mais lentas (`pg_stat_statements`, comandos no runbook do banco).
4. Outros serviços também ficaram lentos ao mesmo tempo? Provável falta de CPU ou memória no host.

**Contenção**
- Reduza a carga se possível (por exemplo, pare testes e demos: `.\scripts\demo_reset.ps1`).
- Se for tráfego legítimo crescendo, aumente recursos do Docker Desktop (memória e CPUs).

**Resolução**
1. Corrija a causa: índice para a query lenta, reinício do serviço travado, mais recursos.
2. Confirme que o p95 voltou ao normal e o card ao verde (a janela é de 60 s, então a recuperação leva cerca de 1 a 1,5 minuto).

**Comunicação**
- Amarelo: avise a equipe do serviço, sem urgência. Vermelho: trate como degradação e comunique usuários afetados.

**Pós-incidente**
- Registre qual métrica estourou, o valor máximo e o que mudou.
- Ajuste limiares se estiverem muito sensíveis, ou adicione capacidade/índices.

---

## 3. Taxa de erro alta

| Item | Detalhe |
|---|---|
| **Gatilho** | `web_erros_5xx` (amarelo > 5%, vermelho > 15%), `db_rollbacks` (amarelo > 0,5/s, vermelho > 2/s), `dns_falhas` (amarelo > 2%, vermelho > 10%), `smtp_entrega` (amarelo < 95%, vermelho < 80%) |
| **Severidade** | **Amarelo** a **Vermelho** |

**Triagem**
1. Identifique o tipo de erro: 5xx (falha do servidor), rollbacks (erro em transações), SERVFAIL/REFUSED (falha do DNS), e-mails não confirmados (SMTP).
2. Web: veja a contagem por código HTTP e o log (`docker exec rd-nginx tail -n 50 /var/log/nginx-json/access.log`), procurando o caminho (`uri`) que mais erra.
3. DNS: separe `nxdomain_rate` (cliente perguntou algo que não existe, não é falha) de `failure_rate` (falha do servidor).
4. Banco: `docker compose logs postgres` para ver os erros que causam rollback.
5. Houve deploy ou mudança de configuração pouco antes?

**Contenção**
- Se for uma rota específica com erro, desvie o tráfego ou retire a rota até corrigir.
- Reverta a mudança recente se coincidir com o início dos erros.

**Resolução**
1. Corrija a causa (bug, configuração, dependência indisponível) e reinicie o serviço se necessário.
2. Confirme a queda da taxa de erro (as janelas são de 30 a 60 s) e o `[RECUPERADO]`.

**Comunicação**
- Informe a equipe responsável pela aplicação com: rota, código e horário de início. Em vermelho, avise os usuários afetados.

**Pós-incidente**
- Registre a causa raiz, o percentual máximo de erro e quantas requisições foram afetadas.
- Adicione teste automatizado que cubra o caso e revise os limiares.

---

## 4. DDoS (pico anormal de tráfego)

| Item | Detalhe |
|---|---|
| **Gatilho** | `sec_ddos_zscore` (amarelo z > 3, vermelho z > 6) e `sec_ddos_razao` (vermelho se RPS > 10x a baseline). E-mail `[CRÍTICO] security: Anomalia de tráfego` com o top 5 de IPs |
| **Severidade** | **Amarelo** a **Vermelho** (crítico) |

**Triagem**
1. Aba Segurança, bloco "Anomalia de tráfego": RPS atual, baseline, z-score e razão.
2. Veja o **top 5 IPs por volume**: poucos IPs concentrando o tráfego indicam ataque ou cliente mal comportado; muitos IPs com volume parecido sugerem aumento legítimo (campanha, notícia).
3. Veja os códigos HTTP (muitos 200 na raiz, ou muitos 404 em caminhos aleatórios) e o `user_agent` no log.
4. A latência e os erros do Web também pioraram? Se sim, o serviço já está sendo afetado.

**Contenção**
- Bloqueie os IPs atacantes na borda (firewall, WAF, ou CDN). No laboratório: o ataque é simulado, e o modo volta ao normal com `Invoke-RestMethod -Method Post http://localhost:8090/mode/normal`.
- Em produção, ative limitação de taxa (`limit_req` do nginx), cache e proteção de CDN. Não bloqueie IPs sem confirmar que são atacantes.
- Guarde o log do período para análise (`docker exec rd-nginx cat /var/log/nginx-json/access.log`).

**Resolução**
1. Confirme a queda do RPS e do z-score (a baseline não absorve o ataque, então o alerta resolve ao voltar ao normal, em cerca de 20 s).
2. Remova bloqueios temporários que não sejam mais necessários.

**Comunicação**
- Avise a equipe de infraestrutura e de segurança. Se o serviço ficou degradado, comunique os usuários.
- Se for produção, acione o provedor de rede ou CDN.

**Pós-incidente**
- Registre início, fim, pico de RPS, IPs de origem e efeito no serviço.
- Revise limites de taxa, capacidade e a regra (os limiares de z-score e razão).
- Atenção: um brute force também eleva o RPS e pode disparar este alerta (veja o playbook 5).

---

## 5. Brute force (tentativas repetidas de login)

| Item | Detalhe |
|---|---|
| **Gatilho** | `sec_bruteforce_ip` (amarelo > 10, vermelho > 30 falhas do mesmo IP em 60 s). Fontes: 401 em `/admin` (nginx) e "password authentication failed" (Postgres). E-mail `[CRÍTICO] security: Brute force` |
| **Severidade** | **Amarelo** a **Vermelho** |

**Triagem**
1. Aba Segurança, bloco "Brute force": tabela de IPs suspeitos (IP, fonte, falhas, primeiro e último visto) e contas alvo.
2. Um IP com muitas falhas em uma conta (por exemplo `admin`) indica ataque direcionado. Muitas contas com poucas falhas cada indica *password spraying*.
3. Houve algum **sucesso** depois das falhas? Procure no log do nginx por status 200 em `/admin` do mesmo IP (`docker exec rd-nginx grep '"uri":"/admin' /var/log/nginx-json/access.log`).
4. Falhas no Postgres vindas de um IP interno (por exemplo o loadgen) indicam aplicação com senha errada ou atacante dentro da rede.

**Contenção**
- Bloqueie o IP atacante na borda e, se possível, limite tentativas por IP (`limit_req` no `/admin`).
- Se houve sucesso, trate como **comprometimento**: troque a senha da conta imediatamente e revogue sessões.
- No laboratório, volte ao modo normal: `Invoke-RestMethod -Method Post http://localhost:8090/mode/normal`.

**Resolução**
1. Troque as senhas das contas atacadas (use senhas fortes), mantenha autenticação multifator quando houver.
2. Confirme que as falhas por IP caíram e o alerta resolveu (a janela é de 60 s, então leva cerca de 70 s).

**Comunicação**
- Avise a equipe de segurança com IPs, contas, horários e se houve sucesso.
- Em caso de comprometimento, siga o processo de resposta a incidentes da organização e notifique os afetados.

**Pós-incidente**
- Registre IPs, contas, volume e duração. Adicione bloqueio automático (por exemplo fail2ban) e proteção adicional no `/admin` (restrição por rede).
- Revise a política de senhas.

---

## 6. Alteração de configuração

| Item | Detalhe |
|---|---|
| **Gatilho** | `sec_config` (amarelo se 1 a 3 arquivos diferem da baseline, vermelho se mais de 3). E-mail `[ATENÇÃO] security: Arquivo de configuração alterado` com nome do arquivo, hash antigo, hash novo e diff |
| **Severidade** | **Amarelo** (atenção); **Vermelho** se muitos arquivos mudaram |

**Triagem**
1. Aba Segurança, bloco "Alteração de configuração (SHA-256)": quais arquivos aparecem como ALTERADO e qual o diff.
2. A mudança foi **planejada**? Verifique com a equipe, o histórico do Git (`git log -p -- <arquivo>`) e o horário.
3. O diff mostra algo perigoso (porta aberta, autenticação desligada, `allow all`, nova rota)?

**Contenção**
- Se a alteração **não foi autorizada**, restaure o arquivo: `git checkout -- services/<caminho>` (se o arquivo está versionado) e reinicie o serviço correspondente (`docker compose restart nginx`).
- Investigue como o arquivo foi alterado (quem acessou o host, qual processo).

**Resolução**
1. Alteração indevida: restaure o arquivo. O alerta resolve sozinho em cerca de 10 s depois que o hash volta ao da baseline.
2. Alteração legítima: clique em **"Aceitar nova baseline"** na aba Segurança (ou `Invoke-RestMethod -Method Post http://localhost:8000/api/security/config/accept`) e registre a mudança no Git.

**Comunicação**
- Alteração não autorizada: avise a segurança. Legítima: avise a equipe que a baseline foi atualizada.

**Pós-incidente**
- Registre quem, quando e por quê. Reforce o controle de mudanças (toda mudança passa por commit e revisão).
- Se foi um erro humano, adicione validação automática antes de aplicar configurações.

---

## 7. CVE crítico

| Item | Detalhe |
|---|---|
| **Gatilho** | `sec_vuln_critical` (amarelo se houver CRITICAL, vermelho acima de 10). E-mail `[ATENÇÃO] security: Vulnerabilidades CRITICAL nas imagens (Trivy)` |
| **Severidade** | **Amarelo** (atenção) até 10 CRITICAL; **Vermelho** acima disso |

**Triagem**
1. Aba Segurança, bloco "Vulnerabilidades conhecidas": qual serviço e imagem tem CRITICAL, e a lista dos principais CVEs com pacote, versão instalada e versão corrigida.
2. Para cada CVE, abra o link (NVD ou fornecedor) e responda: o pacote é **usado** pelo serviço? A falha é explorável remotamente neste cenário (rede, sem autenticação)? Existe correção (`Corrigida em`)?
3. Priorize: CVSS alto + explorável + serviço exposto + correção disponível.

**Contenção**
- Se o serviço está exposto e a falha é explorável, restrinja o acesso (rede, firewall) até corrigir.
- Se não há correção, avalie mitigações (desativar o recurso afetado, regra de WAF).

**Resolução**
1. Atualize a imagem para uma versão com a correção (altere a tag no `docker-compose.yml`, por exemplo para uma versão mais nova da mesma linha estável) e suba: `docker compose pull` e `docker compose up -d`.
2. Rode os testes (`python -m pytest tests/e2e`) para garantir que nada quebrou.
3. Escaneie de novo: `docker compose --profile scan run --rm trivy`. O alerta resolve quando o número de CRITICAL cai a zero (cerca de 15 s depois de o monitor ler o novo JSON).

**Comunicação**
- Informe a segurança e os donos do serviço com: CVE, serviço, gravidade, prazo para corrigir e a exposição.

**Pós-incidente**
- Registre o "antes e depois" de CVEs (veja o relatório de processo).
- Automatize: escaneie as imagens periodicamente e fixe versões (nunca `latest`) para não receber atualizações sem testar.
- Lembre que o resultado depende do banco de vulnerabilidades do scanner, que deve estar atualizado.
