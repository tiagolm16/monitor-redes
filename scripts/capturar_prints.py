"""Reproduz os cenarios e salva os prints padronizados em docs/img/ (figuras do artigo).

Uso (com o ambiente no ar e o scan do Trivy ja executado):
    python scripts/capturar_prints.py

Desktop: 1440x900. Celular: 390x844 com emulacao de dispositivo (escala 2x, toque, user agent mobile).
O script derruba o postgres, liga os modos pico e bruteforce e altera o nginx.conf; ao final (mesmo com erro)
restaura tudo.
"""
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "tests" / "e2e"))

from playwright.sync_api import sync_playwright  # noqa: E402

from conftest import (BASE, MAILPIT, NGINX_CONF, alerta_ativo, alerta_resolvido, api, assuntos_emails,  # noqa: E402
                      compose, esperar, graficos_com_dados, loadgen_modo)

SELECAO = {a.replace(".png", "")[:5] for a in sys.argv[1:]}   # ex.: fig01 fig06 (vazio = todas)
IMG = RAIZ / "docs" / "img"
IMG.mkdir(parents=True, exist_ok=True)

LEGENDAS = {
    "fig01_visao_geral_normal": "Visão Geral do dashboard em operação normal: cinco cards (Web, Banco, DNS, SMTP e Segurança) com status, métricas principais e mini gráfico.",
    "fig02_web": "Página do Web Server (nginx): disponibilidade, RPS, latência, taxa de erro 4xx/5xx, conexões ativas e contagem de respostas por código HTTP.",
    "fig03_banco": "Página do Banco de Dados (PostgreSQL): QPS, rollbacks, conexões, CPU, memória e IO do container, tamanho e crescimento do banco e slow queries.",
    "fig04_dns": "Página do DNS (CoreDNS): tempo de resolução, QPS e separação entre falhas do servidor e respostas NXDOMAIN.",
    "fig05_smtp": "Página do SMTP (Mailpit): taxa de entrega, fila de envio, latência, taxa de erro e volume de e-mails por minuto.",
    "fig06_alertas_historico": "Página de Alertas com o histórico de incidentes (abertura, pior nível, resolução), filtros por nível e serviço e as regras do alerts.yaml.",
    "fig07_queda_postgres_vermelho": "Queda do PostgreSQL: o card do banco fica vermelho (FORA DO AR) poucos segundos depois de o container ser parado.",
    "fig08_email_critico_mailpit": "E-mail [CRÍTICO] de queda do PostgreSQL recebido no Mailpit, com serviço, métrica, valor, limiar, horário e link para o dashboard.",
    "fig09_email_recuperado": "E-mail [RECUPERADO] enviado quando o PostgreSQL voltou ao ar, com a duração do incidente.",
    "fig10_ddos_zscore": "Simulação de DDoS: o RPS salta bem acima da baseline, o z-score ultrapassa o limiar vermelho e o top 5 de IPs mostra as três origens do ataque.",
    "fig11_bruteforce_ips": "Simulação de brute force: IPs suspeitos com contagem de falhas de login (nginx /admin e Postgres), contas alvo e gráfico das falhas por janela de 60 s.",
    "fig12_config_alterada": "Detecção de alteração de configuração: o nginx.conf aparece como ALTERADO, com hash SHA-256 antigo e novo e o diff das linhas mudadas.",
    "fig13_vulnerabilidades": "Vulnerabilidades conhecidas por serviço (Trivy): contagem por severidade e os principais CVEs com pacote, versão instalada e versão corrigida.",
    "fig14_mobile_visao_geral": "Visão Geral em um celular (390x844): cards em coluna única, sem rolagem horizontal.",
    "fig15_mobile_menu": "Menu hamburguer aberto no celular, listando todas as páginas do dashboard.",
}


def quer(*figuras):
    """True se alguma das figuras foi pedida na linha de comando (ou se nenhuma foi: gera todas)."""
    return not SELECAO or any(f in SELECAO for f in figuras)


