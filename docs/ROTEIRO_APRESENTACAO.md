# Roteiro da apresentação (10 a 12 minutos)

Total previsto: **11 minutos e 30 segundos**, em 6 blocos. Fale pausadamente: o tempo abaixo já inclui as pausas das demos.

| Bloco | Conteúdo | Tempo | Acumulado |
|---|---|---|---|
| 1 | Introdução | 1:30 | 1:30 |
| 2 | Arquitetura | 2:00 | 3:30 |
| 3 | Demo ao vivo (monitoramento e alertas) | 3:00 | 6:30 |
| 4 | Segurança | 3:00 | 9:30 |
| 5 | Testes | 1:00 | 10:30 |
| 6 | Conclusão | 1:00 | 11:30 |

## Antes de começar (15 minutos antes)

1. Conecte o notebook na tomada e feche programas pesados (a demo gera carga).
2. Abra o Docker Desktop e espere ficar estável.
3. Na pasta do projeto, rode o script que prepara tudo (sobe os containers, espera ficar verde, limpa o histórico de alertas e abre o painel e o Mailpit):

```powershell
.\scripts\preparar_apresentacao.ps1
```

4. Organize as abas do navegador, nesta ordem:
   - **Aba 1:** painel, Visão Geral (`http://localhost:8000/#/`)
   - **Aba 2:** Mailpit (`http://localhost:8025`)
   - **Aba 3:** painel, aba Segurança (`http://localhost:8000/#/seguranca`)
   - **Aba 4:** `docs/img/fig00_arquitetura.png` (para o bloco 2)
5. Deixe um PowerShell aberto na pasta do projeto, com fonte grande (Ctrl + roda do mouse) e ao lado do navegador.
6. Confira: todos os cards verdes (o card de Segurança fica **amarelo** porque as imagens têm CVEs CRITICAL, e isso é esperado; você vai explicar).
7. Tenha o `docs/img/` aberto no Explorador, caso precise do plano B.

## Bloco 1: Introdução (1:30)

**Mostrar:** a aba 1 (Visão Geral), ainda sem mexer em nada.

**Falar:**
- "Em um ambiente de DevOps, os serviços de rede precisam ser observados o tempo todo. Se o banco cai ou alguém ataca o servidor web, a equipe precisa saber em segundos."
- "Construímos uma plataforma que monitora quatro serviços: **Web** (nginx), **Banco de Dados** (PostgreSQL), **DNS** (CoreDNS) e **SMTP** (Mailpit)."
- "Ela coleta métricas a cada 5 segundos, mostra dashboards por serviço e uma visão consolidada, dispara alertas em **três níveis** (verde, amarelo e vermelho) com **e-mail**, e tem uma área de **segurança**: tráfego anormal, brute force, alteração de configuração e vulnerabilidades."
- "Tudo sobe com **um único comando**: `docker compose up -d --build`."

## Bloco 2: Arquitetura (2:00)

**Mostrar:** aba 4 com a figura `fig00_arquitetura.png`.

**Falar (nessa ordem, apontando na figura):**
1. "Seis containers numa rede Docker com IPs fixos: nginx, postgres, coredns, mailpit, o **monitor** e o **loadgen**, que gera tráfego realista."
2. Protocolos (conceitos de redes que a professora vai querer ouvir):
   - "O Web é medido por **HTTP sobre TCP, porta 80**: um GET e o tempo da resposta. Contamos requisições pelo `stub_status` e códigos 200, 404 e 500 pelo log em JSON."
   - "O Banco usa o protocolo do PostgreSQL, **TCP 5432**. Lemos as views `pg_stat_*`."
   - "O DNS usa **UDP porta 53**, porque a consulta e a resposta cabem em um pacote cada. Medimos o tempo de resolução com uma consulta real."
   - "O SMTP usa **TCP porta 1025**: o monitor envia e-mails de teste e confirma a entrega pela API do Mailpit."
