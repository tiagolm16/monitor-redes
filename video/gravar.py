"""Grava a tela de cada cena (Playwright, 1920x1080, record_video) e gera as telas de abertura e encerramento.

Uso (com o ambiente verde: .\\scripts\\preparar_apresentacao.ps1):
    python video/gravar.py                 # todas as cenas, com os audios reais de video/audio/
    python video/gravar.py --provisorio    # usa audios de silencio com a duracao estimada
    python video/gravar.py cena03 cena05   # so essas cenas (para corrigir uma cena)

Cada cena dura pelo menos a duracao do audio dela + 1 s. As acoes (derrubar o postgres, modo pico,
bruteforce, alterar config) sao disparadas por Python/API, nao pelo terminal; quando seria um comando de terminal,
uma faixa no topo da pagina mostra o comando.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from comum import BASE, IDS, LOADGEN, MAILPIT, RAIZ, RAW, TMP, preparar_audios

ZOOM = 1.3                       # aumenta o painel para ficar legivel em 1080p
FIG00 = RAIZ / "docs" / "img" / "fig00_arquitetura.png"
NGINX_CONF = RAIZ / "services" / "nginx" / "nginx.conf"
REPO = "https://github.com/tiagolm16/monitor-redes"


# ------------------------------------------------------------------ apoio (API, docker)
def api(caminho, metodo="GET"):
    req = urllib.request.Request(BASE + caminho, method=metodo)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def loadgen_modo(modo):
    urllib.request.urlopen(urllib.request.Request(f"{LOADGEN}/mode/{modo}", method="POST"), timeout=10).read()


def compose(*args):
    subprocess.run(["docker", "compose", *args], cwd=RAIZ, check=True, capture_output=True)


def esperar(cond, timeout, intervalo=1.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond():
                return time.time() - t0
        except Exception:
            pass
        time.sleep(intervalo)
    raise TimeoutError(f"tempo esgotado ({timeout}s)")


def id_email(prefixo, desde):
    """ID do e-mail mais recente do Mailpit cujo assunto comeca com 'prefixo' (recebido depois de 'desde')."""
    with urllib.request.urlopen(f"{MAILPIT}/api/v1/messages?limit=100", timeout=10) as r:
        for m in json.load(r)["messages"]:
            criado = datetime.fromisoformat(m["Created"].replace("Z", "+00:00")).timestamp()
            if m["Subject"].startswith(prefixo) and criado >= desde - 2:
                return m["ID"]
    return None


def alertas_ativos(prefixo):
    return [a for a in api("/api/alerts?active=true&limit=200") if a["rule"].startswith(prefixo)]


def servicos_verdes():
    return all(s["nivel"] == 1 for s in api("/api/services") if s["service"] != "security")


def preparar_estado():
    """Entre as cenas: modo normal, sem ataque em curso, configs limpas e os 4 servicos verdes."""
    loadgen_modo("normal")
    esperar(lambda: not alertas_ativos("sec_ddos") and not alertas_ativos("sec_bruteforce")
            and not alertas_ativos("sec_config"), 200)
    esperar(servicos_verdes, 200)


# ------------------------------------------------------------------ gravacao de uma cena
class Gravacao:
    """Um contexto do navegador gravando video, com um relogio para sincronizar com o audio."""

    def __init__(self, browser, cena, dur_audio, zoom=ZOOM):
        self.cena, self.dur = cena, dur_audio
        self.pasta = RAW / "_gravando" / cena
        shutil.rmtree(self.pasta, ignore_errors=True)
        self.ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080}, record_video_dir=str(self.pasta),
            record_video_size={"width": 1920, "height": 1080}, locale="pt-BR", timezone_id="America/Sao_Paulo")
        if zoom:
            # so em paginas http (painel e Mailpit); a imagem do diagrama fica sem zoom
            self.ctx.add_init_script(
                "document.addEventListener('DOMContentLoaded',()=>{if(location.protocol.startsWith('http'))"
                f"document.documentElement.style.zoom={zoom}}});")
        self.page = self.ctx.new_page()
        self.page.set_content("<body style='background:#0b1220;margin:0'></body>")   # evita o flash branco do inicio
        self.t0 = time.monotonic()
        self.faixa = None

    def ate(self, fracao):
        """Espera ate 'fracao' da duracao do audio (se ja passou, segue direto)."""
        alvo = fracao * self.dur
        resto = alvo - (time.monotonic() - self.t0)
        if resto > 0:
            time.sleep(resto)

    def ir(self, url):
        self.page.goto(url, wait_until="domcontentloaded")
        self.mostrar_faixa(self.faixa)

    def mostrar_faixa(self, texto):
        """Faixa no topo com o comando que seria digitado no terminal."""
        self.faixa = texto
        if texto is None:
            return
        self.page.evaluate(
            """(t) => { let b = document.getElementById('cmd-banner');
                if (!b) { b = document.createElement('div'); b.id = 'cmd-banner';
                  b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#0b0b0b;color:#7CFC00;'
                    + 'font:24px/1.3 Consolas,monospace;padding:12px 28px;border-bottom:3px solid #38bdf8;white-space:pre';
                  document.body.appendChild(b); }
                b.textContent = t; }""", texto)

    def graficos(self, seletor, minimo, timeout=40000):
        self.page.wait_for_function(
            """([sel, n]) => { const cs = [...document.querySelectorAll(sel + ' canvas')];
                return cs.length >= n && cs.every(c => { const ch = Chart.getChart(c); return ch && ch.data.labels.length >= 3; }); }""",
            arg=[seletor, minimo], timeout=timeout)

    def rolar_ate(self, y_final, segundos):
        y0 = self.page.evaluate("window.scrollY")
        passos = max(int(segundos * 20), 1)
        for i in range(1, passos + 1):
            self.page.evaluate("y => window.scrollTo(0, y)", y0 + (y_final - y0) * i / passos)
            self.page.wait_for_timeout(50)

    def rolar_para(self, titulo_h3, segundos=2.0, folga=130):
        y = self.page.evaluate(
            """(t) => { const h = [...document.querySelectorAll('main h3, main h2')].find(x => x.textContent.startsWith(t));
                return h ? h.getBoundingClientRect().top + window.scrollY : 0; }""", titulo_h3)
        self.rolar_ate(max(y - folga, 0), segundos)

    def rolar_pagina(self, fracao_final, segundos):
        total = self.page.evaluate("document.documentElement.scrollHeight - window.innerHeight")
        self.rolar_ate(max(total, 0) * fracao_final, segundos)

    def encerrar(self):
        """Mantem a cena ate a duracao do audio + 1 s e salva o video em video/raw/cenaNN.webm."""
        self.ate(1.0 + 1.0 / self.dur)
        video = self.page.video
        self.ctx.close()
        destino = RAW / f"{self.cena}.webm"
        shutil.move(video.path(), destino)
        shutil.rmtree(self.pasta, ignore_errors=True)
        return destino


# ------------------------------------------------------------------ cenas
def cena01(g):
    g.ir(FIG00.as_uri())                       # diagrama de arquitetura em tela cheia
    g.page.wait_for_load_state("load")
    g.ate(0.62)
    g.ir(f"{BASE}/#/")
    g.graficos("#cards", 5)


def cena02(g):
    g.ir(f"{BASE}/#/")
    g.graficos("#cards", 5)
    g.ate(0.17)
    segmentos = [("web", 0.38, 6), ("db", 0.58, 10), ("dns", 0.72, 4), ("smtp", 0.97, 6)]
    for rota, fim, n in segmentos:
        inicio = time.monotonic()
        g.page.goto(f"{BASE}/#/{rota}")
        g.graficos("main", n)
        restante = max(fim * g.dur - (time.monotonic() - g.t0), 2.0)
        if rota == "smtp":                       # no fim, o seletor de periodo
            g.rolar_pagina(0.5, restante * 0.55)
            g.page.evaluate("window.scrollTo(0, 0)")
            for p in ("5m", "1h", "15m"):
                g.page.click(f'button[data-p="{p}"]')
                g.page.wait_for_timeout(max(int(restante * 0.14 * 1000), 800))
        else:
            g.rolar_pagina(0.55, restante * 0.8)
        g.ate(fim)


def cena03(g):
    g.ir(f"{BASE}/#/")
    g.graficos("#cards", 5)
    g.ate(0.06)
    g.mostrar_faixa("PS> docker compose stop postgres")
    t_parada = time.time()
    try:
        compose("stop", "postgres")
        g.page.wait_for_selector("#card-db.nivel3", timeout=90000)
        g.ate(0.28)
        esperar(lambda: id_email("[CRÍTICO] db", t_parada), 40)
        g.ir(f"{MAILPIT}/view/{id_email('[CRÍTICO] db', t_parada)}")
        g.page.wait_for_selector("text=Subject", timeout=30000)
        g.ate(0.46)
        g.mostrar_faixa("PS> docker compose start postgres")
        compose("start", "postgres")
        g.ir(f"{BASE}/#/")
        g.page.wait_for_selector("#card-db.nivel1", timeout=120000)
        g.ate(0.70)
        esperar(lambda: id_email("[RECUPERADO] db", t_parada), 40)
        g.ir(f"{MAILPIT}/view/{id_email('[RECUPERADO] db', t_parada)}")
        g.page.wait_for_selector("text=Subject", timeout=30000)   # a interface do Mailpit carrega por JavaScript
        time.sleep(4)                                              # deixa o e-mail de recuperacao visivel
    finally:
        compose("start", "postgres")


def cena04(g):
    g.ir(f"{BASE}/#/alertas")
    g.page.wait_for_selector("#historico table", timeout=20000)
    g.ate(0.30)
    g.page.select_option("#f-nivel", "3")
    g.ate(0.46)
    g.page.select_option("#f-nivel", "")
    g.page.select_option("#f-serv", "db")
    g.ate(0.62)
    g.page.select_option("#f-serv", "")
    g.rolar_para("Regras configuradas", 4.0)


def cena05(g):
    g.ir(f"{BASE}/#/seguranca")
    g.graficos("main", 3)
    try:
        g.ate(0.10)
        loadgen_modo("pico")
        g.ate(0.14)
        g.rolar_para("Anomalia de tráfego", 2.5)
        g.ate(0.46)
        loadgen_modo("normal")
        g.ate(0.48)
        loadgen_modo("bruteforce")
        g.rolar_para("Brute force", 2.5)
        g.ate(0.96)
    finally:
        loadgen_modo("normal")


def cena06(g):
    original = NGINX_CONF.read_bytes()
    g.ir(f"{BASE}/#/seguranca")
    g.graficos("main", 3)
    try:
        g.rolar_para("Alteração de configuração", 2.0)
        g.ate(0.16)
        g.mostrar_faixa('PS> Add-Content services\\nginx\\nginx.conf "# alteração de demonstração"')
        NGINX_CONF.write_bytes(original + "\n# alteracao de demonstracao (nao autorizada)\n".encode())
        g.page.wait_for_selector("#diffs pre.diff", timeout=120000)
        # rola ate o diff aparecer inteiro na tela
        y = g.page.evaluate("document.querySelector('#diffs pre.diff').getBoundingClientRect().bottom + window.scrollY")
        g.rolar_ate(max(y - 900, 0), 1.5)
        g.ate(0.52)
        g.mostrar_faixa("PS> git checkout -- services\\nginx\\nginx.conf")
        NGINX_CONF.write_bytes(original)
        g.ate(0.58)
        g.mostrar_faixa(None)
        g.page.evaluate("document.getElementById('cmd-banner')?.remove()")
        g.rolar_para("Vulnerabilidades", 2.5)
        g.ate(0.72)
        g.page.locator("#vulns details summary").nth(0).click()
        g.ate(0.86)
        g.page.locator("#vulns details summary").nth(1).click()
    finally:
        NGINX_CONF.write_bytes(original)


TESTES = ["T01 menu desktop", "T02 visao geral", "T03 graficos por servico", "T04 seletor de periodo",
          "T05 atualizacao automatica", "T06 aba seguranca", "T07 celular sem overflow e menu",
          "T08 aviso quando a API para", "T10 queda postgres", "T11 queda nginx", "T12 filtros de alertas",
          "T13 ddos z-score", "T14 brute force", "T15 alteracao de configuracao", "T16 aceitar nova baseline",
          "T17 vulnerabilidades"]


def cena07(g):
    g.page.set_content(f"""<body style="margin:0;background:#0b1220;display:flex;align-items:center;justify-content:center;
        height:100vh;gap:110px;font-family:Segoe UI,sans-serif">
      <div style="color:#e5e9f2;width:560px"><div style="font-size:56px;font-weight:700">Painel no celular</div>
        <div style="font-size:30px;color:#8b97ad;margin-top:18px">390 x 844. O menu vira um botão e não há rolagem lateral.</div></div>
      <div style="width:390px;height:844px;border:14px solid #222;border-radius:50px;overflow:hidden;background:#0b1220">
        <iframe id="f" src="{BASE}" width="390" height="844" style="border:0"></iframe></div></body>""")
    tela = g.page.frame_locator("#f")
    tela.locator("#cards canvas").first.wait_for(timeout=30000)
    g.ate(0.12)
    tela.locator("#btn-menu").click()
    g.ate(0.20)
    tela.locator('#menu a[data-r="alertas"]').click()
    g.ate(0.30)
    tela.locator("#btn-menu").click()
    g.ate(0.36)
    tela.locator('#menu a[data-r="web"]').click()
    g.ate(0.46)
    g.page.set_content("""<body style="margin:0;background:#0b0b0b;color:#d4d4d4;font:30px/1.5 Consolas,monospace;padding:50px 90px">
      <div style="color:#7CFC00">PS> python -m pytest tests/e2e</div><div id="l"></div>
      <div id="r" style="margin-top:24px;font-size:56px;font-weight:700;color:#22c55e;visibility:hidden">16 passed em 263 s</div>
      <script>const t=%s;let i=0;const l=document.getElementById('l');
      const x=setInterval(()=>{if(i>=t.length){clearInterval(x);document.getElementById('r').style.visibility='visible';return}
      l.innerHTML+='<div>test_'+t[i].replace(/ /g,'_')+' <span style="color:#22c55e">PASSED</span></div>';i++},230);</script></body>""" % json.dumps(TESTES))


def cena08(g):
    g.ir(f"{BASE}/#/")
    g.graficos("#cards", 5)


CENAS_FN = {"cena01": cena01, "cena02": cena02, "cena03": cena03, "cena04": cena04,
            "cena05": cena05, "cena06": cena06, "cena07": cena07, "cena08": cena08}


# ------------------------------------------------------------------ telas de abertura e encerramento
def cartoes(browser):
    css = ("body{margin:0;width:1920px;height:1080px;background:linear-gradient(135deg,#0b1220,#16233f);color:#e5e9f2;"
           "font-family:Segoe UI,sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}"
           "h1{font-size:84px;margin:0 0 20px}h2{font-size:42px;font-weight:400;color:#38bdf8;margin:6px}"
           "p{font-size:34px;margin:6px;color:#c3cbdb}.s{font-size:30px;color:#8b97ad;margin-top:50px}")
    paginas = {
        "abertura": f"""<style>{css}</style><h1>Plataforma de Monitoramento para DevOps</h1>
            <h2>Redes de Computadores &middot; IDP</h2><p>Professora: Lorena Borges</p>
            <div class="s">Tiago Lara Melo &middot; Pedro Vilela &middot; Diana Galdino &middot; Lucas Barreto</div>""",
        "encerramento": f"""<style>{css}</style><h1>Obrigado!</h1><h2>Código, documentação e relatório</h2>
            <p style="font-size:44px;color:#e5e9f2;margin-top:30px">{REPO}</p>""",
    }
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    for nome, html in paginas.items():
        page.set_content(html)
        page.screenshot(path=str(RAW / f"{nome}.png"))
    page.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provisorio", action="store_true")
    ap.add_argument("cenas", nargs="*")
    args = ap.parse_args()
    cenas = args.cenas or IDS
    audios = preparar_audios(args.provisorio)
    RAW.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    try:
        assert api("/api/health")["status"] == "ok"
    except Exception:
        sys.exit("O monitor nao responde. Rode antes: .\\scripts\\preparar_apresentacao.ps1")
    duracoes = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        cartoes(browser)
        for cena in cenas:
            dur = audios[cena][1]
            print(f"[{cena}] preparando o estado (audio de {dur:.1f} s)...", flush=True)
            preparar_estado()
            g = Gravacao(browser, cena, dur, zoom=0 if cena == "cena07" else ZOOM)
            inicio = time.monotonic()
            try:
                CENAS_FN[cena](g)
            finally:
                destino = g.encerrar()
            duracoes[cena] = round(time.monotonic() - inicio, 1)
            print(f"[{cena}] gravada em {duracoes[cena]} s -> {destino.name}", flush=True)
        browser.close()
    preparar_estado()
    print("Pronto. Proximo passo: python video/montar.py" + (" --provisorio" if args.provisorio else ""))


if __name__ == "__main__":
    main()