def salvar(page, nome, completa=True, clip=None):
    if SELECAO and nome[:5] not in SELECAO:
        return
    kwargs = {"path": str(IMG / f"{nome}.png")}
    if clip:
        # O cabecalho e "sticky": em prints de trecho da pagina ele apareceria no meio da imagem
        page.add_style_tag(content="header { position: static !important; }")
        kwargs.update(full_page=True, clip=clip)
    else:
        kwargs["full_page"] = completa
    page.screenshot(**kwargs)
    print(f"  salvo {nome}.png")


def secao(page, titulo_ini, titulo_fim=None):
    """Retorna o 'clip' (retangulo) que vai do h3 titulo_ini ate o h3 titulo_fim (ou o fim da pagina)."""
    return page.evaluate(
        """([ini, fim]) => {
            const h3 = [...document.querySelectorAll('main h3')];
            const a = h3.find(h => h.textContent.startsWith(ini));
            const b = fim ? h3.find(h => h.textContent.startsWith(fim)) : null;
            const y0 = a.getBoundingClientRect().top + window.scrollY - 8;
            const main = document.querySelector('main').getBoundingClientRect();
            const y1 = b ? b.getBoundingClientRect().top + window.scrollY - 8 : main.bottom + window.scrollY;
            return { x: 0, y: y0, width: 1440, height: y1 - y0 };
        }""", [titulo_ini, titulo_fim])


def aguardar_verde(page):
    page.goto(BASE)
    for s in ("web", "db", "dns", "smtp"):
        page.wait_for_selector(f"#card-{s}.nivel1", timeout=120000)
    graficos_com_dados(page, "#cards", 5)
    page.wait_for_timeout(1500)


