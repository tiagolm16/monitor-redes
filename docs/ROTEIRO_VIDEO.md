# Roteiro do vídeo explicativo (5 a 8 minutos)

Objetivo: mostrar as **funcionalidades mínimas** da plataforma de monitoramento. Duração prevista: **7 minutos**.

Dicas de gravação:
- Resolução 1920x1080, navegador em tela cheia (F11), zoom de 100% a 110%, terminal com fonte grande.
- Grave a tela com a Barra de Jogos do Windows (Win + G) ou OBS Studio. Narre depois, em cima da gravação, se preferir.
- Antes de gravar, rode `.\scripts\preparar_apresentacao.ps1` (histórico de alertas limpo e tudo verde).
- Corte os tempos de espera (queda, ataques) para manter o vídeo ágil, mas mostre o tempo real que o script imprime.

| Cena | Tempo | Duração |
|---|---|---|
| 1. Abertura | 0:00 | 0:20 |
| 2. Subindo o ambiente | 0:20 | 0:40 |
| 3. Visão Geral | 1:00 | 0:50 |
| 4. Dashboards dos serviços | 1:50 | 1:10 |
| 5. Alertas: queda do banco | 3:00 | 1:15 |
| 6. Segurança: DDoS e brute force | 4:15 | 1:15 |
| 7. Segurança: configuração e vulnerabilidades | 5:30 | 0:50 |
| 8. Celular e testes | 6:20 | 0:30 |
| 9. Encerramento | 6:50 | 0:20 |

---

## Cena 1: Abertura (0:20)

**Tela:** slide ou a página inicial do repositório com o título "Plataforma de Monitoramento para DevOps".

**Narração:** "Esta é a plataforma de monitoramento para DevOps do nosso trabalho de Redes de Computadores. Ela observa um servidor web, um banco de dados, um DNS e um servidor de e-mail, mostra tudo em um painel, avisa por e-mail quando algo dá errado e vigia a segurança."

## Cena 2: Subindo o ambiente (0:40)

**Tela:** terminal na pasta do projeto.

```powershell
docker compose up -d --build
docker compose ps
```

**Narração:** "Tudo sobe com um único comando do Docker Compose. São seis containers: nginx, PostgreSQL, CoreDNS e Mailpit, que são os serviços monitorados, mais o monitor, que coleta e serve o painel, e o gerador de tráfego, que simula usuários." Mostre o `docker compose ps` com todos `Up`.

## Cena 3: Visão Geral (0:50)

**Tela:** navegador em `http://localhost:8000`, aba Visão Geral.

**Narração:** "Esta é a visão geral. Cada card é um serviço, com a cor do estado: verde está bem, amarelo pede atenção, vermelho é crítico. Vemos as principais métricas, um mini gráfico e a quantidade de alertas ativos. O card de Segurança aparece em amarelo porque as imagens públicas usadas têm vulnerabilidades críticas conhecidas. No topo, a hora da última atualização: o painel se atualiza sozinho a cada 5 segundos." Passe o mouse sobre os cards e mostre o menu.

## Cena 4: Dashboards dos serviços (1:10)

**Tela:** páginas Web, Banco, DNS e SMTP, uma de cada vez (cerca de 15 segundos cada), com o seletor de período.

**Narração por serviço:**
- **Web:** "Disponibilidade, requisições por segundo, latência, taxa de erro 4xx e 5xx, conexões ativas e o gráfico de barras com a contagem por código HTTP."
- **Banco:** "Consultas por segundo, rollbacks, conexões abertas, CPU, memória e IO do container, tamanho e crescimento do banco, e slow queries."
- **DNS:** "Tempo de resolução, consultas por segundo e a taxa de falha, separada das respostas de nome inexistente."
- **SMTP:** "Taxa de entrega, fila de envio, latência, taxa de erro e volume por minuto."
- Mostre o seletor de 5 minutos, 15 minutos e 1 hora em uma das páginas.

## Cena 5: Alertas, queda do banco (1:15)

**Tela:** terminal ao lado do painel, depois o Mailpit.

```powershell
.\scripts\demo_queda.ps1 postgres
```

**Narração:** "Vamos derrubar o banco de dados. O script para o container. Em cerca de 10 segundos o card fica vermelho." Mostre o card vermelho. "E chega um e-mail crítico no Mailpit, com o serviço, o valor, o limiar, o horário e o link para o painel." Abra o e-mail. "Agora religamos o banco: o card volta ao verde e chega o e-mail de recuperação, com a duração do incidente." Mostre a aba **Alertas** com o incidente resolvido e as regras com os limiares. "Para não gerar spam, a regra exige alguns ciclos seguidos antes de alertar e não reenvia enquanto o estado não muda."

## Cena 6: Segurança, DDoS e brute force (1:15)

**Tela:** aba Segurança do painel.

**Narração:**
- Clique em **Pico (DDoS)**: "Aqui simulamos um ataque de negação de serviço: mais de cem requisições por segundo, vindas de poucos IPs. O sistema compara o tráfego com a média dos últimos dez minutos: é o z-score. Em segundos o alerta vermelho aparece, e o top cinco de IPs mostra de onde vem o ataque." Clique em **Normal**.
- Clique em **Brute force**: "Agora tentativas repetidas de senha errada no painel administrativo e no banco. A plataforma conta as falhas por IP e por conta, em janelas de 60 segundos, e lista os IPs suspeitos." Clique em **Normal**.

## Cena 7: Segurança, configuração e vulnerabilidades (0:50)

**Tela:** terminal e aba Segurança.

```powershell
.\scripts\demo_config.ps1
```

**Narração:** "Para detectar alterações de configuração, guardamos o hash SHA-256 de cada arquivo. O script acrescenta um comentário no `nginx.conf`: em poucos segundos o monitor detecta, mostra os hashes antigo e novo e o diff, e envia o alerta. Ao restaurar o arquivo, o alerta se resolve. E se a mudança for legítima, o botão Aceitar nova baseline registra o novo estado." Role até **Vulnerabilidades**: "O Trivy escaneia as imagens e o painel mostra, por serviço, a contagem por severidade e os principais CVEs, com o pacote e a versão corrigida."

## Cena 8: Celular e testes (0:30)

**Tela:** navegador em modo celular (F12, ícone de dispositivo, 390 x 844), depois `docs/TESTES.md`.

**Narração:** "O painel é responsivo: no celular o menu vira um botão e não há rolagem horizontal. Por fim, uma suíte de dezesseis testes automatizados com Playwright confere as páginas, os gráficos, os filtros e os cenários de falha e ataque. Resultado: dezesseis de dezesseis aprovados."

## Cena 9: Encerramento (0:20)

**Tela:** slide ou README do repositório.

**Narração:** "Resumindo: monitoramento de quatro serviços, dashboards, alertas em três níveis com e-mail e segurança, tudo reproduzível com um comando. O código, a documentação e o relatório de processo estão no repositório. Obrigado."
