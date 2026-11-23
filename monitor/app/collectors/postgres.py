"""Coletor do PostgreSQL (servico exposto como 'db').

Conecta pela porta TCP 5432 com o usuario 'monitor' (papel pg_monitor, so leitura de estatisticas).
Le views internas do Postgres e, se o docker.sock estiver montado, CPU/memoria do container.
"""
import asyncio
import os
import time

import asyncpg
import httpx

from .. import storage
from ..util import Taxas

PG_HOST = os.getenv("PG_HOST", "postgres")
PG_USER = os.getenv("PG_USER", "monitor")
PG_PASSWORD = os.getenv("PG_PASSWORD", "monitor")
PG_DB = os.getenv("PG_DB", "appdb")
PG_CONTAINER = os.getenv("PG_CONTAINER", "rd-postgres")
SLOW_MS = 200  # mesmo limite do log_min_duration_statement do postgresql.conf


class PostgresCollector:
    service = "db"

    def __init__(self) -> None:
        self.taxas = Taxas()
        self.docker = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds="/var/run/docker.sock"), timeout=3.5
        )

    async def collect(self):
        linhas = []
        # Em paralelo: estatisticas do Postgres e estatisticas do container
        pg, cont = await asyncio.gather(
            self._postgres(), self._container(), return_exceptions=True
        )
        if isinstance(pg, Exception):
            linhas.append(("up", 0, None))  # nao conectou: servico indisponivel
        else:
            linhas += pg
        if not isinstance(cont, Exception):
            linhas += cont
        return linhas

    async def _postgres(self):
        linhas = []
        inicio = time.perf_counter()
        # Abre uma conexao nova a cada ciclo: o tempo mede handshake TCP + autenticacao
        conn = await asyncpg.connect(
            host=PG_HOST, user=PG_USER, password=PG_PASSWORD, database=PG_DB, timeout=3
        )
        try:
            await conn.fetchval("SELECT 1")
            linhas.append(("up", 1, None))
            linhas.append(("connect_ms", (time.perf_counter() - inicio) * 1000, None))

            # Contadores acumulados do banco atual (viram taxa por segundo)
            st = await conn.fetchrow(
                """SELECT xact_commit, xact_rollback, blks_read,
                          pg_database_size(datname) AS tamanho
                   FROM pg_stat_database WHERE datname = current_database()"""
            )
            # pg_stat_statements: total de chamadas e de chamadas de queries lentas (media >= SLOW_MS)
            ss = await conn.fetchrow(
                """SELECT COALESCE(SUM(calls),0) AS calls,
                          COALESCE(SUM(calls) FILTER (WHERE mean_exec_time >= $1),0) AS lentas
                   FROM pg_stat_statements""",
                SLOW_MS,
            )
            conexoes = await conn.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend'"
            )
            max_conn = int(await conn.fetchval("SHOW max_connections"))
        finally:
            await conn.close()

        qps = self.taxas.por_segundo("calls", float(ss["calls"]))
        if qps is not None:
            linhas.append(("qps", qps, None))
        rb = self.taxas.por_segundo("rollbacks", st["xact_rollback"])
        if rb is not None:
            linhas.append(("rollbacks_per_s", rb, None))
        blocos = self.taxas.por_segundo("blks_read", st["blks_read"])
        if blocos is not None:
            linhas.append(("blocks_read_per_s", blocos, None))
        lentas = self.taxas.delta("lentas", float(ss["lentas"]))
        if lentas is not None:
            linhas.append(("slow_queries", lentas[0], None))  # novas lentas desde o ciclo anterior

        linhas.append(("connections", conexoes, None))
        linhas.append(("connections_max", max_conn, None))
        linhas.append(("connections_percent", 100 * conexoes / max_conn, None))
        linhas.append(("db_size_bytes", st["tamanho"], None))

        # Crescimento: compara o tamanho atual com a leitura mais antiga dos ultimos 15 min
        # guardada no proprio SQLite (o historico ja esta la, nao precisa de memoria extra).
        antigo = await asyncio.to_thread(storage.first_value, "db", "db_size_bytes", time.time() - 900)
        if antigo and time.time() - antigo[0] >= 60:
            mb_por_hora = (st["tamanho"] - antigo[1]) / (time.time() - antigo[0]) * 3600 / 1e6
            linhas.append(("db_growth_mb_per_h", mb_por_hora, None))
            linhas.append(("db_growth_gb_per_day", mb_por_hora * 24 / 1024, None))  # projecao linear
        return linhas

    async def _container(self):
        """CPU, memoria e IO de disco do container, via API do Docker (socket Unix)."""
        r = await self.docker.get(
            f"http://docker/containers/{PG_CONTAINER}/stats", params={"stream": "false"}
        )
        s = r.json()
        linhas = []
        cpu = s["cpu_stats"]
        pre = s["precpu_stats"]
        d_cpu = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        d_sys = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        if d_sys > 0:
            linhas.append(("cpu_percent", d_cpu / d_sys * cpu.get("online_cpus", 1) * 100, None))
        mem = s["memory_stats"]
        cache = mem.get("stats", {}).get("inactive_file", 0)
        linhas.append(("memory_mb", (mem["usage"] - cache) / 1_048_576, None))
        io = (s.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []
        if io:
            total = sum(e["value"] for e in io if e["op"].lower() in ("read", "write"))
            taxa = self.taxas.por_segundo("io_bytes", total)
            if taxa is not None:
                linhas.append(("io_bytes_per_s", taxa, None))
        return linhas
