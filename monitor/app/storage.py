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
        # Tabela de alertas: sera preenchida na fase de alertas
        c.execute(
            """CREATE TABLE IF NOT EXISTS alerts (
                   id         INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts         REAL NOT NULL,
                   service    TEXT NOT NULL,
                   level      TEXT NOT NULL,
                   rule       TEXT NOT NULL,
                   message    TEXT NOT NULL,
                   resolved_ts REAL
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


def list_alerts(limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


def count_rows() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
