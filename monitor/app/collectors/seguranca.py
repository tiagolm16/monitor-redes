"""Coletor de seguranca (servico 'security').

Quatro monitoramentos:
1. Anomalia de trafego (DDoS): z-score do RPS contra uma baseline movel + top 5 IPs (do access log JSON).
2. Brute force: falhas de autenticacao por IP e por conta (401 no /admin do nginx e
   "password authentication failed" no log do Postgres) numa janela de 60 s.
3. Alteracao de configuracao: hash SHA-256 dos arquivos de /config contra a baseline.
4. Vulnerabilidades conhecidas: le os JSON gerados pelo Trivy em /trivy.
"""
import asyncio
import json
import os
import re
import statistics
import struct
import time
from collections import Counter, deque

import httpx

from .. import config_watch, storage

NGINX_LOG = os.getenv("NGINX_LOG", "/var/log/nginx-json/access.log")
PG_CONTAINER = os.getenv("PG_CONTAINER", "rd-postgres")
TRIVY_DIR = os.getenv("TRIVY_DIR", "/trivy")

JANELA_BRUTE_S = 60       # falhas contadas nos ultimos 60 s
BASELINE_S = 600          # baseline de RPS: ultimos 10 min
MIN_AMOSTRAS = 24         # precisa de >= 2 min de historico para calcular z-score
Z_ANOMALIA = 3            # acima disto a amostra NAO entra na baseline (nao "contamina" a media)
MAX_CICLOS_ANOMALIA = 60  # se a "anomalia" durar 5 min, vira o novo normal
SEVERIDADES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

# "2026-11-23 20:07:04.123 UTC [88] user@db 172.28.77.21 FATAL:  password authentication failed for user "admin""
RE_PG_FALHA = re.compile(r'(\S+) FATAL:\s+password authentication failed for user "([^"]*)"')


