# Relatório de processo: Plataforma de Monitoramento para DevOps

Documento para quem vai apresentar o projeto. Cada fase tem as mesmas sete seções.

---

## Fase 1: infraestrutura, coletores, armazenamento e API

### 1. O que foi feito

- Arquivos de base: `CLAUDE.md` (regras do projeto), `.gitignore`, `.gitattributes` (força fim de linha LF), `README.md`.
- `docker-compose.yml` com 6 containers numa rede própria `172.28.77.0/24` com IPs fixos: nginx (.10), postgres (.11), coredns (.12), mailpit (.13), monitor (.20), loadgen (.21).
- Configurações dos serviços em `services/<nome>/`: `nginx.conf`, `postgresql.conf` e `init.sql`, `Corefile` e zona `lab.local.db`, `mailpit.env`.
- App `monitor` (Python 3.12 e FastAPI) com quatro coletores assíncronos que rodam a cada 5 s:
  - `web.py`: HTTP check, `stub_status` e leitura do access log JSON.
  - `postgres.py`: views de estatística do Postgres e CPU/memória do container.
  - `dns_check.py`: consulta DNS real e métricas Prometheus do CoreDNS.
  - `smtp_check.py`: fila interna, envio de e-mails sintéticos e confirmação pela API do Mailpit.
- Armazenamento em SQLite (`storage.py`): tabela `metrics(ts, service, metric, value, labels)` em modo WAL, com retenção de 24 h. A tabela `alerts` já existe, mas só será usada na fase de alertas.
- API REST: `/api/health`, `/api/services`, `/api/metrics?service=&metric=&since=` e `/api/alerts`, além de uma página placeholder em `/`.
- `loadgen` no modo `normal`: HTTP (200, 404, 500 e 401), queries no Postgres (leitura, escrita, agregação, lentas e com erro), DNS (válido e inválido) e e-mails.

### 2. Decisões e alternativas

| Decisão | Por que | Alternativa |
|---|---|---|
| Rede Docker com IPs fixos | O DNS `lab.local` aponta para os IPs reais dos containers, e o monitor fala com o CoreDNS por IP | Deixar o Docker sortear IPs e usar só nomes (mais simples, mas o registro A não bateria com a realidade) |
| Portas do host: 8081, 5433, 1053, 8000 | Evitam conflito com serviços do Windows (a porta 53 do host já estava em uso) | Usar as portas padrão e quebrar em máquinas com serviço local |
| SQLite com uma tabela só (série temporal) | É simples, não precisa de servidor e atende ao requisito | InfluxDB ou Prometheus (mais poderosos, mas mais peças para explicar) |
| `asyncio` nos coletores | Os 4 coletores esperam rede (I/O). Esperar em paralelo faz o ciclo durar o tempo do mais lento, não a soma | Threads ou um processo por coletor (mais pesado) |
| Gravação no SQLite com `asyncio.to_thread` | O módulo `sqlite3` é síncrono. Rodar em outra thread evita travar o laço de coleta | Biblioteca `aiosqlite` (uma dependência a mais) |
| Métricas guardadas já como taxa (RPS, QPS) | O front só desenha o valor. A conta `(contador agora - contador antes) / segundos` fica no coletor | Guardar o contador bruto e calcular na consulta (mais flexível, mais complexo) |
| Log do nginx em JSON num volume compartilhado | Contar códigos HTTP sem regex e sem ler o log do Docker | `stub_status` não dá contagem por código; o log de acesso em texto exigiria regex |
| Usuário `monitor` com papel `pg_monitor` | Princípio do menor privilégio: lê estatísticas, não altera dados | Usar o superusuário `app` (funciona, mas é pior em segurança) |
| `docker.sock` montado em modo leitura | É a forma de ler CPU e memória do container do Postgres | `cAdvisor` (um container a mais) ou deixar essas métricas de fora. Atenção: acesso ao `docker.sock` é poderoso, mesmo `:ro` |
| Slow queries via `pg_stat_statements` | Não precisa ler o log do Postgres. Conta chamadas de queries com tempo médio de 200 ms ou mais | Ler o log gerado por `log_min_duration_statement` (o log também está ativo e aparece em `docker logs rd-postgres`) |
| Sondas SMTP apagadas do Mailpit após confirmar | A caixa de entrada não enche de e-mails de teste e continua legível para os alertas | Manter todos (a UI fica poluída) |

### 3. Conceitos de redes envolvidos

**Modelo TCP/IP em 4 camadas**: Aplicação (HTTP, DNS, SMTP, protocolo do Postgres), Transporte (TCP ou UDP, com portas), Internet (IP) e Enlace/Física. O OSI tem 7 camadas, e HTTP, DNS e SMTP ficam na camada 7 (aplicação). TCP e UDP ficam na 4 (transporte). IP fica na 3 (rede).

**Porta**: número de 16 bits que diz qual programa dentro da máquina deve receber o pacote. O IP leva o pacote até a máquina e a porta escolhe o programa. Usadas aqui: HTTP 80, PostgreSQL 5432, DNS 53, SMTP 1025 (a padrão é 25, o Mailpit usa 1025 para não exigir privilégio), métricas do CoreDNS 9153.

**TCP versus UDP**
- TCP: orientado a conexão, com handshake de 3 vias (SYN, SYN-ACK, ACK), entrega confiável e ordenada. Usado por HTTP, PostgreSQL e SMTP, que não toleram perda de dados.
- UDP: sem conexão, sem garantia, só "manda e pronto". É mais rápido e leve. O **DNS usa UDP 53** porque a consulta e a resposta cabem em um pacote cada, então o handshake do TCP custaria mais que a própria resposta. Se a resposta for grande demais, o servidor marca "truncada" e o cliente repete por **TCP 53**. Por isso o compose publica a porta 53 nos dois protocolos.

