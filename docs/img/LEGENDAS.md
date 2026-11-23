# Legendas das figuras

Uma linha por figura, para usar no artigo. Prints gerados por `scripts/capturar_prints.py`.

- **fig01_visao_geral_normal.png**: Visão Geral do dashboard em operação normal: cinco cards (Web, Banco, DNS, SMTP e Segurança) com status, métricas principais e mini gráfico.
- **fig02_web.png**: Página do Web Server (nginx): disponibilidade, RPS, latência, taxa de erro 4xx/5xx, conexões ativas e contagem de respostas por código HTTP.
- **fig03_banco.png**: Página do Banco de Dados (PostgreSQL): QPS, rollbacks, conexões, CPU, memória e IO do container, tamanho e crescimento do banco e slow queries.
- **fig04_dns.png**: Página do DNS (CoreDNS): tempo de resolução, QPS e separação entre falhas do servidor e respostas NXDOMAIN.
- **fig05_smtp.png**: Página do SMTP (Mailpit): taxa de entrega, fila de envio, latência, taxa de erro e volume de e-mails por minuto.
- **fig06_alertas_historico.png**: Página de Alertas com o histórico de incidentes (abertura, pior nível, resolução), filtros por nível e serviço e as regras do alerts.yaml.
- **fig07_queda_postgres_vermelho.png**: Queda do PostgreSQL: o card do banco fica vermelho (FORA DO AR) poucos segundos depois de o container ser parado.
- **fig08_email_critico_mailpit.png**: E-mail [CRÍTICO] de queda do PostgreSQL recebido no Mailpit, com serviço, métrica, valor, limiar, horário e link para o dashboard.
- **fig09_email_recuperado.png**: E-mail [RECUPERADO] enviado quando o PostgreSQL voltou ao ar, com a duração do incidente.
- **fig10_ddos_zscore.png**: Simulação de DDoS: o RPS salta bem acima da baseline, o z-score ultrapassa o limiar vermelho e o top 5 de IPs mostra as três origens do ataque.
- **fig11_bruteforce_ips.png**: Simulação de brute force: IPs suspeitos com contagem de falhas de login (nginx /admin e Postgres), contas alvo e gráfico das falhas por janela de 60 s.
- **fig12_config_alterada.png**: Detecção de alteração de configuração: o nginx.conf aparece como ALTERADO, com hash SHA-256 antigo e novo e o diff das linhas mudadas.
- **fig13_vulnerabilidades.png**: Vulnerabilidades conhecidas por serviço (Trivy): contagem por severidade e os principais CVEs com pacote, versão instalada e versão corrigida.
- **fig14_mobile_visao_geral.png**: Visão Geral em um celular (390x844): cards em coluna única, sem rolagem horizontal.
- **fig15_mobile_menu.png**: Menu hamburguer aberto no celular, listando todas as páginas do dashboard.
