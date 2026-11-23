# Testes de navegação e uso

Suíte automatizada com **Playwright (Python) + pytest**, em `tests/e2e/`. Usa o Google Chrome instalado (sem baixar outro navegador), com viewport desktop 1440x900 e emulação de celular 375x812 (escala 2x, toque e user agent mobile).

```powershell
docker compose up -d --build
docker compose --profile scan run --rm trivy      # necessário para T06 e T17
pip install playwright pytest
python -m pytest tests/e2e -rA --durations=0
```

Os testes T10 a T17 **derrubam serviços, trocam o modo do gerador de tráfego e alteram o `nginx.conf` de propósito**, e restauram tudo ao final. Duração total: cerca de 4 minutos. As evidências são salvas em `docs/img/testes/`.

## Resultado da execução final

**16 casos executados, 16 aprovados, 0 falhas** (263,5 s, 23/11/2026, execução final da Fase 4, com as imagens atualizadas, o fuso `America/Sao_Paulo` e os textos acentuados). Os tempos por caso na tabela abaixo são os da última rodada da Fase 3, e variam alguns segundos de uma execução para outra.

### Rodadas da Fase 4

| Rodada | Resultado | O que aconteceu |
|---|---|---|
| Branch `imagens-atualizadas` (1) | 13 aprovados, 3 falhas | T13 e T15 procuravam o assunto do e-mail sem acento (`trafego`, `configuracao`), que passou a ter acento (`tráfego`, `configuração`); T16 falhou em seguida. Os testes foram atualizados |
| Branch `imagens-atualizadas` (2) | 3 de 3 reexecutados aprovados | T13, T15 e T16 com os assuntos corretos. Os outros 13 já tinham passado. Branch mesclada no `main` |
| `main` após o merge (1) | 14 aprovados, 2 falhas, 8 erros no encerramento | O container do `loadgen` **morreu** durante o T10 (queda do Postgres) por uma exceção do `asyncpg` (`InternalClientError`) que o código não tratava; T13 e T14 não conseguiram trocar o modo (porta 8090 recusada) |
| `main` após a correção (2, **final**) | **16 aprovados** | `loadgen` agora trata qualquer exceção nos laços do Postgres e tem `restart: unless-stopped`, voltando sozinho se cair |

A suíte pegou um defeito real: um gerador de tráfego que cai quando o banco reinicia. Nas rodadas da Fase 3 isso não tinha aparecido por sorte de temporização.

### Rodadas da Fase 3 (histórico)

| Rodada | Resultado | O que aconteceu |
|---|---|---|
| 1 | 13 aprovados, 3 falhas | T07 (print do celular estourou 30 s), T15 e T16 (alteração de arquivo no Windows demorou a aparecer dentro do container, mais do que o tempo limite de 30 a 40 s) |
| 2 | 3 de 3 reexecutados aprovados | Tempos limite ampliados (90 a 120 s) e tempo do print aumentado para 90 s |
| 3 | 15 aprovados, 1 falha | T13 lia o z-score cedo demais (obteve 4,7 e esperava mais de 6, o pico ainda estava enchendo a janela). O teste passou a esperar o z-score cruzar 6 |
| 4 (final) | **16 aprovados** | Suíte completa, sem alterações adicionais |

Também corrigimos um defeito **do próprio teste**: uma falha no meio de T15/T16 deixou linhas de teste no `nginx.conf`. A suíte agora limpa essas linhas antes e depois de rodar.

## Casos de teste