**Como cada métrica é obtida na prática**
- **Disponibilidade web (HTTP check)**: o monitor abre uma conexão TCP na porta 80, envia `GET /` e mede o tempo até a resposta. Se vier status menor que 500, está "up". A latência inclui o handshake, porque o monitor abre uma conexão nova a cada checagem.
- **`stub_status` do nginx**: página de texto com 3 informações. `Active connections` (conexões abertas agora), `accepts handled requests` (três contadores acumulados desde que o nginx subiu: conexões aceitas, conexões tratadas e requisições totais) e `Reading/Writing/Waiting` (estado das conexões). O **RPS** (requisições por segundo) é a diferença do contador `requests` entre duas leituras dividida pelos segundos entre elas.
- **Taxa de erro e contagem por código**: a cada ciclo o monitor lê as linhas novas do access log JSON e conta quantas respostas tiveram cada status. Códigos 4xx são erros do cliente (404 não encontrado, 401 não autorizado). Códigos 5xx são erros do servidor (500). A taxa é `erros / total da janela * 100`.
- **QPS** (queries por segundo): o mesmo cálculo de taxa. No Postgres, a soma de `calls` do `pg_stat_statements` é um contador que só cresce, e o QPS é a variação dele por segundo. No DNS, o contador é `coredns_dns_requests_total`.
- **Rollbacks**: `xact_rollback` da view `pg_stat_database`. Uma transação que termina em erro é desfeita (ROLLBACK) e incrementa esse contador. O loadgen provoca `SELECT 1/0` de propósito.
- **Conexões abertas**: `count(*)` em `pg_stat_activity`, que lista as sessões TCP abertas no banco.
- **Tamanho e crescimento**: `pg_database_size()`. O crescimento é a diferença entre o tamanho atual e o mais antigo guardado em memória, convertida para bytes por minuto.
- **CPU, memória e IO do container**: o monitor conversa com o daemon do Docker pelo socket Unix `/var/run/docker.sock` (API `/containers/<nome>/stats`). A CPU é a variação do tempo de CPU do container dividida pela variação do tempo de CPU do sistema.
- **Tempo de resolução DNS**: o monitor faz uma consulta real do tipo A para `web.lab.local` por UDP 53 e mede o tempo. A **taxa de falha** vem das métricas do CoreDNS: proporção de respostas com `rcode` diferente de `NOERROR`. `NXDOMAIN` significa "esse nome não existe" e é o que o loadgen provoca ao perguntar por nomes inexistentes.
- **SMTP**: o monitor abre TCP na 1025 e lê o banner `220` que todo servidor SMTP envia ao conectar (disponibilidade). Depois envia um e-mail de teste, mede o tempo e pergunta à API do Mailpit se ele chegou (taxa de entrega). A **fila** é uma `asyncio.Queue` interna do monitor: se o Mailpit cair, os e-mails de teste se acumulam nela.
- **Formato Prometheus**: formato de texto `nome{rotulo="valor"} número`, usado pelo CoreDNS na porta 9153. O monitor tem um parser pequeno em `util.py`.

### 4. Fluxo do dado: do serviço até o gráfico

```
 SERVIÇO                COLETOR (monitor, a cada 5 s)         ARMAZENAMENTO      API                    TELA (fase 2)
 nginx  :80  ---------> web.py     (HTTP + stub_status + log) --\
 postgres :5432 -------> postgres.py (SQL + docker.sock)      ---+--> SQLite -----> /api/metrics ------> Chart.js
 coredns :53/:9153 ----> dns_check.py (UDP 53 + /metrics)     ---+    metrics.db     /api/services       (fetch a
 mailpit :1025/:8025 --> smtp_check.py (fila + SMTP + API)    --/                    /api/alerts          cada 5 s)
```

1. O serviço gera o dado (por exemplo o nginx incrementa o contador de requisições).
2. O coletor lê (HTTP, SQL, DNS, SMTP), transforma em número e devolve uma lista `(metrica, valor, labels)`.
3. `main.py` junta o resultado dos 4 coletores e grava tudo com o mesmo `ts` no SQLite.
4. A API lê o SQLite e devolve JSON.
5. Na fase 2 o navegador chamará a API a cada poucos segundos e o Chart.js desenhará as séries.

### 5. Comandos para rodar e verificar

```powershell
docker compose up -d --build        # sobe tudo
docker compose ps                   # os 6 containers devem estar Up
docker compose logs -f monitor      # logs do monitor (warnings de coletor aparecem aqui)
curl.exe localhost:8000/api/health
curl.exe localhost:8000/api/services
curl.exe "localhost:8000/api/metrics?service=web&metric=rps&since=5m"
curl.exe "localhost:8000/api/metrics?service=dns&since=1m"
curl.exe -i localhost:8081/admin                      # 401 sem senha
curl.exe -u admin:admin123 -i localhost:8081/admin/   # 200 com senha
docker exec rd-monitor python -c "import sqlite3;c=sqlite3.connect('/data/metrics.db');print(c.execute('select service,count(*) from metrics group by service').fetchall())"
docker exec rd-monitor python -c "import dns.resolver as r;x=r.Resolver(configure=False);x.nameservers=['172.28.77.12'];print(x.resolve('web.lab.local','A')[0])"   # consulta DNS direta ao CoreDNS (esperado: 172.28.77.10)
docker compose down                 # para (use -v para apagar os dados)
```

Interfaces: monitor em http://localhost:8000, Swagger em `/docs`, Mailpit em http://localhost:8025.

### 6. Perguntas que a professora pode fazer

- **Por que o DNS usa UDP?** Consulta e resposta cabem em um pacote cada. O UDP evita o custo do handshake do TCP. Se a resposta for grande, o cliente repete por TCP.
- **O que é QPS?** Queries por segundo: quantas consultas o serviço recebe por segundo. Calculado pela variação de um contador entre duas leituras.
- **O que o `stub_status` mostra?** Conexões ativas e contadores acumulados de conexões aceitas, tratadas e requisições, mais o estado das conexões (lendo, escrevendo, esperando).
- **Qual a diferença entre 4xx e 5xx?** 4xx é erro do cliente (pediu algo errado ou sem permissão). 5xx é erro do servidor (falhou ao atender).
- **Por que HTTP e Postgres usam TCP?** Precisam de entrega confiável e ordenada. Perder um pedaço de uma resposta ou de uma query corromperia a comunicação.
- **O que é NXDOMAIN?** Código de resposta DNS que diz que o nome consultado não existe.
- **Como vocês sabem que o e-mail foi entregue?** O servidor SMTP aceitar a mensagem só prova o envio. Confirmamos consultando a API do Mailpit, que confirma que ela chegou à caixa.
- **Por que o monitor abre conexão nova a cada checagem?** Para medir também o handshake TCP, como um cliente novo sentiria.
- **Por que a rede Docker tem IPs fixos?** Para a zona DNS `lab.local` apontar para IPs reais, e para o monitor consultar o CoreDNS por IP.
- **O que é `pg_stat_statements`?** Extensão do Postgres que guarda estatísticas por tipo de query: nº de chamadas, tempo médio e total.
- **Por que o monitor usa um usuário separado no banco?** Menor privilégio: só lê estatísticas.

### 7. Problemas encontrados e como foram resolvidos

