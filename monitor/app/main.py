"""App FastAPI: roda os coletores em segundo plano e expoe a API REST + front-end estatico."""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from . import storage
from .alerts import Motor
from .collectors.dns_check import DnsCollector
import httpx

from . import config_watch
from .collectors.postgres import PostgresCollector
from .collectors.seguranca import SegurancaCollector
from .collectors.smtp_check import SmtpCollector
from .collectors.web import WebCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # senao loga cada requisicao dos coletores
log = logging.getLogger("monitor")

INTERVALO = float(os.getenv("COLLECT_INTERVAL", "5"))
SERVICOS = ["web", "db", "dns", "smtp", "security"]
LOADGEN_URL = os.getenv("LOADGEN_URL", "http://loadgen:8090")
estado = {"inicio": time.time(), "ultimo_ciclo": None}
motor: Motor | None = None
seguranca: SegurancaCollector | None = None


async def _coletar_um(coletor):
    """Roda um coletor com limite de tempo; se falhar, registra o servico como indisponivel (up=0)."""
    try:
        return await asyncio.wait_for(coletor.collect(), timeout=INTERVALO - 0.2)
    except Exception as e:  # um coletor quebrado nao pode derrubar os outros
        log.warning("coletor %s falhou: %r", coletor.service, e)
        return [("up", 0, None)]


async def loop_coleta():
    coletores = [WebCollector(), PostgresCollector(), DnsCollector(), SmtpCollector(), seguranca]
    while True:
        inicio = time.monotonic()
        ts = time.time()
        # Os 4 coletores rodam ao mesmo tempo (asyncio): o ciclo dura o tempo do mais lento
        resultados = await asyncio.gather(*(_coletar_um(c) for c in coletores))
        linhas = [
            (c.service, metrica, valor, labels)
            for c, res in zip(coletores, resultados)
            for metrica, valor, labels in res
        ]
        await asyncio.to_thread(storage.insert_rows, ts, linhas)
        estado["ultimo_ciclo"] = ts
        try:
            await motor.avaliar()  # decide o nivel de cada regra com os dados recem gravados
        except Exception:
            log.exception("erro no motor de alertas")
        await asyncio.sleep(max(0.0, INTERVALO - (time.monotonic() - inicio)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global motor, seguranca
    storage.init()
    seguranca = SegurancaCollector()
    motor = Motor(os.getenv("ALERTS_FILE", os.path.join(os.path.dirname(__file__), "..", "alerts.yaml")))
    motor.provedor_detalhe = seguranca.detalhe_alerta  # e-mails de seguranca levam IPs, hashes e diff
    tarefa = asyncio.create_task(loop_coleta())
    yield
    tarefa.cancel()


app = FastAPI(title="Monitor de Redes", lifespan=lifespan)


def _parse_since(valor: str) -> float:
    """Aceita '90s', '15m', '2h', '1d' (tempo atras) ou um timestamp Unix."""
    unidades = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        if valor[-1] in unidades:
            return time.time() - float(valor[:-1]) * unidades[valor[-1]]
        n = float(valor)
        return n if n > 1e9 else time.time() - n
    except (ValueError, IndexError):
        raise HTTPException(422, "since invalido. Exemplos: 90s, 15m, 2h, 1d")


@app.get("/api/health")
def health():
    ultimo = estado["ultimo_ciclo"]
    return {
        "status": "ok" if ultimo and time.time() - ultimo < INTERVALO * 3 else "degradado",
        "uptime_s": round(time.time() - estado["inicio"]),
        "ultimo_ciclo_ts": ultimo,
        "linhas_no_banco": storage.count_rows(),
    }


@app.get("/api/services")
def services():
    """Visao consolidada: para cada servico, estado (up/down) e ultimo valor de cada metrica."""
    agora = time.time()
    niveis = motor.nivel_servicos()
    ativos = storage.list_alerts(500, active=True)
    saida = {
        s: {"service": s, "up": None, "nivel": niveis.get(s, 1),
            "alertas_ativos": sum(1 for a in ativos if a["service"] == s),
            "ultima_leitura_ts": None, "metrics": {}}
        for s in SERVICOS
    }
    for linha in storage.latest(60):
        item = saida.get(linha["service"])
        if item is None:
            continue
        item["ultima_leitura_ts"] = max(item["ultima_leitura_ts"] or 0, linha["ts"])
        if linha["metric"] == "up":
            item["up"] = bool(linha["value"]) and agora - linha["ts"] < INTERVALO * 3
        elif linha["labels"]:  # metricas com label (ex.: codigo HTTP) viram {rotulo: valor}
            chave = ",".join(linha["labels"].values())
            item["metrics"].setdefault(linha["metric"], {})[chave] = linha["value"]
        else:
            item["metrics"][linha["metric"]] = linha["value"]
    return list(saida.values())


@app.get("/api/metrics")
def metrics(
    service: str | None = None,
    metric: str | None = None,
    since: str = "15m",
    limit: int = Query(5000, ge=1, le=20000),
):
    if service and service not in SERVICOS:
        raise HTTPException(404, f"servico desconhecido. Use um de: {', '.join(SERVICOS)}")
    return storage.query_metrics(service, metric, _parse_since(since), limit)


@app.get("/api/alerts")
def alerts(
    service: str | None = None,
    level: int | None = Query(None, ge=2, le=3, description="pior nivel do incidente"),
    active: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Historico de incidentes (mais recentes primeiro). active=true so os ainda abertos."""
    return storage.list_alerts(limit, service, level, active)


@app.get("/api/alert-rules")
def alert_rules():
    """Regras do alerts.yaml com o nivel e o ultimo valor avaliado de cada uma."""
    return motor.listar_regras()


@app.get("/api/security")
def security():
    """Painel de seguranca: trafego/DDoS, brute force, configuracao e vulnerabilidades."""
    est = seguranca.estado
    arquivos = est["config"]
    return {
        "nivel": motor.nivel_servicos().get("security", 1),
        "ddos": est["ddos"],
        "top_ips": est["top_ips"],
        "brute": est["brute"],
        "config": {"arquivos": arquivos, "alterados": sum(1 for a in arquivos if a["status"] != "ok")},
        "vulns": seguranca.vulns,
        "regras": [r for r in motor.listar_regras() if r["servico"] == "security"],
    }


@app.post("/api/security/config/accept")
def accept_config():
    """Aceita o estado atual dos arquivos de /config como a nova baseline (mudanca autorizada)."""
    config_watch.aceitar_baseline()
    return {"ok": True}


@app.get("/api/loadgen")
async def loadgen_modo():
    """Modo atual do gerador de trafego (normal | pico | bruteforce)."""
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            return (await c.get(f"{LOADGEN_URL}/mode")).json()
    except httpx.HTTPError:
        raise HTTPException(502, "loadgen indisponivel")


@app.post("/api/loadgen/{modo}")
async def loadgen_trocar(modo: str):
    """Troca o modo do loadgen ao vivo (usado pelos botoes da aba Seguranca)."""
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.post(f"{LOADGEN_URL}/mode/{modo}")
            return r.json()
    except httpx.HTTPError:
        raise HTTPException(502, "loadgen indisponivel")


# Front-end estatico (precisa vir por ultimo, senao "/" engole as rotas /api)
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True))