3. "A cada 5 segundos o monitor coleta, grava em **SQLite** (série temporal) e a **API REST** alimenta o painel, que é HTML, CSS e JavaScript puros com Chart.js."
4. "O **motor de alertas** lê regras de um arquivo YAML. Para não dar falso alarme, exige que a condição se mantenha por alguns ciclos seguidos (histerese). Quando o estado muda, envia e-mail."

## Bloco 3: Demo ao vivo, monitoramento e alertas (3:00)

**Mostrar:** aba 1, depois terminal e Mailpit.

**Passo a passo exato:**

1. (0:30) Na Visão Geral, aponte os cards: "Cada card tem a cor do estado, as métricas principais e um mini gráfico." Clique em **Banco** e mostre 2 ou 3 gráficos (QPS, conexões, tamanho do banco) e o seletor de 5 min, 15 min e 1 hora.
2. (0:10) Volte à Visão Geral.
3. (1:30) No terminal, rode:

```powershell
.\scripts\demo_queda.ps1 postgres
```

   Narre o que o script imprime:
   - "O script para o container do Postgres." (cerca de 10 s depois) "O card do banco ficou **vermelho**, e o script mostra o tempo até o alerta."
   - Vá ao **Mailpit (aba 2)**: abra o e-mail **[CRÍTICO] db: PostgreSQL fora do ar**. "Serviço, métrica, valor, limiar, **horário de Brasília** e link para o painel."
   - Volte ao terminal: o script religa o container. "Em cerca de 15 segundos o card volta ao verde e chega o e-mail **[RECUPERADO]** com a duração do incidente."
4. (0:50) No painel, abra a aba **Alertas**: "Aqui o histórico do incidente, com filtros por nível e por serviço, e as regras do `alerts.yaml`." Mostre as regras com os limiares.

**Frase de transição:** "Agora, além de falhas, a plataforma detecta ataques."

## Bloco 4: Segurança (3:00)

**Mostrar:** aba 3 (Segurança). Use os **botões do simulador** (rápidos) em vez dos scripts completos (cada script dura de 1 a 2 minutos).

1. **DDoS (0:50).** Clique em **Pico (DDoS)**. "O gerador começa a enviar mais de 150 requisições por segundo a partir de 3 IPs." Em cerca de 10 s: o alerta vermelho aparece, o z-score sobe para mais de 100, e o **top 5 de IPs** mostra as 3 origens. Explique em uma frase: "O z-score mede quantos desvios padrão o tráfego está acima da média dos últimos 10 minutos. Normal fica perto de zero; aqui passou de 100." Clique em **Normal**.
2. **Brute force (0:50).** Clique em **Brute force**. Em cerca de 15 s: o alerta e a tabela de **IPs suspeitos**, com falhas no `/admin` do nginx e logins errados no Postgres, e a conta `admin` como alvo. "Contamos falhas **por IP** numa janela de 60 segundos." Clique em **Normal**.
3. **Alteração de configuração (0:50).** No terminal:

```powershell
.\scripts\demo_config.ps1
```

   "O script acrescenta um comentário no `nginx.conf`. Em cerca de 5 s o monitor detecta que o **hash SHA-256** mudou." Mostre o diff e os dois hashes na tela (também no e-mail). Explique: "Mudar um caractere muda o hash inteiro." O script desfaz a alteração e o alerta resolve.
4. **Vulnerabilidades (0:30).** Na seção Vulnerabilidades da aba Segurança: "O Trivy escaneia as imagens e lista CVEs por severidade, com o pacote e a versão corrigida. Por isso o card de Segurança está amarelo: as imagens públicas têm CVEs CRITICAL conhecidos. A correção é atualizar as imagens."

## Bloco 5: Testes (1:00)

**Mostrar:** `docs/TESTES.md` (ou o terminal com a última saída).