class SegurancaCollector:
    service = "security"

    def __init__(self) -> None:
        self.log_pos: int | None = None
        self.ultimo_ciclo = time.monotonic()
        self.janela: deque = deque()   # (instante, Counter ips, Counter falhas(fonte, ip, conta))
        self.suspeitos: dict[str, dict] = {}   # ip -> {primeiro, ultimo, total}
        # baseline de RPS: amostras recentes consideradas "normais"
        self.baseline: deque = deque(maxlen=BASELINE_S // 5)
        self.ciclos_anomalos = 0
        self.docker = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds="/var/run/docker.sock"), timeout=3
        )
        self.pg_ultimo_ts = ""      # ultimo timestamp do Docker ja processado
        self.pg_desde = int(time.time())
        self.vulns: dict[str, dict] = {}
        self._vulns_mtime: dict[str, float] = {}
        # Estado exposto pela API
        self.estado = {"ddos": {}, "brute": {}, "config": [], "top_ips": []}
        # Reaproveita o historico de RPS do SQLite (monitor reiniciado nao perde a baseline)
        for v in storage.values("security", "rps", time.time() - BASELINE_S)[-self.baseline.maxlen:]:
            self.baseline.append(v)

    # ------------------------------------------------------------------ ciclo
    async def collect(self):
        linhas = [("up", 1, None)]
        agora = time.monotonic()
        dt = max(agora - self.ultimo_ciclo, 0.001)
        self.ultimo_ciclo = agora

        ips_ciclo, falhas_ciclo, total_req = self._ler_nginx()
        falhas_ciclo.update(await self._ler_postgres())
        self.janela.append((agora, ips_ciclo, falhas_ciclo))
        while self.janela and agora - self.janela[0][0] > JANELA_BRUTE_S:
            self.janela.popleft()

        linhas += self._trafego(total_req, dt)
        linhas += self._brute_force()
        linhas += await self._config()
        linhas += self._vulnerabilidades()
        return linhas

    # ------------------------------------------------------------------ fontes
    def _ler_nginx(self):
        """Linhas novas do access log: (contagem por IP, falhas 401 em /admin, total de requisicoes)."""
        ips, falhas, total = Counter(), Counter(), 0
        try:
            tamanho = os.path.getsize(NGINX_LOG)
        except OSError:
            return ips, falhas, 0
        if self.log_pos is None or tamanho < self.log_pos:
            primeira = self.log_pos is None
            self.log_pos = tamanho if primeira else 0
            if primeira:
                return ips, falhas, 0
        with open(NGINX_LOG, "rb") as f:
            f.seek(self.log_pos)
            dados = f.read(10_000_000)
        fim = dados.rfind(b"\n")
        if fim < 0:
            return ips, falhas, 0
        self.log_pos += fim + 1
        for linha in dados[: fim + 1].splitlines():
            try:
                reg = json.loads(linha)
            except ValueError:
                continue
            ip = reg.get("remote_addr", "?")
            ips[ip] += 1
            total += 1
            if reg.get("status") == 401 and str(reg.get("uri", "")).startswith("/admin"):
                falhas[("nginx", ip, reg.get("user") or "(sem credencial)")] += 1
        return ips, falhas, total

    async def _ler_postgres(self) -> Counter:
        """Falhas de login no log do container do Postgres, lidas pela API do Docker."""
        falhas: Counter = Counter()
        try:
            r = await self.docker.get(
                f"http://docker/containers/{PG_CONTAINER}/logs",
                params={"stdout": 1, "stderr": 1, "timestamps": 1, "since": self.pg_desde},
            )
        except httpx.HTTPError:
            return falhas
        if r.status_code != 200:
            return falhas
        corpo, i, maior = r.content, 0, self.pg_ultimo_ts
        # Formato do Docker sem TTY: quadros com cabecalho de 8 bytes (tipo, 0, 0, 0, tamanho big-endian)
        while i + 8 <= len(corpo):
            tam = struct.unpack(">I", corpo[i + 4: i + 8])[0]
            texto = corpo[i + 8: i + 8 + tam].decode("utf-8", errors="replace")
            i += 8 + tam
            for linha in texto.splitlines():
                ts, _, resto = linha.partition(" ")
                if ts <= self.pg_ultimo_ts:
                    continue  # ja contada em um ciclo anterior
                maior = max(maior, ts)
                m = RE_PG_FALHA.search(resto)
                if m:
                    falhas[("postgres", m.group(1), m.group(2))] += 1
        self.pg_ultimo_ts = maior
        if maior:
            self.pg_desde = int(time.time()) - 5
        return falhas

    # ------------------------------------------------------------------ 1. trafego / DDoS
    def _trafego(self, total_req: int, dt: float):
        rps = total_req / dt
        linhas = [("rps", rps, None)]
        z = ratio = None
        media = desvio = None
        if len(self.baseline) >= MIN_AMOSTRAS:
            media = statistics.fmean(self.baseline)
            # piso de 0.5 no desvio: evita z-score absurdo quando o trafego historico e quase constante
            desvio = max(statistics.pstdev(self.baseline), 0.5)
            z = (rps - media) / desvio
            ratio = rps / media if media > 0 else 0
            linhas += [("rps_baseline", media, None), ("rps_std", desvio, None),
                       ("rps_zscore", z, None), ("rps_ratio", ratio, None)]
        # Amostra anomala nao entra na baseline; assim um ataque longo nao "ensina" o sistema que e normal
        if z is not None and z > Z_ANOMALIA:
            self.ciclos_anomalos += 1
            if self.ciclos_anomalos >= MAX_CICLOS_ANOMALIA:  # novo patamar persistente
                self.baseline.clear()
                self.baseline.append(rps)
                self.ciclos_anomalos = 0
        else:
            self.ciclos_anomalos = 0
            self.baseline.append(rps)

        por_ip: Counter = Counter()
        for _, ips, _ in self.janela:
            por_ip.update(ips)
        top = por_ip.most_common(5)
        for ip, n in top:
            linhas.append(("top_ip_requests", n, {"ip": ip}))
        self.estado["top_ips"] = [{"ip": ip, "requisicoes": n} for ip, n in top]
        self.estado["ddos"] = {"rps": rps, "baseline": media, "desvio": desvio, "zscore": z, "razao": ratio,
                               "amostras": len(self.baseline)}
        return linhas

    # ------------------------------------------------------------------ 2. brute force
    def _brute_force(self):
        por_ip: Counter = Counter()
        por_conta: Counter = Counter()
        por_ip_fonte: Counter = Counter()
        por_conta_fonte: Counter = Counter()
        for _, _, falhas in self.janela:
            for (fonte, ip, conta), n in falhas.items():
                por_ip[ip] += n
                por_conta[conta] += n
                por_ip_fonte[(ip, fonte)] += n
                por_conta_fonte[(conta, fonte)] += n
        agora = time.time()
        for ip, n in por_ip.items():
            s = self.suspeitos.setdefault(ip, {"primeiro": agora, "ultimo": agora, "total": 0})
            s["ultimo"] = agora
            s["total"] = max(s["total"], n)
        for ip in [i for i, s in self.suspeitos.items() if agora - s["ultimo"] > 900]:
            del self.suspeitos[ip]  # esquece IPs quietos ha 15 min

        linhas = [
            ("auth_failures_total", sum(por_ip.values()), None),
            ("max_auth_failures_per_ip", max(por_ip.values(), default=0), None),
            ("max_auth_failures_per_account", max(por_conta.values(), default=0), None),
        ]
        for (ip, fonte), n in por_ip_fonte.items():
            linhas.append(("auth_failures_by_ip", n, {"ip": ip, "source": fonte}))
        for (conta, fonte), n in por_conta_fonte.items():
            linhas.append(("auth_failures_by_account", n, {"account": conta, "source": fonte}))

        fontes_ip: dict[str, set] = {}
        for (ip, fonte) in por_ip_fonte:
            fontes_ip.setdefault(ip, set()).add(fonte)
        self.estado["brute"] = {
            "janela_s": JANELA_BRUTE_S,
            "ips": sorted(
                [{"ip": ip, "falhas": n, "fontes": sorted(fontes_ip[ip]),
                  "primeiro_visto": self.suspeitos[ip]["primeiro"], "ultimo_visto": self.suspeitos[ip]["ultimo"]}
                 for ip, n in por_ip.items()],
                key=lambda x: -x["falhas"]),
            "contas": sorted([{"conta": c, "falhas": n} for c, n in por_conta.items()], key=lambda x: -x["falhas"]),
        }
        return linhas

    # ------------------------------------------------------------------ 3. configuracao
    async def _config(self):
        arquivos = await asyncio.to_thread(config_watch.comparar)
        self.estado["config"] = arquivos
        alterados = sum(1 for a in arquivos if a["status"] != "ok")
        return [("config_changed_files", alterados, None), ("config_files_total", len(arquivos), None)]

    # ------------------------------------------------------------------ 4. vulnerabilidades
    def _vulnerabilidades(self):
        linhas = []
        total_critico = 0
        for svc in ("web", "db", "dns", "smtp"):
            caminho = os.path.join(TRIVY_DIR, f"{svc}.json")
            try:
                mtime = os.path.getmtime(caminho)
            except OSError:
                continue
            if self._vulns_mtime.get(svc) != mtime:  # so le o arquivo de novo se ele mudou
                try:
                    self.vulns[svc] = self._parse_trivy(caminho, mtime)
                    self._vulns_mtime[svc] = mtime
                except (OSError, ValueError):
                    continue
            info = self.vulns.get(svc)
            if not info:
                continue
            total_critico += info["contagem"]["CRITICAL"]
            for sev, n in info["contagem"].items():
                linhas.append(("vulns", n, {"service": svc, "severity": sev}))
        if self.vulns:
            linhas.append(("vulns_critical_total", total_critico, None))
        return linhas

    @staticmethod
    def _parse_trivy(caminho: str, mtime: float) -> dict:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
        vistos, lista = set(), []
        for res in dados.get("Results") or []:
            for v in res.get("Vulnerabilities") or []:
                chave = (v.get("VulnerabilityID"), v.get("PkgName"), v.get("InstalledVersion"))
                if chave in vistos:
                    continue
                vistos.add(chave)
                nota = max((c.get("V3Score", 0) or 0 for c in (v.get("CVSS") or {}).values()), default=0)
                lista.append({
                    "id": v.get("VulnerabilityID"), "pacote": v.get("PkgName"), "versao": v.get("InstalledVersion"),
                    "corrigida": v.get("FixedVersion") or "", "severidade": v.get("Severity", "UNKNOWN"),
                    "cvss": nota, "titulo": (v.get("Title") or "")[:110], "url": v.get("PrimaryURL") or "",
                })
        contagem = {s: sum(1 for v in lista if v["severidade"] == s) for s in SEVERIDADES}
        lista.sort(key=lambda v: (SEVERIDADES.index(v["severidade"]) if v["severidade"] in SEVERIDADES else 9,
                                  -v["cvss"], v["id"] or ""))
        return {"imagem": dados.get("ArtifactName"), "scan_ts": mtime, "contagem": contagem,
                "total": len(lista), "principais": lista[:10]}

    # ------------------------------------------------------------------ detalhes para o e-mail
    def detalhe_alerta(self, regra_id: str) -> str:
        """Texto extra anexado ao e-mail do alerta (quem atacou, qual arquivo mudou...)."""
        if regra_id.startswith("sec_ddos"):
            linhas = [f"  {t['ip']}: {t['requisicoes']} requisicoes nos ultimos 60 s" for t in self.estado["top_ips"]]
            return "Top 5 IPs por volume:\n" + "\n".join(linhas)
        if regra_id == "sec_bruteforce_ip":
            linhas = [f"  {i['ip']}: {i['falhas']} falhas em {self.estado['brute']['janela_s']} s ({', '.join(i['fontes'])})"
                      for i in self.estado["brute"].get("ips", [])[:5]]
            return "IPs com mais falhas de autenticacao:\n" + "\n".join(linhas)
        if regra_id == "sec_config":
            partes = []
            for a in self.estado["config"]:
                if a["status"] == "ok":
                    continue
                partes.append(f"Arquivo: {a['arquivo']} ({a['status']})\n  hash antigo: {a['hash_baseline']}\n"
                              f"  hash novo:   {a['hash_atual']}\n{a['diff']}")
            return "\n\n".join(partes)
        if regra_id == "sec_vuln_critical":
            partes = [f"{svc}: {i['contagem']['CRITICAL']} CRITICAL ({i['imagem']})"
                      for svc, i in self.vulns.items() if i["contagem"]["CRITICAL"]]
            return "\n".join(partes)
        return ""