| ID | Objetivo | Passos | Resultado esperado | Resultado obtido | Evidência |
|---|---|---|---|---|---|
| T01 | O menu navega por todas as páginas (desktop) | Abrir o dashboard e clicar em cada item do menu (Visão Geral, Web, Banco, DNS, SMTP, Alertas, Segurança) | Cada clique mostra o título da página e marca o item como ativo | **Passou** (0,8 s) | `testes/T01_menu_desktop.png` |
| T02 | A Visão Geral mostra os 5 cards com gráficos com dados | Abrir `#/` e esperar os gráficos | 5 cards e 5 mini gráficos com pelo menos 3 pontos; texto "Última atualização" | **Passou** (0,5 s) | `testes/T02_visao_geral.png` |
| T03 | Cada página de serviço renderiza todos os gráficos obrigatórios | Abrir Web, Banco, DNS e SMTP | 6, 10, 4 e 6 gráficos, todos com dados; tiles de valor atual visíveis | **Passou** (1,2 s) | `testes/T03_web.png`, `T03_db.png`, `T03_dns.png`, `T03_smtp.png` |
| T04 | O seletor de período funciona | Em Web, clicar em 5 min e depois em 15 min | Com 5 min o gráfico tem no máximo 70 pontos; com 15 min, mais de 70; botão ativo marcado | **Passou** (0,5 s) | sem print |
| T05 | A tela se atualiza sozinha | Abrir a página e esperar até 12 s | O texto "Última atualização" muda sem recarregar | **Passou** (5,1 s) | sem print |
| T06 | A aba Segurança mostra todos os blocos | Abrir `#/seguranca` | 3 gráficos, 6 tiles de DDoS, tabela de top IPs, tabela de arquivos com `nginx/nginx.conf`, 4 cards de vulnerabilidades com lista de CVEs ao expandir | **Passou** (0,6 s) | `testes/T06_seguranca.png` |
| T07 | O dashboard funciona no celular (375 px) | Emular celular, abrir cada página e medir `scrollWidth`; abrir o menu hambúrguer e escolher Alertas | Sem rolagem horizontal em nenhuma página; menu fechado no início, abre ao tocar, navega e fecha ao escolher | **Passou** (4,8 s) | `testes/T07_celular_menu_aberto.png` |
| T08 | Aviso visual quando a API para | Bloquear as chamadas `/api/*` pelo navegador | Faixa vermelha "não está respondendo" e ponto de status vermelho | **Passou** (5,2 s) | `testes/T08_aviso_api_fora.png` |
| T10 | Queda do PostgreSQL: card vermelho, alerta e e-mails | `docker compose stop postgres`; depois `start` | Card do banco com nível 3, incidente ativo na página Alertas, e-mail `[CRÍTICO] db` no Mailpit; ao religar, card verde e e-mail `[RECUPERADO] db` | **Passou** (26,9 s) | `testes/T10_queda_postgres_vermelho.png`, `T10_queda_postgres_recuperado.png` |
| T11 | Queda do nginx (mesmo cenário) | `docker compose stop nginx`; depois `start` | Card web vermelho, alerta ativo, `[CRÍTICO] web` e depois `[RECUPERADO] web` no Mailpit | **Passou** (30,2 s) | `testes/T11_queda_nginx_vermelho.png`, `T11_queda_nginx_recuperado.png` |
| T12 | Os filtros da página Alertas funcionam | Filtrar por serviço `db` e depois por nível Vermelho | Só linhas do serviço `db`; só linhas com pior nível Vermelho | **Passou** (0,5 s) | `testes/T12_filtros_alertas.png` |
| T13 | Detecção de DDoS por z-score | `POST /mode/pico` e esperar | Alerta `sec_ddos*` ativo; top IPs com `203.0.113.x`; z-score maior que 6; e-mail `[CRÍTICO] security: Anomalia de trafego`; resolve ao voltar ao normal | **Passou** (32,9 s) | `testes/T13_ddos.png` |
| T14 | Detecção de brute force | `POST /mode/bruteforce` e esperar | Alerta `sec_bruteforce*`; IP `203.0.113.50` e fonte `postgres` na tabela de suspeitos; conta `admin` entre as atacadas; e-mail de brute force; resolve depois da janela de 60 s | **Passou** (89,8 s) | `testes/T14_bruteforce.png` |
| T15 | Detecção de alteração de configuração | Acrescentar uma linha ao `nginx.conf` e depois restaurar | Alerta `sec_config`; arquivo `ALTERADO` com diff e dois hashes de 64 caracteres diferentes; e-mail com o arquivo; alerta resolve ao restaurar | **Passou** (19,2 s) | `testes/T15_config_alterada.png` |
| T16 | "Aceitar nova baseline" | Alterar o arquivo, clicar no botão e confirmar o diálogo | O alerta resolve e nenhum arquivo fica diferente; no final a baseline volta ao arquivo original | **Passou** (30,6 s) | sem print |
| T17 | Vulnerabilidades por serviço | Ler `/api/security` e abrir a aba | Os 4 serviços com contagem das 4 severidades e CVEs com ID, pacote e versão; alerta `sec_vuln_critical` ativo (há CRITICAL) | **Passou** (1,0 s) | `testes/T17_vulnerabilidades.png` |

## Tempos medidos nos cenários

Medidos pelas demos (`scripts/demo_*.ps1`) e confirmados pela suíte:

| Cenário | Tempo até o alerta | Recuperação |
|---|---|---|
| Queda do PostgreSQL | 9,7 s | 13,4 s depois de religar |
| DDoS (modo pico) | 10,3 s | 20,4 s depois de voltar ao normal |
| Brute force | 14,6 s | 72,9 s (a janela de falhas tem 60 s) |
| Alteração de configuração | 5,1 s | 8,1 s depois de restaurar |

## Limitações dos testes

- Os testes de cenário dependem do tempo e do estado do ambiente (Docker Desktop, carga da máquina). Foram escritos com esperas por condição (não com pausas fixas), mas uma máquina muito carregada pode exigir ampliar os tempos limite.
- O teste de queda do Mailpit não existe: com o Mailpit parado não há onde receber o e-mail de alerta.
- Não há teste de envio por SMTP real (a configuração está documentada no README, mas só o caminho do Mailpit foi exercitado).