1. **Porta 53 do host já em uso no Windows** (o serviço de DNS local usa essa porta). Solução: publicar o CoreDNS em 1053 (UDP e TCP). Dentro da rede Docker ele continua na 53.
2. **Códigos HTTP "grudados" no dashboard**: um código que aparecia uma vez (ex.: 404) continuava mostrando o valor antigo, porque a API pega o último valor de cada série e a série parava de receber pontos. Solução: o coletor passou a gravar `0` para códigos já vistos que não apareceram na janela. Mesma correção no `rcode` do DNS.
3. **Fila SMTP sempre valia 1**: a fila era medida depois de enfileirar a sonda. Solução: medir antes, assim só passa de 0 quando o envio está atrasado.
4. **Log barulhento**: a biblioteca `httpx` registrava cada requisição interna do monitor. Solução: nível `WARNING` para o logger `httpx`.
5. **Fim de linha no Windows**: o Git pode converter para CRLF e quebrar `nginx.conf`, `Corefile` ou `htpasswd` dentro dos containers Linux. Solução: `.gitattributes` com `eol=lf`.
6. **Slow queries por média**: a contagem usa a média do `pg_stat_statements` (200 ms ou mais). Se a média de uma query cair depois, a soma pode diminuir e o valor é tratado como 0 naquele ciclo. É uma aproximação aceitável para o laboratório. O log `log_min_duration_statement` registra cada query lenta individualmente (`docker logs rd-postgres`).
7. **`nslookup` do Windows não respondeu na porta 1053**: o `nslookup` do Windows costuma falhar com porta customizada (ele tenta antes um DNS reverso do servidor). Um teste direto em Python por UDP e TCP para `127.0.0.1:1053` confirmou que o CoreDNS responde. Para demonstrar, use o comando via `docker exec` da seção 5.


---

## Ajustes pós-Fase 1

1. **Loadgen calibrado para o modo normal ficar verde.** Respostas HTTP: cerca de 94% de sucesso, 4% de 404, 0,6% de 500 e 0,4% de 401. DNS: 4% de nomes inexistentes (antes 15%). Queries lentas: 1,5% (antes 3%). Medido depois: erro 4xx médio 3,7%, 5xx médio 0,6%, NXDOMAIN médio 2,9%.
2. **Taxas em janela de 30 s.** Taxa de erro calculada só com os 5 s do último ciclo oscila demais (um erro em 25 requisições vira 4%). O coletor agora soma os últimos 30 s (classe `Janela` em `util.py`).
3. **DNS com duas métricas separadas.**
   - `nxdomain_rate`: percentual de respostas `NXDOMAIN` ("esse nome não existe"). É uma resposta **válida**: o servidor funcionou e o cliente perguntou por um nome errado. É erro do cliente e não gera alerta.
   - `failure_rate`: percentual de respostas `SERVFAIL`, `REFUSED` e similares, somado aos timeouts da sonda do monitor. É falha do **servidor**: ele não conseguiu ou não quis responder. **Só esta dispara alerta.**
   - Por que separar: se NXDOMAIN contasse como falha, um usuário digitando um domínio errado deixaria o painel vermelho sem que nada estivesse quebrado.
4. **Crescimento do banco.** `db_growth_mb_per_h` e `db_growth_gb_per_day` (projeção linear: MB/h vezes 24, dividido por 1024). São calculados comparando o tamanho atual com a leitura mais antiga dos últimos 15 min, buscada no próprio SQLite (`storage.first_value`). Só aparecem depois de 60 s de histórico.
5. **Repositório remoto** configurado em https://github.com/tiagolm16/monitor-redes. O primeiro push exige login no GitHub.

---

## Fase 2: front-end e alertas

### 1. O que foi feito

- **Motor de alertas** (`monitor/app/alerts.py`) com regras em `monitor/alerts.yaml`: 14 regras em 4 serviços, 3 níveis, histerese por número de ciclos, agregações (último, média, máximo, soma, p95).
- **E-mails** `[ATENÇÃO]`, `[CRÍTICO]` e `[RECUPERADO]`, em HTML simples com serviço, métrica, valor atual, limiar, horário e link para o dashboard. Padrão: Mailpit. Opcional: SMTP real por variáveis de ambiente, sem credencial no repositório (`.env` ignorado pelo Git).
- **Histórico** na tabela `alerts`: uma linha por incidente, com nível atual, pior nível, abertura, resolução e a lista de eventos (cada mudança de nível).
- **API nova ou ampliada**: `/api/services` agora traz `nivel` e `alertas_ativos`; `/api/alerts` aceita `service`, `level`, `active` e `limit`; `/api/alert-rules` mostra cada regra com o valor avaliado agora.
- **Front-end** estático (HTML, CSS e JS puros, Chart.js por CDN): Visão Geral (card por serviço com cor, 3 métricas, mini gráfico, alertas ativos e últimos alertas), uma página por serviço com todos os gráficos obrigatórios e seletor de 5 min, 15 min ou 1 hora, página de Alertas (ativos em destaque, filtros por nível e serviço, tabela de regras) e Segurança como placeholder. Tema escuro, responsivo, atualização a cada 5 s, indicador de última atualização e faixa de aviso se a API parar.
- **Screenshots** em `docs/img/` (desktop e celular).

### 2. Decisões e alternativas

| Decisão | Por que | Alternativa |
|---|---|---|
| Regras em YAML | Legível, editável sem mexer em código, e a professora vê os limiares num arquivo | Regras no código Python (mais rápido, menos transparente) |
| Histerese por número de ciclos | Evita alerta por um pico de 1 leitura e evita "pisca-pisca" na recuperação | Alertar na primeira leitura ruim (gera spam e falsos positivos) |
| Agregação sobre janela (p95, média, soma) | Latência e erros oscilam. Comparar um número que resume 1 minuto é mais justo que uma leitura isolada | Comparar sempre a última leitura |
| Um incidente = uma linha com lista de eventos | Mostra abertura, mudanças e resolução num só registro | Uma linha por evento (mais difícil de ler no histórico) |
| Motor no mesmo processo do monitor, logo após gravar o ciclo | Sem fila nem processo extra, lê os dados recém gravados | Serviço separado de alertas (mais flexível, mais peças) |
| Front sem framework, roteamento por `#hash` | Sem build nem npm, fácil de explicar; o FastAPI só serve arquivos estáticos | React ou Vue (produtivo em apps grandes, mas exige build) |
| Gráficos com eixo de categorias (hora formatada) | Não precisa de adaptador de datas para o Chart.js | Escala de tempo do Chart.js com adaptador |
| Estado dos alertas reidratado do SQLite ao iniciar | Reiniciar o monitor com incidente aberto não gera e-mail duplicado | Começar sempre do verde |
| Variável `SMTP_TLS` (e não `TLS`) | Nome mais claro e sem risco de colidir com outra variável | `TLS` |

