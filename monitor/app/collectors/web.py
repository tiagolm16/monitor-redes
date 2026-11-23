"""Coletor do Web Server (nginx).

Tres fontes de dados:
1. Um HTTP check (GET /): mede disponibilidade e latencia como um usuario veria.
2. stub_status: pagina de texto do nginx com conexoes ativas e total de requisicoes.
3. Access log JSON (volume compartilhado): conta quantas respostas por codigo HTTP.
"""
import json
import os
import re
import time

import httpx

from ..util import Taxas

WEB_URL = os.getenv("WEB_URL", "http://nginx")
NGINX_LOG = os.getenv("NGINX_LOG", "/var/log/nginx-json/access.log")


class WebCollector:
    service = "web"

    def __init__(self) -> None:
        # max_keepalive_connections=0: cada checagem abre uma conexao TCP nova (SYN, SYN-ACK, ACK),
        # entao a latencia medida inclui o handshake, como para um cliente novo.
        self.client = httpx.AsyncClient(
            timeout=3, limits=httpx.Limits(max_keepalive_connections=0)
        )
        self.taxas = Taxas()
        self.log_pos: int | None = None  # ate onde ja lemos o arquivo de log
        self.codigos_vistos: set[str] = set()

    async def collect(self):
        linhas = []

        # 1) HTTP check (camada de aplicacao, TCP porta 80)
        inicio = time.perf_counter()
        try:
            r = await self.client.get(WEB_URL + "/")
            linhas.append(("latency_ms", (time.perf_counter() - inicio) * 1000, None))
            linhas.append(("up", 1 if r.status_code < 500 else 0, None))
        except httpx.HTTPError:
            linhas.append(("up", 0, None))

        # 2) stub_status. Exemplo da resposta:
        #    Active connections: 3
        #    server accepts handled requests
        #     120 120 340
        #    Reading: 0 Writing: 1 Waiting: 2
        try:
            texto = (await self.client.get(WEB_URL + "/nginx_status")).text
            ativas = int(re.search(r"Active connections:\s*(\d+)", texto).group(1))
            total_req = int(texto.splitlines()[2].split()[2])
            linhas.append(("active_connections", ativas, None))
            rps = self.taxas.por_segundo("requests", total_req)
            if rps is not None:
                linhas.append(("rps", rps, None))
        except (httpx.HTTPError, AttributeError, IndexError, ValueError):
            pass

        # 3) Access log: contagem por codigo na janela desde a ultima leitura
        linhas += self._ler_log()
        return linhas

    def _ler_log(self):
        try:
            tamanho = os.path.getsize(NGINX_LOG)
        except OSError:
            return []
        if self.log_pos is None or tamanho < self.log_pos:  # 1a vez ou log rotacionado
            self.log_pos = tamanho if self.log_pos is None else 0
            if self.log_pos == tamanho:
                return []
        with open(NGINX_LOG, "rb") as f:
            f.seek(self.log_pos)
            dados = f.read(5_000_000)
        fim = dados.rfind(b"\n")  # ignora linha incompleta no final
        if fim < 0:
            return []  # (sem linhas novas: nao emite nada neste ciclo)
        self.log_pos += fim + 1

        por_codigo: dict[str, int] = {}
        soma_tempo = 0.0
        total = 0
        for linha in dados[: fim + 1].splitlines():
            try:
                reg = json.loads(linha)
            except ValueError:
                continue
            codigo = str(reg.get("status"))
            por_codigo[codigo] = por_codigo.get(codigo, 0) + 1
            soma_tempo += float(reg.get("request_time", 0))
            total += 1

        # Codigos ja vistos antes e ausentes agora entram com 0: sem isso o grafico
        # mostraria o ultimo valor antigo em vez de "nenhuma resposta 404 neste intervalo".
        self.codigos_vistos |= set(por_codigo)
        saida = [("requests_by_code", por_codigo.get(c, 0), {"code": c})
                 for c in sorted(self.codigos_vistos)]
        erros_4xx = sum(n for c, n in por_codigo.items() if c.startswith("4"))
        erros_5xx = sum(n for c, n in por_codigo.items() if c.startswith("5"))
        saida.append(("error_rate_4xx", 100 * erros_4xx / total if total else 0, None))
        saida.append(("error_rate_5xx", 100 * erros_5xx / total if total else 0, None))
        if total:
            saida.append(("log_latency_ms", 1000 * soma_tempo / total, None))
        return saida
