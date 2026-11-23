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