### 3. Conceitos de redes envolvidos

**Como o e-mail sai (SMTP).** O monitor abre uma conexão **TCP na porta 1025** do Mailpit (em servidor real seria 25, 587 ou 465) e conversa em texto:

```
S: 220 mailpit ESMTP                      (banner: servidor pronto)
C: EHLO monitor                           (cliente se apresenta e pergunta as extensões)
S: 250-... 250 ...
C: MAIL FROM:<alertas@lab.local>          (envelope: quem envia)
S: 250 ok
C: RCPT TO:<ops@lab.local>                (envelope: para quem)
S: 250 ok
C: DATA                                   (a partir daqui vem a mensagem)
S: 354 end data with <CR><LF>.<CR><LF>
C: Subject: [CRÍTICO] db: ... (cabeçalhos + corpo HTML) .
S: 250 queued
C: QUIT
```

`MAIL FROM` e `RCPT TO` formam o **envelope** (usado na entrega). Os cabeçalhos `From:` e `To:` dentro do `DATA` são o que o leitor vê. Em SMTP real, a porta 587 inicia em texto e muda para criptografado com o comando `STARTTLS`; a 465 já começa criptografada (TLS implícito). É o que as opções `starttls` e `ssl` de `SMTP_TLS` fazem. SMTP está na camada de aplicação e usa TCP.

**HTTP nas duas pontas.** O navegador chama a API REST do monitor por HTTP (TCP 8000) a cada 5 s com `fetch`, e a resposta é JSON. É o mesmo princípio do monitor chamando o nginx, só que invertido.

**Latência p95.** Percentil 95: o valor abaixo do qual ficam 95% das medições. Se em 60 s tivemos 12 medições e a lista ordenada termina em `..., 60, 80, 215`, o p95 é 215. Ele mostra quase o pior caso, mas não é dominado por um único outlier extremo como o máximo.

### 4. Fluxo do dado: do serviço até o gráfico

```
serviço -> coletor (5 s) -> SQLite (metrics) -+-> motor de alertas -> SQLite (alerts) -> e-mail (SMTP 1025) -> Mailpit
                                              |
                                              +-> API REST (/api/services, /metrics, /alerts) -> fetch a cada 5 s -> Chart.js
```

1. O coletor grava as métricas do ciclo.
2. Logo depois o motor lê o SQLite, agrega cada regra, compara com os limiares e aplica a histerese.
3. Se o nível oficial mudou, grava o incidente e dispara o e-mail em segundo plano (falha de SMTP não trava a coleta).
4. O navegador pede `/api/health`, `/api/services`, `/api/metrics` e `/api/alerts`. O Chart.js redesenha sem animação, então a tela não pisca.

### 5. Como o motor decide o nível (exemplo numérico)

Regra `web_latencia_p95`: operador `>`, amarelo 300 ms, vermelho 1000 ms, 3 ciclos para piorar e 3 para melhorar. Cada ciclo dura 5 s.

| Ciclo | p95 medido | Nível "bruto" | Contagem | Nível oficial | O que acontece |
|---|---|---|---|---|---|
| 1 | 80 | verde | 0 | verde | nada |
| 2 | 350 | amarelo | 1 | verde | ainda não, só 1 leitura |
| 3 | 90 | verde | 0 | verde | voltou, contagem zera (pico isolado, sem e-mail) |
| 4 a 6 | 350, 400, 380 | amarelo | 1, 2, 3 | **amarelo** | no ciclo 6 abre incidente, e-mail `[ATENÇÃO]` |
| 7 a 9 | 1200 | vermelho | 1, 2, 3 | **vermelho** | no ciclo 9, e-mail `[CRÍTICO]` |
| 10 a 12 | 120 | verde | 1, 2, 3 | **verde** | no ciclo 12 resolve e envia `[RECUPERADO]` |

Regras de decisão: o nível bruto é vermelho se o valor ultrapassa o limiar vermelho, senão amarelo se ultrapassa o amarelo, senão verde. O nível oficial só muda depois de N leituras seguidas no mesmo novo nível. A cor do serviço é o pior nível entre as suas regras.

**Por que histerese (duração mínima).** Sem ela, uma única medição ruim (um pacote atrasado, uma query lenta) gera e-mail, e uma métrica que oscila em torno do limiar gera uma enxurrada de "caiu, voltou, caiu". Exigir N ciclos seguidos filtra ruído e só deixa passar problemas que se mantêm. O custo é um atraso na detecção (10 a 15 s), aceitável aqui. Para um serviço cair usamos 2 ciclos (10 s) e para recuperar 3 (15 s), para ter certeza de que estabilizou. Não há reenvio enquanto o nível não muda.

### 6. Tabela de regras de alerta (limiares finais)

| Serviço | Regra | Métrica e agregação | Amarelo | Vermelho | Ciclos (piora/melhora) |
|---|---|---|---|---|---|
| web | Disponibilidade | `up`, último | n/a | `< 1` | 2 / 3 |
| web | Latência HTTP | `latency_ms`, p95 de 60 s | `> 300 ms` | `> 1000 ms` | 3 / 3 |
| web | Taxa de erro 5xx | `error_rate_5xx` (janela 30 s) | `> 5%` | `> 15%` | 3 / 3 |
| db | Disponibilidade | `up`, último | n/a | `< 1` | 2 / 3 |
| db | Conexões em uso | `connections_percent`, último | `> 70%` | `> 90%` | 3 / 3 |
| db | Slow queries | `slow_queries`, soma de 60 s | `> 8` | `> 20` | 3 / 3 |
| db | Rollbacks | `rollbacks_per_s`, média de 60 s | `> 0,5/s` | `> 2/s` | 3 / 3 |
| dns | Disponibilidade | `up`, último | n/a | `< 1` | 2 / 3 |
| dns | Tempo de resolução | `resolve_ms`, p95 de 60 s | `> 100 ms` | `> 500 ms` | 3 / 3 |
| dns | Falhas do servidor | `failure_rate` (janela 30 s) | `> 2%` | `> 10%` | 3 / 3 |
| smtp | Disponibilidade | `up`, último | n/a | `< 1` | 2 / 3 |
| smtp | Taxa de entrega | `delivery_rate`, último (janela 60 s) | `< 95%` | `< 80%` | 3 / 3 |
| smtp | Fila de envio | `queue_size`, último | `> 5` | `> 20` | 3 / 3 |
| smtp | Latência de envio | `send_latency_ms`, média de 60 s | `> 500 ms` | `> 2000 ms` | 3 / 3 |

