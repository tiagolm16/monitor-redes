# Plataforma de Monitoramento para DevOps

Trabalho final de Redes de Computadores (IDP). Monitora Web Server (nginx), Banco de Dados (PostgreSQL), DNS (CoreDNS) e SMTP (Mailpit), com API REST, dashboards, alertas e monitoramentos de segurança.

Regras do projeto: [CLAUDE.md](CLAUDE.md). Explicação de cada fase: [docs/RELATORIO_PROCESSO.md](docs/RELATORIO_PROCESSO.md).

## Como rodar

Requisitos: Windows 11 com Docker Desktop (WSL2).

```powershell
docker compose up -d --build
```

| O que | Endereço |
|---|---|
| Monitor (API e front) | http://localhost:8000 |
| Swagger da API | http://localhost:8000/docs |
| Site nginx | http://localhost:8081 (`/admin` usa `admin` / `admin123`) |
| Mailpit (e-mails) | http://localhost:8025 |
| Métricas do CoreDNS | http://localhost:9153/metrics |
| DNS (UDP/TCP) | `localhost:1053` |
| PostgreSQL | `localhost:5433` (usuário `app`, senha `app123`) |

Parar tudo: `docker compose down` (use `-v` para apagar também os dados).

## Alertas

As regras ficam em [monitor/alerts.yaml](monitor/alerts.yaml) (serviço, métrica, operador, limiar amarelo e vermelho, ciclos). Depois de editar, rode `docker compose up -d --build monitor`. Níveis: Verde (ok), Amarelo (atenção), Vermelho (crítico). Cada mudança de nível gera um e-mail (`[ATENÇÃO]`, `[CRÍTICO]` ou `[RECUPERADO]`), por padrão no Mailpit (http://localhost:8025).

### Enviar alertas por um SMTP real (opcional)

Crie um arquivo `.env` na raiz (está no `.gitignore`, nunca vai para o repositório). Use [.env.example](.env.example) como modelo:

| Variável | Significado | Padrão |
|---|---|---|
| `SMTP_HOST` | servidor SMTP | `mailpit` |
| `SMTP_PORT` | porta | `1025` |
| `SMTP_USER` / `SMTP_PASS` | credenciais (vazias = sem autenticação) | vazio |
| `SMTP_TLS` | `none`, `starttls` (porta 587) ou `ssl` (porta 465) | `none` |
| `ALERT_TO` | destinatário | `ops@lab.local` |
| `ALERT_FROM` | remetente | `alertas@lab.local` |
| `DASHBOARD_URL` | link usado no corpo do e-mail | `http://localhost:8000` |

As sondas de monitoramento do SMTP continuam sempre no Mailpit, independente dessas variáveis.

## Status

- [x] Fase 1: infraestrutura, coletores, SQLite, API REST, loadgen modo normal
- [x] Fase 2: dashboard (Visão Geral, Web, Banco, DNS, SMTP, Alertas) e motor de alertas com e-mail
- [ ] Fase 3: segurança (brute force, pico/DDoS, alteração de config) e modos pico e bruteforce do loadgen
