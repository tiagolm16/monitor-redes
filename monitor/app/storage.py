"""Armazenamento em SQLite: uma unica tabela de serie temporal.

Cada linha = uma medicao: (ts, service, metric, value, labels).
Exemplo: (1732700000.0, 'web', 'requests_by_code', 12, '{"code": "404"}')
"""
import json
import os
import sqlite3
import time

DB_PATH = os.getenv("DB_PATH", "/data/metrics.db")
RETENCAO_SEGUNDOS = 24 * 3600  # guardamos 24 h para o banco nao crescer sem limite


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")  # leitura (API) nao bloqueia escrita (coletores)
        c.execute(
            """CREATE TABLE IF NOT EXISTS metrics (
                   ts      REAL NOT NULL,
                   service TEXT NOT NULL,
                   metric  TEXT NOT NULL,
                   value   REAL NOT NULL,
                   labels  TEXT NOT NULL DEFAULT ''
               )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_metrics ON metrics (service, metric, ts)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS config_baseline (
                   path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, content TEXT, updated_ts REAL NOT NULL
               )"""
        )
        # Tabela de alertas: 1 linha por INCIDENTE (abertura, mudancas de nivel, resolucao).
        # Esquema antigo (fase 1, vazio) e descartado.
        cols = [r[1] for r in c.execute("PRAGMA table_info(alerts)")]
        if cols and "opened_ts" not in cols:
            c.execute("DROP TABLE alerts")
        c.execute(
            """CREATE TABLE IF NOT EXISTS alerts (
                   id          INTEGER PRIMARY KEY AUTOINCREMENT,
                   rule        TEXT NOT NULL,
                   service     TEXT NOT NULL,
                   metric      TEXT NOT NULL,
                   level       INTEGER NOT NULL,   -- nivel atual (2 amarelo, 3 vermelho)
                   max_level   INTEGER NOT NULL,   -- pior nivel atingido no incidente
                   opened_ts   REAL NOT NULL,
                   updated_ts  REAL NOT NULL,
                   resolved_ts REAL,               -- NULL = incidente ainda ativo
                   value       REAL,
                   threshold   REAL,
                   message     TEXT NOT NULL,
                   events      TEXT NOT NULL       -- JSON: [{ts, level, value}, ...]
               )"""
        )


def insert_rows(ts: float, rows: list[tuple[str, str, float, dict | None]]) -> None:
    """rows: lista de (service, metric, value, labels)."""
    dados = [
        (ts, s, m, float(v), json.dumps(l, sort_keys=True) if l else "")
        for s, m, v, l in rows
    ]
    with _conn() as c:
        c.executemany("INSERT INTO metrics VALUES (?,?,?,?,?)", dados)
        c.execute("DELETE FROM metrics WHERE ts < ?", (time.time() - RETENCAO_SEGUNDOS,))


def _linha(r: sqlite3.Row) -> dict:
    return {
        "ts": r["ts"],
        "service": r["service"],
        "metric": r["metric"],
        "value": r["value"],
        "labels": json.loads(r["labels"]) if r["labels"] else None,
    }


def query_metrics(service, metric, since_ts, limit) -> list[dict]:
    sql = "SELECT * FROM metrics WHERE ts >= ?"
    args: list = [since_ts]
    if service:
        sql += " AND service = ?"
        args.append(service)
    if metric:
        sql += " AND metric = ?"
        args.append(metric)
    sql += " ORDER BY ts ASC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        return [_linha(r) for r in c.execute(sql, args)]


def latest(janela_s: int = 60) -> list[dict]:
    """Ultimo valor de cada (service, metric, labels) dentro da janela."""
    sql = """SELECT m.* FROM metrics m
             JOIN (SELECT service, metric, labels, MAX(ts) AS mts FROM metrics
                   WHERE ts >= ? GROUP BY service, metric, labels) x
               ON m.service = x.service AND m.metric = x.metric
              AND m.labels = x.labels AND m.ts = x.mts"""
    with _conn() as c:
        return [_linha(r) for r in c.execute(sql, (time.time() - janela_s,))]


def values(service: str, metric: str, since_ts: float) -> list[float]:
    """Valores de uma metrica (sem labels) desde since_ts, em ordem cronologica."""
    with _conn() as c:
        rows = c.execute(
            "SELECT value FROM metrics WHERE service=? AND metric=? AND labels='' AND ts>=? ORDER BY ts",
            (service, metric, since_ts),
        )
        return [r[0] for r in rows]


def first_value(service: str, metric: str, since_ts: float):
    """Leitura mais antiga desde since_ts: (ts, valor) ou None."""
    with _conn() as c:
        r = c.execute(
            "SELECT ts, value FROM metrics WHERE service=? AND metric=? AND ts>=? ORDER BY ts LIMIT 1",
            (service, metric, since_ts),
        ).fetchone()
        return (r[0], r[1]) if r else None


# ---- Alertas ----
def alert_open(rule, service, metric, level, ts, value, threshold, message) -> int:
    ev = json.dumps([{"ts": ts, "level": level, "value": value}])
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO alerts (rule, service, metric, level, max_level, opened_ts, updated_ts,
                                   value, threshold, message, events)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (rule, service, metric, level, level, ts, ts, value, threshold, message, ev),
        )
        return cur.lastrowid


def alert_update(alert_id, level, ts, value, threshold, message, resolved: bool = False) -> None:
    with _conn() as c:
        row = c.execute("SELECT max_level, events FROM alerts WHERE id=?", (alert_id,)).fetchone()
        eventos = json.loads(row["events"]) + [{"ts": ts, "level": level, "value": value}]
        c.execute(
            """UPDATE alerts SET level=?, max_level=?, updated_ts=?, value=?, threshold=?, message=?,
                                 resolved_ts=?, events=? WHERE id=?""",
            (level, max(level, row["max_level"]), ts, value, threshold, message,
             ts if resolved else None, json.dumps(eventos), alert_id),
        )


def list_alerts(limit=100, service=None, level=None, active=None) -> list[dict]:
    sql, args = "SELECT * FROM alerts WHERE 1=1", []
    if service:
        sql += " AND service=?"; args.append(service)
    if level:
        sql += " AND max_level=?"; args.append(level)
    if active is not None:
        sql += " AND resolved_ts IS NULL" if active else " AND resolved_ts IS NOT NULL"
    sql += " ORDER BY opened_ts DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        out = []
        for r in c.execute(sql, args):
            d = dict(r)
            d["events"] = json.loads(d["events"])
            out.append(d)
        return out


# ---- Baseline de configuracao (hash SHA-256 por arquivo) ----
def config_baseline_get() -> dict:
    with _conn() as c:
        return {r["path"]: {"sha": r["sha256"], "conteudo": r["content"], "ts": r["updated_ts"]}
                for r in c.execute("SELECT * FROM config_baseline")}


def config_baseline_set(arquivos: dict, substituir: bool = False) -> None:
    """arquivos: {caminho: {sha, conteudo}}. substituir=True apaga a baseline anterior."""
    with _conn() as c:
        if substituir:
            c.execute("DELETE FROM config_baseline")
        c.executemany(
            "INSERT OR REPLACE INTO config_baseline VALUES (?,?,?,?)",
            [(p, v["sha"], v["conteudo"], time.time()) for p, v in arquivos.items()],
        )


def count_rows() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