### 7. Comandos para rodar e verificar

```powershell
docker compose up -d --build
# Dashboard: http://localhost:8000   Mailpit: http://localhost:8025
curl.exe localhost:8000/api/alert-rules              # estado de cada regra
curl.exe "localhost:8000/api/alerts?active=true"     # incidentes abertos

# Teste de queda do banco
docker compose stop postgres      # em ~10 s o card fica vermelho e chega [CRÍTICO] no Mailpit
docker compose start postgres     # em ~15 s chega [RECUPERADO]

# Teste de queda do nginx
docker compose stop nginx
docker compose start nginx
```

**Resultado dos testes de queda (executados de verdade):**

| Teste | Parada | Vermelho + e-mail | Volta | Recuperado + e-mail |
|---|---|---|---|---|
| PostgreSQL | 17:06:53 | 17:07:04 (11 s), `[CRÍTICO] db: PostgreSQL fora do ar` | 17:07:10 | 17:07:22, `[RECUPERADO] db: ...` (incidente de 18 s) |
| nginx | 17:07:32 | 17:07:46 (14 s), `[CRÍTICO] web: Web fora do ar (HTTP check)` | 17:07:56 | 17:08:12, `[RECUPERADO] web: ...` |

Cada queda gerou exatamente 2 e-mails (um crítico e um de recuperação), sem repetição. Os outros serviços ficaram verdes durante os testes. No celular (375 px de largura) a página não tem rolagem horizontal; as tabelas largas rolam dentro do próprio quadro.

Screenshots em `docs/img/`: `desktop-visao-geral.png`, `desktop-web.png`, `desktop-banco.png`, `desktop-alertas.png`, `mobile-visao-geral.png`, `mobile-web.png`, `mobile-alertas.png`. Os de celular foram gerados com 500 px de largura (mínimo do Chrome sem interface); a verificação a 375 px foi feita no navegador do app.

### 8. Perguntas que a professora pode fazer

- **Por que o alerta não dispara na primeira leitura ruim?** Para filtrar ruído. Exigimos N ciclos seguidos (histerese) para só alertar problemas que se mantêm.
- **O que acontece se a métrica oscila em volta do limiar?** A contagem zera a cada volta ao nível anterior, então nada dispara e não há spam.
- **Diferença entre NXDOMAIN e SERVFAIL?** NXDOMAIN: o servidor respondeu corretamente que o nome não existe (erro do cliente). SERVFAIL: o servidor falhou ao resolver (erro do servidor). Só o segundo gera alerta.
- **Como o e-mail é enviado?** Conexão TCP na porta 1025 e os comandos EHLO, MAIL FROM, RCPT TO, DATA; a mensagem termina com um ponto sozinho numa linha.
- **Qual a diferença entre a porta 587 e a 465?** A 587 começa em texto e passa a TLS com STARTTLS. A 465 já começa com TLS.
- **Por que p95 e não a média?** A média esconde picos e o máximo é sensível a um único outlier. O p95 mostra quase o pior caso típico.
- **Como se evita e-mail duplicado se o monitor reiniciar?** Os incidentes abertos ficam no SQLite e são recarregados ao iniciar.
- **Por que o front não usa React?** Para não precisar de build nem de npm, e porque a aplicação é pequena. O FastAPI serve os arquivos estáticos.
- **Como o navegador fica atualizado?** Chama a API REST a cada 5 s (polling) e redesenha os gráficos. Alternativas: WebSocket ou Server-Sent Events.

### 9. Problemas encontrados e como foram resolvidos

1. **Conflito de nome `SMTP_HOST`.** Na Fase 1 a variável apontava para o Mailpit nas sondas. Como o envio de alertas precisa usar um SMTP real com essas mesmas variáveis, as sondas passaram a usar `MAILPIT_HOST` e ficam sempre no Mailpit.
2. **Tabela `alerts` antiga.** O esquema da Fase 1 era simples demais para incidentes com mudanças de nível. Como estava vazia, é recriada automaticamente se faltar a coluna `opened_ts`.
3. **Valores antigos com o serviço fora do ar.** Os cards mostravam o último QPS de antes da queda. Agora, se o serviço está fora, as métricas aparecem como `-`.
4. **Gráfico de conexões espremido** pela linha de `max_connections` (100). A linha foi removida; o percentual de uso está na regra de alerta.
5. **Screenshot "cortado" no celular.** O Chrome sem interface tem largura mínima de 500 px e recortava a imagem. A checagem de overflow foi feita no navegador do app a 375 px e os screenshots de celular usam 500 px.
6. **Risco de falso positivo.** Slow queries e rollbacks são raros mas aleatórios. Reduzi a frequência no loadgen e usei limiares com folga (slow queries `> 8` por minuto contra uma média de cerca de 2).


---

## Fase 3: segurança, testes e evidências

### 1. O que foi feito

- **Loadgen com 3 modos trocáveis ao vivo** (sem rebuild), por uma API interna na porta 8090 (`POST /mode/normal|pico|bruteforce`), com botões na aba Segurança e proxy em `/api/loadgen`.
  - `normal`: tráfego legítimo vindo de 12 IPs ficcionais (faixa `198.51.100.0/24`).
  - `pico`: rajada de cerca de 150 a 200 requisições por segundo, vinda de 3 IPs (`203.0.113.7`, `.8`, `.9`), por cima do tráfego normal.
  - `bruteforce`: 2 IPs (`203.0.113.50` e `.51`) tentando senhas erradas em `/admin` (cerca de 5 por segundo cada) e logins com senha errada no Postgres (usuários `admin`, `postgres`, `root` e `app`).
- **nginx com `real_ip`**: o IP real do cliente vem do header `X-Forwarded-For`, mas só quando a conexão chega da rede interna. O log JSON ganhou os campos `peer` (IP da conexão TCP) e `user` (conta usada no Basic Auth).
- **Postgres** com `%h` no `log_line_prefix`, para o log de falhas de login trazer o IP de origem.
- **Coletor de segurança** (`collectors/seguranca.py`, serviço `security`) com 4 monitoramentos:
  1. **Anomalia de tráfego (DDoS)**: z-score do RPS contra baseline móvel de 10 min e top 5 IPs do access log.
  2. **Brute force**: falhas de autenticação por IP e por conta numa janela de 60 s, de duas fontes (401 no `/admin` e "password authentication failed" no log do container do Postgres, lido pela API do Docker).
  3. **Alteração de configuração** (`config_watch.py`): SHA-256 de todos os arquivos de `/config` contra a baseline guardada no SQLite, com diff e endpoint para aceitar nova baseline.
  4. **Vulnerabilidades**: contêiner Trivy (profile `scan`) grava um JSON por serviço num volume; o monitor lê, conta por severidade e lista os principais CVEs.
