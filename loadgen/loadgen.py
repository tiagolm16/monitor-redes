"""Gerador de trafego realista com 3 modos: normal | pico (DDoS) | bruteforce.

O modo inicial vem de LOAD_MODE e pode ser trocado AO VIVO, sem rebuild, por uma API interna:
    GET  http://localhost:8090/mode          -> modo atual
    POST http://localhost:8090/mode/pico     -> troca para pico (ou normal, bruteforce)
"""
import asyncio
import base64
import json
import os
import random
import threading
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer

import aiosmtplib
import asyncpg
import dns.asyncresolver
import dns.exception
import httpx

MODO = os.getenv("LOAD_MODE", "normal")
WEB_URL = os.getenv("WEB_URL", "http://nginx")
PG_DSN = os.getenv("PG_DSN", "postgresql://app:app123@postgres:5432/appdb")
DNS_SERVER = os.getenv("DNS_SERVER", "172.28.77.12")
SMTP_HOST = os.getenv("SMTP_HOST", "mailpit")

# Pausa media (s) entre acoes do trafego LEGITIMO. Os ataques sao tarefas extras (mais abaixo).
PERFIL = {"http": 0.2, "pg": 0.4, "dns": 0.3, "smtp": 8.0}
MODOS = ("normal", "pico", "bruteforce")
estado = {"modo": MODO if MODO in MODOS else "normal"}

# IPs ficticios, nas faixas reservadas para documentacao (RFC 5737): nunca existem na internet real.
# O loadgen "finge" ser esses IPs enviando o header X-Forwarded-For; o nginx (real_ip) confia nele
# porque a requisicao vem da rede interna do Docker.
CLIENTES_NORMAIS = [f"198.51.100.{n}" for n in range(10, 22)]   # 12 usuarios comuns
ATACANTES_DDOS = ["203.0.113.7", "203.0.113.8", "203.0.113.9"]   # 3 origens do pico
ATACANTES_BRUTE = ["203.0.113.50", "203.0.113.51"]               # 2 origens do brute force


async def http_loop(pausa):
    """Trafego legitimo, sempre ligado em qualquer modo, vindo de 12 IPs diferentes."""
    # (caminho, peso em %): ~94% sucesso, 4% 404, 0,6% 500, 0,4% /admin sem senha (401)
    caminhos = [("/", 50), ("/index.html", 25), ("/sobre.html", 19),
                ("/nao-existe", 4), ("/erro500", 0.6), ("/admin", 0.4)]
    rotas, pesos = zip(*caminhos)
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            try:
                await client.get(WEB_URL + random.choices(rotas, pesos)[0],
                                 headers={"X-Forwarded-For": random.choice(CLIENTES_NORMAIS)})
            except httpx.HTTPError:
                pass
            await asyncio.sleep(random.expovariate(1 / pausa))


async def ddos_worker(ip):
    """Modo pico: rajada de GET / (~25 req/s por tarefa; 6 tarefas = ~150 req/s) de poucos IPs."""
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            if estado["modo"] != "pico":
                await asyncio.sleep(0.5)
                continue
            try:
                await client.get(WEB_URL + "/", headers={"X-Forwarded-For": ip})
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.02)


async def brute_http_worker(ip):
    """Modo bruteforce: senhas erradas em /admin (HTTP Basic Auth), ~5 tentativas/s por IP."""
    senhas = ["123456", "password", "admin", "qwerty", "letmein", "senha123", "admin123x", "root"]
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            if estado["modo"] != "bruteforce":
                await asyncio.sleep(0.5)
                continue
            cred = base64.b64encode(f"admin:{random.choice(senhas)}".encode()).decode()
            try:
                await client.get(WEB_URL + "/admin/",
                                 headers={"X-Forwarded-For": ip, "Authorization": f"Basic {cred}"})
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)


async def brute_pg_worker():
    """Modo bruteforce: logins com senha errada no Postgres (gera 'password authentication failed' no log)."""
    while True:
        if estado["modo"] != "bruteforce":
            await asyncio.sleep(0.5)
            continue
        usuario = random.choice(["admin", "postgres", "root", "app"])
        try:
            c = await asyncpg.connect(host="postgres", user=usuario, password=f"errada{random.randint(1, 99)}",
                                      database="appdb", timeout=3)
            await c.close()
        except (asyncpg.PostgresError, OSError):
            pass
        await asyncio.sleep(0.4)


