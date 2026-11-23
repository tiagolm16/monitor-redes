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

## Status

- [x] Fase 1: infraestrutura, coletores, SQLite, API REST, loadgen modo normal
- [ ] Fase 2 em diante: dashboards, alertas, segurança, modos pico e bruteforce
