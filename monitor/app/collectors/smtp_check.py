"""Coletor do SMTP (Mailpit).

Funcionamento:
- A cada ciclo o coletor poe 1 e-mail sintetico numa FILA interna (asyncio.Queue).
- Uma tarefa de fundo (worker) tira da fila e envia via SMTP (TCP 1025), medindo a latencia.
- Depois do envio, pergunta a API do Mailpit se o e-mail realmente chegou (confirmacao de entrega).
- Se o Mailpit cair, o worker falha e a fila cresce: o tamanho da fila vira uma metrica.
"""
import asyncio
import os
import time
import uuid
from collections import deque
from email.message import EmailMessage

import aiosmtplib
import httpx

from ..util import Taxas

# Sondas SEMPRE vao para o Mailpit (SMTP_HOST/SMTP_PORT ficam livres para o envio de alertas)
SMTP_HOST = os.getenv("MAILPIT_HOST", "mailpit")
SMTP_PORT = 1025
MAILPIT_API = os.getenv("MAILPIT_API", "http://mailpit:8025")
JANELA_S = 60  # taxas de entrega/erro sao calculadas sobre o ultimo minuto


class SmtpCollector:
    service = "smtp"

    def __init__(self) -> None:
        self.fila: asyncio.Queue = asyncio.Queue()
        # resultados recentes: (instante, enviou_ok, entregue_confirmado, latencia_ms)
        self.resultados: deque = deque()
        self.worker: asyncio.Task | None = None
        self.http = httpx.AsyncClient(timeout=3)
        self.taxas = Taxas()
        self.enviados_ciclo = 0

    async def collect(self):
        if self.worker is None:
            self.worker = asyncio.create_task(self._worker())
        # Fila medida ANTES de enfileirar a sonda nova: so passa de 0 se o worker estiver atrasado
        linhas = [("queue_size", self.fila.qsize(), None)]
        self.fila.put_nowait(f"sonda-{uuid.uuid4().hex[:12]}")

        # Disponibilidade: abre TCP na 1025 e le o banner "220 ..." que todo servidor SMTP envia
        try:
            leitor, escritor = await asyncio.wait_for(
                asyncio.open_connection(SMTP_HOST, SMTP_PORT), 2
            )
            banner = await asyncio.wait_for(leitor.readline(), 2)
            escritor.write(b"QUIT\r\n")
            escritor.close()
            linhas.append(("up", 1 if banner.startswith(b"220") else 0, None))
        except (OSError, asyncio.TimeoutError):
            linhas.append(("up", 0, None))

        # Estatisticas do ultimo minuto
        corte = time.time() - JANELA_S
        while self.resultados and self.resultados[0][0] < corte:
            self.resultados.popleft()
        total = len(self.resultados)
        if total:
            ok = sum(1 for r in self.resultados if r[1])
            entregues = sum(1 for r in self.resultados if r[2])
            lat = [r[3] for r in self.resultados if r[1]]
            linhas.append(("delivery_rate", 100 * entregues / total, None))
            linhas.append(("error_rate", 100 * (total - ok) / total, None))
            if lat:
                linhas.append(("send_latency_ms", sum(lat) / len(lat), None))

        # Volume por minuto: variacao do total de e-mails guardados no Mailpit (loadgen) + sondas
        try:
            r = await self.http.get(f"{MAILPIT_API}/api/v1/messages", params={"limit": 1})
            d = self.taxas.delta("mailpit_total", r.json()["total"])
            if d is not None:
                novos = d[0] + self.enviados_ciclo
                linhas.append(("volume_per_min", novos / d[1] * 60, None))
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        self.enviados_ciclo = 0
        return linhas

    async def _worker(self):
        while True:
            assunto = await self.fila.get()
            inicio = time.perf_counter()
            enviou = entregue = False
            try:
                msg = EmailMessage()
                msg["From"] = "monitor@lab.local"
                msg["To"] = "sonda@lab.local"
                msg["Subject"] = assunto
                msg.set_content("e-mail sintetico de monitoramento")
                await aiosmtplib.send(msg, hostname=SMTP_HOST, port=SMTP_PORT, timeout=5)
                enviou = True
                self.enviados_ciclo += 1
                latencia = (time.perf_counter() - inicio) * 1000
                entregue = await self._confirmar_e_apagar(assunto)
            except (aiosmtplib.SMTPException, OSError, asyncio.TimeoutError):
                latencia = (time.perf_counter() - inicio) * 1000
                await asyncio.sleep(1)  # nao martelar um servidor que caiu
            self.resultados.append((time.time(), enviou, entregue, latencia))

    async def _confirmar_e_apagar(self, assunto: str) -> bool:
        """Pergunta ao Mailpit se a sonda chegou; se sim, apaga para nao poluir a caixa."""
        params = {"query": f"subject:{assunto}"}
        try:
            r = await self.http.get(f"{MAILPIT_API}/api/v1/search", params=params)
            achou = r.json().get("messages_count", 0) >= 1
            if achou:
                await self.http.request("DELETE", f"{MAILPIT_API}/api/v1/search", params=params)
            return achou
        except (httpx.HTTPError, ValueError):
            return False