- **5 regras novas** no `alerts.yaml` (todas com e-mail, e os e-mails de segurança levam os IPs, o diff ou os CVEs no corpo).
- **Aba Segurança** do dashboard, card de Segurança na Visão Geral e **menu hambúrguer** no celular.
- **Scripts de demo** em `scripts/` (PowerShell): `demo_queda.ps1`, `demo_ddos.ps1`, `demo_bruteforce.ps1`, `demo_config.ps1`, `demo_reset.ps1`.
- **Suíte E2E** com Playwright (Python) em `tests/e2e/` (16 casos), `docs/TESTES.md` e **script de figuras** `scripts/capturar_prints.py` com `docs/img/LEGENDAS.md`.

### 2. Decisões e alternativas

| Decisão | Por que | Alternativa |
|---|---|---|
| Modo do loadgen por API HTTP na porta 8090 | Troca ao vivo com um comando ou clique, sem rebuild nem editar arquivo | Arquivo de controle lido a cada ciclo (também funcionaria, mas é menos direto de demonstrar) |
| IPs de origem simulados por `X-Forwarded-For` + `real_ip` | Dentro do Docker todo tráfego sairia do mesmo IP. Com o header, o log do nginx mostra origens diferentes, como atrás de um balanceador | Vários containers atacantes (mais pesado) ou IPs reais por interface de rede (complexo) |
| Faixas `198.51.100.0/24` e `203.0.113.0/24` | São reservadas para documentação (RFC 5737): nunca existem na internet real | IPs privados (`10.x`), que poderiam ser confundidos com a rede interna |
| z-score com baseline que **não absorve** amostras anômalas | Se o ataque entrasse na média, ela subiria e o próprio ataque "viraria normal" em poucos minutos | Média e desvio simples sobre tudo (mais fácil, mas cego a ataques longos) |
| Piso de 0,5 no desvio padrão | Evita z-score gigante quando o tráfego histórico é quase constante | Sem piso (qualquer variação pequena viraria alerta) |
| Regra dupla: z-score **e** razão (10x a baseline) | O z-score depende do desvio; a razão é uma segunda opinião simples de explicar | Só z-score |
| Falhas contadas por IP **e** por conta | O IP identifica quem ataca. A conta mostra o alvo (ex.: `admin`) | Contar só o total (um ataque distribuído e pequenos erros normais ficariam misturados) |
| Log do Postgres lido pela API do Docker | O monitor já tem o `docker.sock`. Não precisa de volume extra nem de `logging_collector` | Gravar o log do Postgres num volume compartilhado |
| Hash SHA-256 e baseline no SQLite, com conteúdo guardado | Permite o diff legível. A primeira execução define o estado "confiável" | Só guardar o hash (detecta, mas não mostra o que mudou) |
| Diretório `/config` montado, não arquivos soltos | Um editor que troca o arquivo (novo inode) quebra o mount de arquivo único, mas o diretório sempre reflete a mudança | Montar cada arquivo |
| Trivy em contêiner com `profile: scan` | Não roda no `up` normal (o scan é pesado) e não exige instalar nada no Windows | Instalar o Trivy no host, ou usar a API do OSV (plano B, não foi necessário) |
| Alerta de CVE CRITICAL em **amarelo** (vermelho acima de 10 CRITICAL) | Vulnerabilidade conhecida em imagem pública é risco, não incidente em andamento. Vermelho permanente tornaria o painel inútil na apresentação | Vermelho sempre que houver CRITICAL |
| Menu hambúrguer abaixo de 600 px | Com 7 itens, a barra horizontal rolável escondia opções no celular | Manter a barra rolável |

### 3. Conceitos de redes e segurança envolvidos

**DDoS (Distributed Denial of Service).** Ataque de negação de serviço distribuído: muitas origens enviam tráfego em volume tão alto que o servidor não consegue atender os usuários legítimos. "Distribuído" porque vem de muitos IPs (uma botnet). Atinge a camada de aplicação (muitas requisições HTTP, o caso simulado aqui), de transporte (inundação de SYN) ou de rede (saturação de banda). Aqui simulamos o primeiro tipo, com poucas origens para facilitar a leitura.

**Por que o z-score detecta o pico.** O z-score diz **quantos desvios padrão** um valor está acima da média do passado:

```
z = (x - média) / desvio padrão
```

Exemplo numérico (valores reais do experimento): a baseline dos últimos 10 min tinha média **4,7 req/s** e desvio padrão **1,47**. Durante o pico o RPS foi **224 req/s**:

```
z = (224 - 4,7) / 1,47 = 149    (o sistema mediu 147,7 com os valores exatos)
razão = 224 / 4,7 = 47,4x
```

Com o tráfego normal, a regra "z > 3" cai em cerca de 10 req/s (4,7 + 3 x 1,47 = 9,1). Se o tráfego oscila entre 3 e 7, o z-score fica entre -1 e 2 e nada dispara. Se uma campanha de vendas dobra o tráfego aos poucos, o desvio acompanha. Um valor 3 desvios acima é raro por acaso (cerca de 0,1% das amostras numa distribuição normal), e 6 desvios é praticamente impossível por acaso, por isso o vermelho. A vantagem sobre um limite fixo (por exemplo "mais de 100 req/s") é que o limite **se adapta** ao que é normal para cada sistema.

**Cabeçalho `X-Forwarded-For` e `real_ip`.** Quando um balanceador ou CDN fica na frente do servidor, o IP que o nginx vê na conexão TCP é o do balanceador. O balanceador passa o IP do cliente no header `X-Forwarded-For`. O módulo `real_ip` do nginx troca `$remote_addr` por esse valor, **só se a conexão vier de um endereço confiável** (`set_real_ip_from`). Isto é crucial: se confiasse em qualquer origem, um atacante poderia escrever `X-Forwarded-For: 1.2.3.4` e se passar por outro IP (para fugir do bloqueio ou incriminar um inocente). Aqui só a rede `172.28.77.0/24` do Docker é confiável. **Limitação honesta**: o gateway do host também está nessa faixa, então quem acessa `localhost:8081` pelo próprio computador chegaria como confiável. Em produção, confie só no IP exato do balanceador (por exemplo `set_real_ip_from 172.28.77.21;`).

