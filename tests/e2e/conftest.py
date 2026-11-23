"""Fixtures e funcoes de apoio da suite E2E (Playwright + pytest).

Pre-requisito: o ambiente no ar (docker compose up -d --build) e o Google Chrome instalado
(o Playwright usa o Chrome do sistema, sem baixar outro navegador).
Executar: python -m pytest tests/e2e -v
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[2]
BASE = "http://localhost:8000"
MAILPIT = "http://localhost:8025"
LOADGEN = "http://localhost:8090"
EVIDENCIAS = RAIZ / "docs" / "img" / "testes"
NGINX_CONF = RAIZ / "services" / "nginx" / "nginx.conf"


# ---------------------------------------------------------------- HTTP/Docker
def api(caminho: str, metodo: str = "GET"):
    req = urllib.request.Request(BASE + caminho, method=metodo)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def loadgen_modo(modo: str):
    req = urllib.request.Request(f"{LOADGEN}/mode/{modo}", method="POST")
    urllib.request.urlopen(req, timeout=10).read()


def compose(*args: str):
    subprocess.run(["docker", "compose", *args], cwd=RAIZ, check=True, capture_output=True)


def assuntos_emails(desde: float) -> list[str]:
    """Assuntos dos e-mails de alerta (comecam com '[') recebidos no Mailpit depois de 'desde'."""
    with urllib.request.urlopen(f"{MAILPIT}/api/v1/messages?limit=100", timeout=10) as r:
        msgs = json.load(r)["messages"]
    from datetime import datetime
    saida = []
    for m in msgs:
        criado = datetime.fromisoformat(m["Created"].replace("Z", "+00:00")).timestamp()
        if criado >= desde - 2 and m["Subject"].startswith("["):
            saida.append(m["Subject"])
    return saida


def esperar(condicao, timeout: float, intervalo: float = 1.0, descricao: str = "condicao"):
    """Repete 'condicao()' ate ela retornar algo verdadeiro. Retorna os segundos gastos."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if condicao():
                return time.time() - t0
        except Exception:
            pass
        time.sleep(intervalo)
    raise AssertionError(f"tempo esgotado ({timeout}s) esperando: {descricao}")


def alerta_ativo(prefixo_regra: str, desde: float = 0) -> bool:
    return any(a["rule"].startswith(prefixo_regra) and a["opened_ts"] >= desde - 2
               for a in api("/api/alerts?active=true&limit=200"))


def alerta_resolvido(prefixo_regra: str, desde: float) -> bool:
    return not any(a["rule"].startswith(prefixo_regra) for a in api("/api/alerts?active=true&limit=200"))


def evidencia(page, nome: str, completa: bool = True):
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(EVIDENCIAS / f"{nome}.png"), full_page=completa, timeout=90000)


def graficos_com_dados(page, seletor: str, minimo: int, pontos: int = 3, timeout=30000):
    """Espera 'minimo' canvases dentro de 'seletor' com graficos Chart.js que ja tem dados."""
    page.wait_for_function(
        """([sel, minimo, pontos]) => {
            const cs = [...document.querySelectorAll(sel + ' canvas')];
            if (cs.length < minimo) return false;
            return cs.every(c => { const ch = Chart.getChart(c); return ch && ch.data.labels.length >= pontos; });
        }""",
        arg=[seletor, minimo, pontos], timeout=timeout)


MARCADORES = ("# alteracao de", "# mudanca autorizada")


def limpar_marcadores_de_teste():
    """Remove do final do nginx.conf linhas deixadas por uma execucao anterior interrompida."""
    linhas = NGINX_CONF.read_bytes().decode("utf-8").split("\n")
    while linhas and (linhas[-1].strip() == "" or linhas[-1].startswith(MARCADORES)):
        linhas.pop()
    limpo = ("\n".join(linhas) + "\n").encode("utf-8")
    if limpo != NGINX_CONF.read_bytes():
        NGINX_CONF.write_bytes(limpo)


@pytest.fixture(scope="session", autouse=True)
def nginx_conf_integro():
    """Garante um nginx.conf limpo antes e depois da suite (os testes de config o alteram de proposito)."""
    limpar_marcadores_de_teste()
    yield
    limpar_marcadores_de_teste()


@pytest.fixture(scope="session", autouse=True)
def ambiente_no_ar():
    try:
        assert api("/api/health")["status"] == "ok"
    except Exception:
        pytest.exit("O monitor nao esta respondendo em http://localhost:8000. Rode: docker compose up -d --build")
    loadgen_modo("normal")


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="pt-BR")
    p = ctx.new_page()
    yield p
    ctx.close()


@pytest.fixture
def mobile(browser):
    # Emulacao de dispositivo (viewport, escala, toque e user agent de celular), como em um iPhone
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, device_scale_factor=2,
                              is_mobile=True, has_touch=True, locale="pt-BR")
    p = ctx.new_page()
    yield p
    ctx.close()
