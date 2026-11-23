"""Motor de alertas: le monitor/alerts.yaml, decide o nivel de cada regra a cada ciclo e envia e-mails.

Niveis: 1 = Verde (ok), 2 = Amarelo (atencao), 3 = Vermelho (critico).
"""
import asyncio
import html
import logging
import math
import os
import statistics
import time
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import aiosmtplib
import yaml

from . import storage

log = logging.getLogger("alertas")
NOMES = {1: "Verde", 2: "Amarelo", 3: "Vermelho"}
AGREGACAO = {"ultimo": "último", "media": "média", "max": "máximo", "soma": "soma", "p95": "p95"}  # nomes para exibir
CORES = {1: "#16a34a", 2: "#ca8a04", 3: "#dc2626"}

# --- Envio de e-mail: por padrao Mailpit (SMTP sem TLS na 1025). Para um SMTP real, defina as
# variaveis de ambiente (veja o README). Nenhuma credencial fica no repositorio.
SMTP_HOST = os.getenv("SMTP_HOST", "mailpit")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_TLS = os.getenv("SMTP_TLS", "none").lower()  # none | starttls | ssl
ALERT_TO = os.getenv("ALERT_TO", "ops@lab.local")
ALERT_FROM = os.getenv("ALERT_FROM", "alertas@lab.local")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8000")
FUSO = ZoneInfo(os.getenv("TZ", "America/Sao_Paulo"))  # horario dos e-mails = horario do painel


class Regra:
    def __init__(self, d: dict):
        self.id = d["id"]
        self.servico = d["servico"]
        self.metrica = d["metrica"]
        self.descricao = d["descricao"]
        self.operador = d["operador"]
        self.amarelo = d.get("amarelo")
        self.vermelho = d.get("vermelho")
        self.agregacao = d.get("agregacao", "ultimo")
        self.janela_s = d.get("janela_s", 20)
        self.unidade = d.get("unidade", "")
        self.ciclos = d.get("ciclos", 3)
        self.ciclos_rec = d.get("ciclos_recuperacao", 3)

    def ruim(self, valor: float, limiar) -> bool:
        return valor > limiar if self.operador == ">" else valor < limiar

    def nivel(self, valor: float) -> int:
        if self.vermelho is not None and self.ruim(valor, self.vermelho):
            return 3
        if self.amarelo is not None and self.ruim(valor, self.amarelo):
            return 2
        return 1

    def limiar(self, nivel: int):
        """Limiar associado a um nivel (para o nivel verde, mostra o ultimo limiar amarelo/vermelho)."""
        if nivel == 3 or (nivel == 1 and self.amarelo is None):
            return self.vermelho
        return self.amarelo


def agregar(valores: list[float], modo: str):
    if not valores:
        return None
    if modo == "media":
        return statistics.fmean(valores)
    if modo == "max":
        return max(valores)
    if modo == "soma":
        return sum(valores)
    if modo == "p95":  # 95% das leituras ficam abaixo deste valor
        ordenados = sorted(valores)
        return ordenados[max(0, math.ceil(0.95 * len(ordenados)) - 1)]
    return valores[-1]  # ultimo


def fmt(v, unidade="") -> str:
    if v is None:
        return "-"
    return f"{v:.0f}{unidade}" if abs(v) >= 100 or float(v).is_integer() else f"{v:.2f}{unidade}"