**Brute force e por que contar falhas por IP.** Brute force é adivinhar credenciais testando muitas tentativas. Uma falha de login isolada é normal (alguém errou a senha). O sinal é a **repetição vinda da mesma origem em pouco tempo**. Contar por IP isola o atacante (e permitiria bloquear só ele); contar só o total misturaria erros legítimos de muitos usuários. Contar por conta mostra o alvo (o ataque aqui concentra em `admin`) e revela *password spraying* (uma senha testada em muitas contas) quando várias contas têm poucas falhas cada. As duas fontes: **HTTP 401** é "não autenticado" no Basic Auth do `/admin`; no Postgres, o log registra `FATAL: password authentication failed for user "x"` com o IP de origem (`%h`).

**Hash criptográfico e SHA-256.** Uma função hash transforma qualquer conteúdo em um resumo de tamanho fixo (SHA-256: 256 bits, escritos como 64 caracteres hexadecimais). Propriedades que importam: (1) o mesmo arquivo sempre dá o mesmo hash; (2) mudar **um único caractere** muda o hash completamente (efeito avalanche); (3) é inviável construir outro arquivo com o mesmo hash. Por isso comparar o hash atual com o hash guardado detecta qualquer alteração, mesmo de um comentário. Exemplo do experimento: `nginx.conf` original `34f18a37...` virou `bd1ad5bd...` depois de acrescentar uma linha de comentário. Detectar alteração de configuração importa porque invasores e erros humanos costumam mexer em arquivos de configuração (abrir uma porta, desligar autenticação), e é um requisito comum de conformidade (integridade de arquivos).

**CVE e CVSS.** **CVE** (*Common Vulnerabilities and Exposures*) é o identificador público de uma vulnerabilidade conhecida, por exemplo `CVE-2024-12797`, mantido pela MITRE e usado por NVD, distribuições Linux e fornecedores. **CVSS** (*Common Vulnerability Scoring System*) dá uma nota de 0 a 10 de gravidade: 0,1 a 3,9 baixa (LOW), 4,0 a 6,9 média (MEDIUM), 7,0 a 8,9 alta (HIGH) e 9,0 a 10 crítica (CRITICAL). A nota considera como a falha é explorada (rede ou local, precisa de senha ou não) e o impacto em confidencialidade, integridade e disponibilidade.

**Como o Trivy funciona.** (1) Lê as **camadas** da imagem de container e identifica o sistema operacional (Alpine, Debian...); (2) lista os **pacotes instalados** (`apk`, `dpkg`) e as dependências de binários Go (CoreDNS e Mailpit são binários Go); (3) compara cada pacote e versão com um **banco de vulnerabilidades** (compilado de NVD, avisos das distribuições e outras fontes) que ele baixa e guarda em cache; (4) gera o relatório com ID do CVE, severidade, versão instalada e versão corrigida, quando existe. O Trivy não executa a imagem, só a analisa. O resultado depende da qualidade e atualização do banco: um achado de "0 vulnerabilidades" pode significar banco vazio (ver problemas).

**Fluxo do SMTP dos alertas de segurança.** Igual ao da Fase 2 (TCP 1025, `EHLO`, `MAIL FROM`, `RCPT TO`, `DATA`), agora com um bloco extra no corpo (IPs, hashes, diff ou CVEs).

### 4. Fluxo do dado: do serviço até o gráfico

```
 loadgen (modo)     nginx (log JSON: IP real, status, user)        monitor
 -----------        -------------------------------------          --------------------------------------------
 pico / brute  --->  access.log (volume) ------------------------> seguranca.py: RPS, z-score, top IPs, 401 por IP/conta
               --->  postgres (stderr) --> API do Docker --------> seguranca.py: "password authentication failed"
 ./services (ro) ---------------------------------------------------> config_watch.py: SHA-256 vs baseline (SQLite)
 trivy (profile scan) --> volume trivy-results (JSON) -------------> seguranca.py: contagem por severidade e CVEs
                                                                      |
                                       SQLite (metrics, config_baseline) --> motor de alertas --> e-mail (Mailpit)
                                                                      |
                                           /api/security, /api/metrics --> aba Segurança (Chart.js, tabelas)
```

1. O loadgen gera o tráfego; o nginx escreve no log o IP real, o status e a conta usada.
2. A cada 5 s o coletor lê só as linhas novas do log, soma as falhas e as requisições por IP numa janela deslizante e calcula RPS e z-score.
3. O coletor grava as métricas (`rps`, `rps_zscore`, `max_auth_failures_per_ip`, `config_changed_files`, `vulns_critical_total`...) no SQLite com `service = security`.
4. O motor de alertas avalia as 5 regras novas como as das fases anteriores, abre o incidente e envia o e-mail (com os detalhes do coletor).
5. A aba Segurança lê `/api/security` (tabelas) e `/api/metrics` (gráficos) a cada 5 s.

### 5. Comandos para rodar e verificar

```powershell
docker compose up -d --build
docker compose --profile scan run --rm trivy        # scan de vulnerabilidades (1a vez baixa ~140 MB)

# Demos (cada uma imprime o que faz e quanto tempo levou)
.\scripts\demo_queda.ps1 postgres
.\scripts\demo_ddos.ps1
.\scripts\demo_bruteforce.ps1
.\scripts\demo_config.ps1
.\scripts\demo_reset.ps1

# Trocar o modo ao vivo
Invoke-RestMethod -Method Post http://localhost:8090/mode/pico

# Testes e figuras
python -m pytest tests/e2e
python scripts/capturar_prints.py
```

**Resultados medidos das demos (execução real):**

| Demo | Ação | Tempo até o alerta | Recuperação |
|---|---|---|---|
| `demo_queda.ps1 postgres` | `docker compose stop postgres` | card vermelho e e-mail `[CRÍTICO]` em **9,7 s** | volta ao verde em **13,4 s** depois do `start` |
| `demo_ddos.ps1` | modo `pico` (RPS 224, z-score 147,7, razão 47x) | alerta em **10,3 s** | resolvido **20,4 s** depois de voltar ao normal |
| `demo_bruteforce.ps1` | modo `bruteforce` (2 IPs no `/admin` e logins no Postgres) | alerta em **14,6 s** | resolvido **72,9 s** depois (a janela de falhas é de 60 s) |
| `demo_config.ps1` | comentário acrescentado ao `nginx.conf` | alerta em **5,1 s** | resolvido **8,1 s** depois de restaurar o arquivo |

