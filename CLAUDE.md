# CLAUDE.md: Plataforma de Monitoramento para DevOps (Redes de Computadores, IDP)

Trabalho final de Redes de Computadores. Apresentação em **27/11**. O dono do projeto vai apresentar, então tudo o que for feito precisa ser **simples e explicável**.

## Objetivo
Front-end/website que monitora serviços de rede (Web Server, Banco de Dados, DNS, SMTP), com dashboards de métricas por serviço e visão consolidada, alertas em 3 níveis com e-mail, e monitoramentos de segurança.

## Ambiente
Windows 11 + Docker Desktop (WSL2). Shell principal: PowerShell. Cuidado com fim de linha (LF), caminhos e portas já ocupadas (porta 53 do host NÃO é usada, o CoreDNS publica em 1053).

## Stack (não mudar sem perguntar ao dono)
- `docker-compose.yml` sobe tudo com um único `docker compose up -d --build`
- Serviços monitorados:
  - **nginx**: site simples + `stub_status` + access log em JSON num volume compartilhado + rota `/admin` com `auth_basic` (gera 401 para detecção de brute force)
  - **postgres** (17-alpine desde a Fase 4; era 16): com `pg_stat_statements` e `log_min_duration_statement`
  - **coredns**: zona local `lab.local`, plugin `prometheus` (:9153) e `log`
  - **mailpit**: SMTP 1025, UI web 8025 (recebe os e-mails de alerta)
- **monitor**: Python 3.12 + FastAPI
  - coletores assíncronos a cada 5 s, um módulo por serviço
  - SQLite num volume (tabela série temporal: `ts, service, metric, value, labels`)
  - API REST: `/api/services`, `/api/metrics?service=&metric=&since=`, `/api/alerts`, `/api/health`
  - front-end estático servido pelo próprio FastAPI (HTML + CSS + JS puro + Chart.js via CDN, sem build, responsivo)
- **loadgen**: container Python que gera tráfego realista (HTTP 200/404/500, queries no Postgres incluindo lentas, DNS válido e inválido, e-mails). Modos por variável de ambiente `LOAD_MODE`: `normal`, `pico` (simula DDoS), `bruteforce`
- Configs dos serviços em `./services/<nome>/`, também montadas em modo leitura no monitor (detecção de alteração de config)

## Métricas obrigatórias
- **Web**: disponibilidade (HTTP check), RPS, latência ms, taxa de erro 4xx/5xx com contagem por código, conexões ativas
- **DB**: disponibilidade, QPS, erros/rollbacks, conexões abertas, CPU/memória/IO do container quando possível, tamanho do banco e crescimento, nº de slow queries
- **DNS**: tempo de resolução ms, taxa de falha, QPS, disponibilidade
- **SMTP**: taxa de entrega, tamanho da fila de envio (fila interna do monitor), latência de envio, taxa de erro, volume por minuto (envios sintéticos do monitor + API do Mailpit para confirmar entrega)

## Regras de trabalho
- Trabalhar em **fases**. Ao terminar cada fase: parar, mostrar resumo e esperar o dono mandar a próxima.
- Código simples e legível, comentado em **pt-BR** onde houver conceito de redes. Nada de abstração desnecessária.
- Tudo funciona no Windows com Docker Desktop. `.gitattributes` força LF em `.sh`, `.conf`, `Corefile`, `Dockerfile`.
- **Verificar de verdade**: subir containers, chamar endpoints, conferir métricas no SQLite. Não declarar pronto sem testar.
- Commits pequenos e descritivos ao fim de cada etapa.

## Relatório de processo (OBRIGATÓRIO)
Manter `docs/RELATORIO_PROCESSO.md` atualizado ao fim de cada fase, escrito para um estudante de Engenharia de Software que vai apresentar o projeto. **Sem travessão (—) no texto.** Para cada fase:
1. O que foi feito (lista objetiva)
2. Por que cada decisão foi tomada e qual seria a alternativa
3. Conceitos de redes envolvidos, explicados do zero (protocolo, camada OSI/TCP-IP, porta, TCP ou UDP, como a métrica é obtida na prática)
4. Fluxo do dado: do serviço até o gráfico na tela
5. Comandos para rodar e verificar
6. Perguntas que a professora pode fazer, com resposta curta
7. Problemas encontrados e como foram resolvidos
