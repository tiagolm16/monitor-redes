"""App FastAPI: roda os coletores em segundo plano e expoe a API REST + front-end estatico."""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from . import storage
from .collectors.dns_check import DnsCollector
from .collectors.postgres import PostgresCollector
from .collectors.smtp_check import SmtpCollector
from .collectors.web import WebCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # senao loga cada requisicao dos coletores
log = logging.getLogger("monitor")

INTERVALO = float(os.getenv("COLLECT_INTERVAL", "5"))
SERVICOS = ["web", "db", "dns", "smtp"]
estado = {"inicio": time.time(), "ultimo_ciclo": None}


async def _coletar_um(coletor):
    """Roda um coletor com limite de tempo; se falhar, registra o servico como indisponivel (up=0)."""
    try:
        return await asyncio.wait_for(coletor.collect(), timeout=INTERVALO - 0.2)
    except Exception as e:  # um coletor quebrado nao pode derrubar os outros
        log.warning("coletor %s falhou: %r", coletor.service, e)
        return [("up", 0, None)]


async def loop_coleta():
    coletores = [WebCollector(), PostgresCollector(), DnsCollector(), SmtpCollector()]
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
        await asyncio.sleep(max(0.0, INTERVALO - (time.monotonic() - inicio)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init()
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
    saida = {s: {"service": s, "up": None, "ultima_leitura_ts": None, "metrics": {}} for s in SERVICOS}
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
def alerts():
    return storage.list_alerts()


# Front-end estatico (precisa vir por ultimo, senao "/" engole as rotas /api)
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True))