def abrir_email(page, prefixo, desde, nome):
    """Abre no Mailpit o e-mail mais recente cujo assunto comeca com 'prefixo' (recebido depois de 'desde')."""
    from datetime import datetime
    msgs = api_mailpit()
    criado = lambda m: datetime.fromisoformat(m["Created"].replace("Z", "+00:00")).timestamp()
    alvo = next(m for m in msgs if m["Subject"].startswith(prefixo) and criado(m) >= desde - 2)
    page.goto(f"{MAILPIT}/view/{alvo['ID']}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2500)
    salvar(page, nome, completa=False)


def api_mailpit():
    import json
    with urllib.request.urlopen(f"{MAILPIT}/api/v1/messages?limit=100", timeout=10) as r:
        return json.load(r)["messages"]


def main():
    original_nginx = NGINX_CONF.read_bytes()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="pt-BR")
        page = ctx.new_page()
        try:
            loadgen_modo("normal")
            print("Aguardando o sistema ficar verde e com dados...")
            aguardar_verde(page)

            if quer("fig01", "fig02", "fig03", "fig04", "fig05"):
                print("Figuras 01 a 05 (operacao normal)")
                salvar(page, "fig01_visao_geral_normal", completa=False)
                for rota, nome in (("web", "fig02_web"), ("db", "fig03_banco"), ("dns", "fig04_dns"), ("smtp", "fig05_smtp")):
                    page.goto(f"{BASE}/#/{rota}")
                    graficos_com_dados(page, "main", 4)
                    page.wait_for_timeout(1500)
                    salvar(page, nome)

            if quer("fig07", "fig08", "fig09"):
                print("Figuras 07 a 09 (queda do postgres e e-mails)")
                from datetime import datetime, timezone
                inicio_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                t0 = time.time()
                compose("stop", "postgres")
                page.goto(BASE)
                page.wait_for_selector("#card-db.nivel3", timeout=60000)
                page.wait_for_timeout(1500)
                salvar(page, "fig07_queda_postgres_vermelho", completa=False)
                esperar(lambda: any(s.startswith("[CRÍTICO] db") for s in assuntos_emails(t0)), 30, descricao="e-mail critico")
                abrir_email(page, "[CRÍTICO] db", t0, "fig08_email_critico_mailpit")
                compose("start", "postgres")
                page.goto(BASE)
                page.wait_for_selector("#card-db.nivel1", timeout=120000)
                esperar(lambda: any(s.startswith("[RECUPERADO] db") for s in assuntos_emails(t0)), 30, descricao="e-mail de recuperacao")
                abrir_email(page, "[RECUPERADO] db", t0, "fig09_email_recuperado")

            if quer("fig06"):
                print("Figura 06 (historico de alertas)")
                page.goto(f"{BASE}/#/alertas")
                page.wait_for_selector("#historico table")
                page.wait_for_timeout(1000)
                salvar(page, "fig06_alertas_historico")

            if quer("fig10"):
                print("Figura 10 (DDoS)")
                t0 = time.time()
                loadgen_modo("pico")
                esperar(lambda: alerta_ativo("sec_ddos", t0), 60, descricao="alerta DDoS")
                page.wait_for_timeout(20000)       # deixa o grafico mostrar a subida do RPS
                page.goto(f"{BASE}/#/seguranca")
                graficos_com_dados(page, "main", 3)
                page.wait_for_timeout(3000)
                salvar(page, "fig10_ddos_zscore", clip=secao(page, "Alertas de segurança", "Brute force"))
                loadgen_modo("normal")
                esperar(lambda: alerta_resolvido("sec_ddos", t0), 150, descricao="DDoS resolvido")

            if quer("fig11"):
                print("Figura 11 (brute force)")
                t0 = time.time()
                loadgen_modo("bruteforce")
                esperar(lambda: alerta_ativo("sec_bruteforce", t0), 60, descricao="alerta brute force")
                page.wait_for_timeout(25000)
                page.goto(f"{BASE}/#/seguranca")
                graficos_com_dados(page, "main", 3)
                page.wait_for_timeout(3000)
                salvar(page, "fig11_bruteforce_ips", clip=secao(page, "Brute force", "Alteração"))
                loadgen_modo("normal")
                esperar(lambda: alerta_resolvido("sec_bruteforce", t0), 150, descricao="brute force resolvido")

            if quer("fig12"):
                print("Figura 12 (configuracao alterada)")
                t0 = time.time()
                NGINX_CONF.write_bytes(original_nginx + b"\n# alteracao de demonstracao (nao autorizada)\n")
                esperar(lambda: alerta_ativo("sec_config", t0), 30, descricao="alerta de config")
                page.goto(f"{BASE}/#/seguranca")
                page.wait_for_selector("#diffs pre.diff", timeout=15000)
                page.wait_for_timeout(1500)
                salvar(page, "fig12_config_alterada", clip=secao(page, "Alteração", "Vulnerabilidades"))
                NGINX_CONF.write_bytes(original_nginx)
                esperar(lambda: alerta_resolvido("sec_config", t0), 40, descricao="config resolvida")

            if quer("fig13"):
                print("Figura 13 (vulnerabilidades)")
                page.goto(f"{BASE}/#/seguranca")
                page.wait_for_selector("#vulns .card", timeout=15000)
                for resumo in page.locator("#vulns details summary").all():
                    resumo.click()
                page.wait_for_timeout(1000)
                salvar(page, "fig13_vulnerabilidades", clip=secao(page, "Vulnerabilidades"))

            if quer("fig14", "fig15"):
                print("Figuras 14 e 15 (celular)")
                mctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                           is_mobile=True, has_touch=True, locale="pt-BR")
                m = mctx.new_page()
                m.goto(BASE)
                graficos_com_dados(m, "#cards", 5)
                m.wait_for_timeout(1500)
                salvar(m, "fig14_mobile_visao_geral")
                m.click("#btn-menu")
                m.wait_for_selector("#menu.aberto")
                salvar(m, "fig15_mobile_menu", completa=False)
                mctx.close()
        finally:
            loadgen_modo("normal")
            compose("start", "nginx", "postgres", "coredns", "mailpit")
            NGINX_CONF.write_bytes(original_nginx)
            browser.close()

    corpo = "# Legendas das figuras\n\nUma linha por figura, para usar no artigo. Prints gerados por `scripts/capturar_prints.py`.\n\n"
    corpo += "\n".join(f"- **{nome}.png**: {txt}" for nome, txt in LEGENDAS.items()) + "\n"
    if not SELECAO:
        (IMG / "LEGENDAS.md").write_text(corpo, encoding="utf-8", newline="\n")
    print("docs/img/LEGENDAS.md gerado.")


if __name__ == "__main__":
    main()
