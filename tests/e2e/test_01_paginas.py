"""Testes de navegacao e uso do dashboard (sem derrubar nada)."""
import re

from playwright.sync_api import expect

from conftest import BASE, evidencia, graficos_com_dados

PAGINAS = [("", "Visão Geral"), ("web", "Web Server"), ("db", "Banco de Dados"), ("dns", "DNS"),
           ("smtp", "SMTP"), ("alertas", "Alertas"), ("seguranca", "Segurança")]
# quantidade de graficos por pagina de servico (definida em app.js)
GRAFICOS = {"web": 6, "db": 10, "dns": 4, "smtp": 6}


def test_T01_menu_desktop(page):
    page.goto(BASE)
    for rota, titulo in PAGINAS:
        page.click(f'#menu a[data-r="{rota}"]')
        expect(page.locator("main h2")).to_contain_text(titulo)
        expect(page.locator(f'#menu a[data-r="{rota}"]')).to_have_class(re.compile("ativo"))
    evidencia(page, "T01_menu_desktop", completa=False)


def test_T02_visao_geral(page):
    page.goto(BASE)
    expect(page.locator("#cards .card")).to_have_count(5)
    graficos_com_dados(page, "#cards", 5)
    expect(page.locator("#atualizacao")).to_contain_text("Última atualização")
    evidencia(page, "T02_visao_geral")


def test_T03_graficos_por_servico(page):
    for servico, qtd in GRAFICOS.items():
        page.goto(f"{BASE}/#/{servico}")
        graficos_com_dados(page, "main", qtd)
        assert page.locator("main canvas").count() == qtd, f"{servico}: esperados {qtd} graficos"
        expect(page.locator("#tiles .kpi").first).to_be_visible()
        evidencia(page, f"T03_{servico}")


def test_T04_seletor_de_periodo(page):
    page.goto(f"{BASE}/#/web")
    graficos_com_dados(page, "main", 6)
    labels = lambda: page.evaluate("Chart.getChart(document.querySelector('main canvas')).data.labels.length")
    page.click('button[data-p="5m"]')
    page.wait_for_function("(() => { const c = Chart.getChart(document.querySelector('main canvas')); return c && c.data.labels.length > 0 && c.data.labels.length <= 70; })()")
    curto = labels()
    page.click('button[data-p="15m"]')
    page.wait_for_function("(() => { const c = Chart.getChart(document.querySelector('main canvas')); return c && c.data.labels.length > 70; })()")
    longo = labels()
    assert curto <= 70 < longo
    expect(page.locator('button[data-p="15m"]')).to_have_class(re.compile("ativo"))


def test_T05_atualizacao_automatica(page):
    page.goto(BASE)
    page.wait_for_selector("#atualizacao:text('Última')")
    antes = page.inner_text("#atualizacao")
    page.wait_for_function("(a) => document.getElementById('atualizacao').textContent !== a", arg=antes, timeout=12000)


def test_T06_aba_seguranca(page):
    page.goto(f"{BASE}/#/seguranca")
    graficos_com_dados(page, "main", 3)
    expect(page.locator("#tiles-ddos .kpi")).to_have_count(6)
    expect(page.locator("#top-ips table tr")).not_to_have_count(0)
    expect(page.locator("#config table")).to_contain_text("nginx/nginx.conf")
    expect(page.locator("#vulns .card")).to_have_count(4)   # exige o scan do Trivy executado
    page.locator("#vulns details summary").first.click()
    expect(page.locator("#vulns details table").first).to_be_visible()
    evidencia(page, "T06_seguranca")


def test_T07_celular_sem_overflow_e_menu(mobile):
    mobile.goto(BASE)
    graficos_com_dados(mobile, "#cards", 5)
    for rota, _ in PAGINAS:
        mobile.goto(f"{BASE}/#/{rota}")
        mobile.wait_for_timeout(600)
        largura = mobile.evaluate("document.documentElement.scrollWidth")
        assert largura <= 376, f"rolagem horizontal em #{rota}: scrollWidth={largura}"
    mobile.goto(BASE)
    expect(mobile.locator("#btn-menu")).to_be_visible()
    expect(mobile.locator("#menu")).to_be_hidden()
    mobile.click("#btn-menu")
    expect(mobile.locator("#menu")).to_be_visible()
    evidencia(mobile, "T07_celular_menu_aberto", completa=False)
    mobile.click('#menu a[data-r="alertas"]')
    expect(mobile.locator("main h2")).to_contain_text("Alertas")
    expect(mobile.locator("#menu")).to_be_hidden()   # o menu fecha depois de escolher


def test_T08_aviso_quando_api_para(page):
    page.goto(BASE)
    page.wait_for_selector("#atualizacao:text('Última')")
    page.route("**/api/**", lambda rota: rota.abort())      # simula a API fora do ar
    expect(page.locator("#aviso")).to_have_class(re.compile("visivel"), timeout=15000)
    expect(page.locator("#aviso")).to_contain_text("não está respondendo")
    expect(page.locator("#ponto")).to_have_class(re.compile("erro"))
    evidencia(page, "T08_aviso_api_fora", completa=False)