def servidor_controle():
    """API minima de controle (porta 8090) para trocar o modo ao vivo."""
    class Handler(BaseHTTPRequestHandler):
        def _resp(self, codigo, corpo):
            dados = json.dumps(corpo).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):
            self._resp(200, {"modo": estado["modo"], "modos": MODOS})

        def do_POST(self):
            modo = self.path.rstrip("/").split("/")[-1]
            if self.path.startswith("/mode/") and modo in MODOS:
                estado["modo"] = modo
                print(f"[loadgen] modo alterado para {modo}", flush=True)
                self._resp(200, {"modo": modo})
            else:
                self._resp(400, {"erro": "use POST /mode/normal|pico|bruteforce"})

        def log_message(self, *a):  # silencia o log de cada requisicao
            pass

    HTTPServer(("0.0.0.0", 8090), Handler).serve_forever()


async def pg_loop(pausa):
    while True:
        try:
            pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=3)
            break
        except OSError:
            await asyncio.sleep(2)
    while True:
        try:
            sorteio = random.random()
            async with pool.acquire() as c:
                if sorteio < 0.55:    # leitura
                    await c.fetch("SELECT * FROM pedidos WHERE cliente = $1 LIMIT 20",
                                  f"cliente{random.randint(0, 49)}")
                elif sorteio < 0.85:  # escrita
                    await c.execute("INSERT INTO pedidos (cliente, valor) VALUES ($1, $2)",
                                    f"cliente{random.randint(0, 49)}", round(random.uniform(5, 500), 2))
                elif sorteio < 0.95:  # agregacao
                    await c.fetch("SELECT cliente, SUM(valor) FROM pedidos GROUP BY cliente")
                elif sorteio < 0.965:  # query LENTA (acima de 200 ms) de proposito, ~1,5%
                    await c.execute("SELECT pg_sleep(0.35)")
                else:                 # erro dentro de transacao -> ROLLBACK
                    async with c.transaction():
                        await c.execute("SELECT 1/0")
        except (asyncpg.PostgresError, OSError):
            pass
        await asyncio.sleep(random.expovariate(1 / pausa))


async def dns_loop(pausa):
    r = dns.asyncresolver.Resolver(configure=False)
    r.nameservers = [DNS_SERVER]
    r.lifetime = 2
    validos = ["web.lab.local", "db.lab.local", "mail.lab.local", "www.lab.local", "ns1.lab.local"]
    while True:
        # 96% nomes que existem; 4% inexistentes (resposta NXDOMAIN)
        nome = random.choice(validos) if random.random() < 0.96 else f"nada{random.randint(1, 999)}.lab.local"
        try:
            await r.resolve(nome, "A")
        except dns.exception.DNSException:
            pass
        await asyncio.sleep(random.expovariate(1 / pausa))


async def smtp_loop(pausa):
    n = 0
    while True:
        n += 1
        msg = EmailMessage()
        msg["From"] = "app@lab.local"
        msg["To"] = f"cliente{random.randint(1, 50)}@lab.local"
        msg["Subject"] = f"Pedido #{n} confirmado"
        msg.set_content("Obrigado pela compra.")
        try:
            await aiosmtplib.send(msg, hostname=SMTP_HOST, port=1025, timeout=5)
        except (aiosmtplib.SMTPException, OSError):
            pass
        await asyncio.sleep(random.expovariate(1 / pausa))


async def main():
    threading.Thread(target=servidor_controle, daemon=True).start()
    print(f"[loadgen] iniciando no modo {estado['modo']}. Troque ao vivo: POST :8090/mode/<modo>", flush=True)
    await asyncio.gather(
        http_loop(PERFIL["http"]), pg_loop(PERFIL["pg"]),
        dns_loop(PERFIL["dns"]), smtp_loop(PERFIL["smtp"]),
        *[ddos_worker(ATACANTES_DDOS[i % 3]) for i in range(6)],
        *[brute_http_worker(ip) for ip in ATACANTES_BRUTE],
        brute_pg_worker(),
    )


asyncio.run(main())