**Falar:**
- "Escrevemos uma **suíte automatizada com Playwright**: 16 casos de teste que abrem cada página, conferem os gráficos, os filtros, o menu no celular e validam os cenários de falha: derrubam serviços, simulam DDoS e brute force, alteram arquivo, e conferem o e-mail pela API do Mailpit."
- "Resultado: **16 de 16 aprovados**, em cerca de 4 minutos." (Não rode ao vivo: demora.)
- Se houver tempo, mostre no celular (ou redimensione a janela): o menu hambúrguer e as páginas sem rolagem horizontal (`fig14` e `fig15`).

## Bloco 6: Conclusão (1:00)

**Falar:**
- "Entregamos monitoramento de 4 serviços, dashboards, alertas em 3 níveis com e-mail, e segurança com 4 monitoramentos, tudo reproduzível com um comando."
- Números para citar: queda detectada em cerca de **10 s**, DDoS em cerca de **10 s**, brute force em cerca de **15 s**, alteração de configuração em cerca de **5 s**.
- **Limitações** (honestidade conta ponto): SQLite e retenção de 24 h (escala de laboratório); `docker.sock` dá muito poder ao monitor; senhas de laboratório; CVEs nas imagens públicas; e-mail real documentado mas só o Mailpit foi testado.
- **Trabalhos futuros:** bloqueio automático de IPs, retenção longa com banco de séries temporais, notificação por chat, agentes com permissões mínimas.
- "Obrigado. Perguntas?"

## Plano B (se algo falhar ao vivo)

| Problema | O que fazer |
|---|---|
| Docker não sobe ou algum container cai antes da apresentação | `.\scripts\demo_reset.ps1`. Se persistir: `docker compose down` e `.\scripts\preparar_apresentacao.ps1`. Se ainda assim falhar, vá para os prints |
| Sem internet (os gráficos usam Chart.js por CDN e ficam em branco) | Apresente com os prints em `docs/img/` |
| A demo de queda travou ou demora demais | Pare com Ctrl + C, rode `.\scripts\demo_reset.ps1` e mostre `fig07`, `fig08` e `fig09` |
| O e-mail não aparece no Mailpit | Atualize a página (F5). Se não vier, mostre `fig08` e `fig09` |
| Os botões do simulador não respondem | Use `Invoke-RestMethod -Method Post http://localhost:8090/mode/pico` (e `normal` para voltar) |
| O alerta de segurança demora | Narre a teoria enquanto espera (z-score ou hash). Passando de 30 s, mostre `fig10`, `fig11` ou `fig12` |
| O painel travou | F5; se não voltar, `docker compose restart monitor` |
| Notebook sem rede ou sem energia | Use o vídeo explicativo (ver `ROTEIRO_VIDEO.md`) e os prints |

**Prints de reserva por bloco** (todos em `docs/img/`): bloco 2 `fig00_arquitetura.png`; bloco 3 `fig01_visao_geral_normal.png`, `fig02_web.png`, `fig03_banco.png`, `fig06_alertas_historico.png`, `fig07_queda_postgres_vermelho.png`, `fig08_email_critico_mailpit.png`, `fig09_email_recuperado.png`; bloco 4 `fig10_ddos_zscore.png`, `fig11_bruteforce_ips.png`, `fig12_config_alterada.png`, `fig13_vulnerabilidades.png`; bloco 5 `fig14_mobile_visao_geral.png` e `fig15_mobile_menu.png`.

## Depois da apresentação

```powershell
.\scripts\demo_reset.ps1        # volta tudo ao normal
```

## Perguntas que podem aparecer

As respostas curtas estão na seção 6 de cada fase do `docs/RELATORIO_PROCESSO.md`. As mais prováveis: por que DNS usa UDP, o que é QPS, o que é z-score, o que é hash SHA-256, o que é histerese, diferença entre NXDOMAIN e SERVFAIL, o que é CVE e CVSS, como o e-mail é enviado (EHLO, MAIL FROM, RCPT TO, DATA).