Resultado do scan (Trivy, banco de vulnerabilidades do espelho da AWS ECR):

| Serviço | Imagem | CRITICAL | HIGH | MEDIUM | LOW |
|---|---|---|---|---|---|
| web | nginx:1.27-alpine | 3 | 67 | 103 | 46 |
| db | postgres:16 | 2 | 154 | 210 | 172 |
| dns | coredns/coredns:1.11.3 | 2 | 55 | 67 | 5 |
| smtp | axllent/mailpit:v1.21 | 3 | 79 | 118 | 41 |

São imagens públicas antigas; os CVEs são reais. Isso mantém o card de Segurança em amarelo (10 CRITICAL somados), o que é um achado legítimo e não um defeito. A correção recomendada é atualizar as imagens para versões mais novas.

### 6. Perguntas que a professora pode fazer

- **O que é um DDoS e como vocês simulam?** Negação de serviço distribuída: muitas origens inundam o servidor. Simulamos com uma rajada de 150 a 200 requisições por segundo vinda de 3 IPs ficcionais, usando o header `X-Forwarded-For`.
- **Por que z-score e não um limite fixo?** O z-score mede o desvio em relação ao normal **daquele sistema** e se adapta. Um limite fixo precisa ser ajustado à mão e falha quando o tráfego legítimo cresce.
- **O que acontece se o ataque durar muito?** A baseline não absorve amostras anômalas, então o alerta se mantém. Se a "anomalia" persistir por 5 minutos, ela vira o novo normal (trade-off para não ficar em alerta para sempre).
- **Por que contar falhas por IP?** Para isolar o atacante e não confundir com erros legítimos de muitos usuários. Também conta por conta para ver o alvo.
- **O nginx confia em qualquer `X-Forwarded-For`?** Não. Só em conexões vindas da rede interna do Docker. Se confiasse em qualquer origem, o atacante poderia falsificar o IP.
- **O que é um hash e por que SHA-256 detecta alteração?** Um resumo de 256 bits do conteúdo. Mudar um caractere muda o hash inteiro, e não dá para fabricar outro arquivo com o mesmo hash.
- **E se a alteração for legítima?** O botão "Aceitar nova baseline" grava o estado atual como o novo normal e o alerta é resolvido.
- **O que é CVE e CVSS?** CVE é o identificador de uma vulnerabilidade pública. CVSS é a nota de 0 a 10 da gravidade (9,0 ou mais é crítica).
- **Como o Trivy sabe que há vulnerabilidade?** Lê os pacotes da imagem e compara nome e versão com um banco de CVEs, informando a versão corrigida.
- **Por que o card de Segurança está amarelo mesmo com tudo calmo?** Porque as imagens públicas usadas têm CVEs CRITICAL conhecidos. Pelas regras, isso é amarelo (atenção).
- **O brute force também dispara o alerta de tráfego?** Sim, porque as tentativas aumentam o RPS (de 5 para cerca de 15 req/s, z-score acima de 6). É um efeito real do ataque, não um erro.

### 7. Problemas encontrados e como foram resolvidos

1. **Trivy sem achados (banco "vazio").** O primeiro scan terminou sem erro mas com 0 vulnerabilidades em todas as imagens. O banco baixado do `ghcr.io` tinha apenas 16 KB (um arquivo praticamente vazio). Solução: apontar `TRIVY_DB_REPOSITORY` para o espelho `public.ecr.aws/aquasecurity/trivy-db:2` (banco real de 1,8 GB descompactado). O plano B (API do OSV) respondeu normalmente nos testes, mas não precisou ser usado.
2. **Mudanças nos arquivos de config não aplicadas.** O nginx e o Postgres montam os arquivos de configuração individualmente e só os relêem ao reiniciar. Depois de editar `nginx.conf` e `postgresql.conf` foi preciso `docker compose restart nginx postgres` (sem isso o log continuava mostrando o IP do loadgen e sem o campo `peer`).
3. **`0 segundos` tratado como "falso" no PowerShell.** `if ($t)` falha quando o tempo medido é 0. Trocado por `$null -ne $t` em todos os scripts.
4. **Acentos quebrados no PowerShell 5.1.** O PowerShell 5.1 lê JSON sem `charset` como Latin-1, e os scripts sem BOM são lidos como ANSI. Solução: scripts salvos em UTF-8 com BOM e funções que decodificam a resposta como UTF-8.
5. **Processo em segundo plano morrendo.** Um `comando &` dentro de uma sessão encerra junto com ela. Os scans e testes longos passaram a rodar como a própria tarefa em segundo plano.
6. **Brute force disparando também o alerta de tráfego** e **latência de DNS subindo depois dos ataques**. Ambos são efeitos reais (mais requisições e CPU disputada no Docker Desktop). Foram mantidos e documentados, pois reforçam a explicação de que ataques têm efeitos colaterais visíveis.
7. **Testes sensíveis ao tempo.** Na primeira execução da suíte, 3 dos 16 testes falharam por tempo: duas esperas de alteração de config e um print de celular. O Docker Desktop pode demorar a propagar para o container uma alteração de arquivo feita no Windows (vimos até cerca de 80 s numa rodada com carga, contra 5 a 8 s nas demos). Os tempos limite foram ampliados. Na rodada seguinte, o teste do z-score falhou por ler o valor cedo demais (4,7 em vez de passar de 6, porque o pico ainda estava "enchendo" a janela); passou a esperar o z-score cruzar o limiar. A execução final teve **16 de 16 aprovados**. Detalhes em `docs/TESTES.md`.
7b. **Teste que sujou o `nginx.conf`.** Os testes de configuração acrescentam linhas ao `nginx.conf` e o restauram no final. Uma falha no meio deixou as linhas de teste no arquivo, e as figuras seguintes saíram com a baseline errada (o diff mostrava "mudança autorizada" nos dois lados). Correções: a suíte agora limpa essas linhas antes e depois de rodar, e o teste de "aceitar baseline" só aceita depois que o monitor enxerga o arquivo restaurado.
7c. **Figuras com defeito visual.** O cabeçalho fixo (`position: sticky`) aparecia no meio dos prints de trecho de página, e a tabela de IPs suspeitos ficava cortada na grade de 3 colunas. O script desativa o cabeçalho fixo durante a captura e a tabela passou a ocupar a largura inteira.
8. **Janela de log do Docker.** A API de logs só aceita `since` em segundos inteiros e repete linhas; o coletor guarda o último timestamp visto e descarta as já contadas, para não contar a mesma falha de login duas vezes.
