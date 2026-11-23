"""Coletor do DNS (CoreDNS).

- Sonda: o proprio monitor faz uma consulta DNS real (UDP porta 53) e mede o tempo.
- Metricas do servidor: le http://coredns:9153/metrics (formato Prometheus) para QPS e taxa de falha.
"""
import os
import time

import dns.asyncresolver
import dns.exception
import httpx

from ..util import Janela, Taxas, parse_prometheus

DNS_SERVER = os.getenv("DNS_SERVER", "172.28.77.12")
DNS_METRICS_URL = os.getenv("DNS_METRICS_URL", "http://coredns:9153/metrics")
NOME_TESTE = "web.lab.local"


class DnsCollector:
    service = "dns"

    def __init__(self) -> None:
        # configure=False: ignora o /etc/resolv.conf e fala so com o nosso CoreDNS
        self.resolver = dns.asyncresolver.Resolver(configure=False)
        self.resolver.nameservers = [DNS_SERVER]
        self.resolver.lifetime = 2  # tempo maximo total da consulta
        self.http = httpx.AsyncClient(timeout=3)
        self.taxas = Taxas()
        self.janela = Janela(30)  # taxas calculadas sobre os ultimos 30 s

    async def collect(self):
        linhas = []

        # Consulta tipo A por UDP (o dnspython so cai para TCP se a resposta vier truncada)
        falha_sonda = 0  # timeout ou erro na nossa consulta tambem conta como falha do servidor
        inicio = time.perf_counter()
        try:
            await self.resolver.resolve(NOME_TESTE, "A")
            linhas.append(("up", 1, None))
            linhas.append(("resolve_ms", (time.perf_counter() - inicio) * 1000, None))
        except dns.exception.DNSException:
            falha_sonda = 1
            linhas.append(("up", 0, None))

        # Metricas do proprio CoreDNS: contadores acumulados de consultas e respostas por rcode
        try:
            texto = (await self.http.get(DNS_METRICS_URL)).text
        except httpx.HTTPError:
            self.janela.add(falha_sonda=falha_sonda)
            return linhas
        total_consultas = 0.0
        respostas: dict[str, float] = {}
        for nome, labels, valor in parse_prometheus(texto):
            if nome == "coredns_dns_requests_total":
                total_consultas += valor
            elif nome == "coredns_dns_responses_total":
                rcode = labels.get("rcode", "?")
                respostas[rcode] = respostas.get(rcode, 0) + valor

        qps = self.taxas.por_segundo("consultas", total_consultas)
        if qps is not None:
            linhas.append(("qps", qps, None))

        # Duas taxas diferentes (soma dos ultimos 30 s):
        # - nxdomain_rate: "o nome nao existe". Resposta VALIDA, erro do cliente (nome digitado errado).
        # - failure_rate: SERVFAIL, REFUSED, etc. + timeouts da sonda. Falha do SERVIDOR: so ela gera alerta.
        total_resp = nxdomain = falhas_servidor = 0.0
        for rcode, valor in respostas.items():
            d = self.taxas.delta("rcode_" + rcode, valor)
            if d is None:
                continue
            total_resp += d[0]
            if rcode == "NXDOMAIN":
                nxdomain += d[0]
            elif rcode != "NOERROR":
                falhas_servidor += d[0]
            linhas.append(("responses_by_rcode", d[0], {"rcode": rcode}))
        self.janela.add(total=total_resp, nx=nxdomain, falhas=falhas_servidor, falha_sonda=falha_sonda)
        t = self.janela.soma("total")
        f = self.janela.soma("falhas") + self.janela.soma("falha_sonda")
        linhas.append(("nxdomain_rate", 100 * self.janela.soma("nx") / t if t else 0, None))
        linhas.append(("failure_rate", 100 * f / (t + self.janela.soma("falha_sonda")) if t + f else 0, None))
        return linhas