class Motor:
    def __init__(self, caminho: str):
        with open(caminho, encoding="utf-8") as f:
            self.regras = [Regra(r) for r in yaml.safe_load(f)["regras"]]
        self.estado = {
            r.id: {"nivel": 1, "cand": 1, "cont": 0, "valor": None, "incidente": None}
            for r in self.regras
        }
        self._tarefas: set[asyncio.Task] = set()
        self.provedor_detalhe = None  # funcao(regra_id) -> texto extra para o e-mail (ex.: IPs atacantes)
        # Se o monitor reiniciou com incidente aberto, retoma de onde parou (evita e-mail duplicado)
        for a in storage.list_alerts(500, active=True):
            if a["rule"] in self.estado:
                self.estado[a["rule"]].update(nivel=a["level"], incidente=a["id"])

    # ---------------- avaliacao ----------------
    def _ler_valores(self) -> dict:
        agora = time.time()
        return {
            r.id: agregar(storage.values(r.servico, r.metrica, agora - r.janela_s), r.agregacao)
            for r in self.regras
        }

    async def avaliar(self) -> None:
        valores = await asyncio.to_thread(self._ler_valores)
        agora = time.time()
        for r in self.regras:
            v = valores[r.id]
            if v is None:  # sem dado recente (ex.: coletor do banco falhou): mantem o estado
                continue
            e = self.estado[r.id]
            e["valor"] = v
            bruto = r.nivel(v)  # nivel "de agora", ainda sem histerese
            if bruto == e["nivel"]:
                e["cand"], e["cont"] = bruto, 0
                continue
            # Piorou ou melhorou: so oficializa depois de N leituras seguidas no mesmo novo nivel
            e["cont"] = e["cont"] + 1 if bruto == e["cand"] else 1
            e["cand"] = bruto
            precisa = r.ciclos if bruto > e["nivel"] else r.ciclos_rec
            if e["cont"] >= precisa:
                await self._transicao(r, e, bruto, v, agora)

    async def _transicao(self, r: Regra, e: dict, novo: int, valor: float, ts: float):
        antigo = e["nivel"]
        e["nivel"], e["cand"], e["cont"] = novo, novo, 0
        limiar = r.limiar(novo if novo > 1 else antigo)
        msg = f"{r.descricao}: valor {fmt(valor, r.unidade)} (limiar {r.operador} {fmt(limiar, r.unidade)})"
        inicio = ts
        if antigo == 1:  # abertura de incidente
            e["incidente"] = await asyncio.to_thread(
                storage.alert_open, r.id, r.servico, r.metrica, novo, ts, valor, limiar, msg
            )
        else:
            await asyncio.to_thread(
                storage.alert_update, e["incidente"], novo, ts, valor, limiar, msg, novo == 1
            )
            inicio = next(a["opened_ts"] for a in storage.list_alerts(500) if a["id"] == e["incidente"])
            if novo == 1:
                e["incidente"] = None
        log.info("ALERTA %s: %s -> %s | %s", r.id, NOMES[antigo], NOMES[novo], msg)
        tarefa = asyncio.create_task(self._enviar_email(r, antigo, novo, valor, limiar, ts, inicio))
        self._tarefas.add(tarefa)  # guarda referencia para o asyncio nao descartar a tarefa
        tarefa.add_done_callback(self._tarefas.discard)

    # ---------------- e-mail ----------------
    async def _enviar_email(self, r: Regra, antigo, novo, valor, limiar, ts, inicio):
        if novo == 1:
            tag, titulo = "[RECUPERADO]", "Serviço recuperado"
        elif novo == 3:
            tag, titulo = "[CRÍTICO]", "Alerta crítico"
        else:
            tag, titulo = "[ATENÇÃO]", "Alerta de atenção" if antigo == 1 else "Criticidade reduzida para atenção"
        msg = EmailMessage()
        msg["From"], msg["To"] = ALERT_FROM, ALERT_TO
        msg["Subject"] = f"{tag} {r.servico}: {r.descricao}"
        hora = datetime.fromtimestamp(ts, FUSO).strftime("%d/%m/%Y %H:%M:%S") + " (horário de Brasília)"
        linhas = [
            ("Serviço", r.servico), ("Métrica", f"{r.metrica} ({AGREGACAO.get(r.agregacao, r.agregacao)})"),
            ("Valor atual", fmt(valor, r.unidade)), ("Limiar", f"{r.operador} {fmt(limiar, r.unidade)}"),
            ("Horário", hora),
        ]
        if novo == 1:
            linhas.append(("Duração do incidente", f"{int(ts - inicio)} s"))
        tabela = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{html.escape(k)}</td>"
            f"<td><b>{html.escape(str(v))}</b></td></tr>" for k, v in linhas
        )
        # Detalhe extra (ex.: IPs atacantes, diff do arquivo alterado), fornecido pelo coletor de seguranca
        detalhe = ""
        if self.provedor_detalhe and novo > 1:
            try:
                detalhe = self.provedor_detalhe(r.id)
            except Exception:
                log.exception("erro ao montar detalhe do alerta")
        texto = "\n".join(f"{k}: {v}" for k, v in linhas)
        if detalhe:
            texto += f"\n\n{detalhe}"
        msg.set_content(texto + f"\n\nDashboard: {DASHBOARD_URL}/#/alertas")
        bloco_detalhe = (f"<pre style='background:#f3f4f6;padding:8px;font-size:12px'>{html.escape(detalhe)}</pre>"
                         if detalhe else "")
        msg.add_alternative(
            f"<html><body style='font-family:Arial,sans-serif'>"
            f"<h2 style='color:{CORES[novo]};margin-bottom:4px'>{html.escape(titulo)}: {NOMES[novo]}</h2>"
            f"<p>{html.escape(r.descricao)}</p><table>{tabela}</table>{bloco_detalhe}"
            f"<p><a href='{DASHBOARD_URL}/#/alertas'>Abrir o dashboard</a></p></body></html>",
            subtype="html",
        )
        # Por baixo, o aiosmtplib abre TCP na porta SMTP e executa: EHLO, MAIL FROM, RCPT TO, DATA
        try:
            await aiosmtplib.send(
                msg, hostname=SMTP_HOST, port=SMTP_PORT, timeout=10,
                username=SMTP_USER or None, password=SMTP_PASS or None,
                use_tls=SMTP_TLS == "ssl", start_tls=True if SMTP_TLS == "starttls" else False,
            )
        except (aiosmtplib.SMTPException, OSError, asyncio.TimeoutError) as ex:
            log.warning("falha ao enviar e-mail de alerta: %r", ex)

    # ---------------- consulta (API) ----------------
    def nivel_servicos(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.regras:
            out[r.servico] = max(out.get(r.servico, 1), self.estado[r.id]["nivel"])
        return out

    def listar_regras(self) -> list[dict]:
        return [
            {
                "id": r.id, "servico": r.servico, "metrica": r.metrica, "descricao": r.descricao,
                "operador": r.operador, "amarelo": r.amarelo, "vermelho": r.vermelho,
                "agregacao": r.agregacao, "janela_s": r.janela_s, "unidade": r.unidade,
                "ciclos": r.ciclos, "ciclos_recuperacao": r.ciclos_rec,
                "nivel": self.estado[r.id]["nivel"], "valor": self.estado[r.id]["valor"],
            }
            for r in self.regras
        ]
