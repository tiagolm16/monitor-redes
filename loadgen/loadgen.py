"""Gerador de trafego realista. Modo escolhido por LOAD_MODE (normal | pico | bruteforce).

Fase 1: so o modo 'normal'. Cada protocolo roda em seu proprio loop assincrono.
"""
import asyncio
import os
import random
from email.message import EmailMessage

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

# Pausa media (s) entre acoes de cada protocolo. Menor = mais trafego.
PERFIS = {
    "normal": {"http": 0.2, "pg": 0.4, "dns": 0.3, "smtp": 8.0},
}


async def http_loop(pausa):
    # (caminho, peso): 85% sucesso, 10% 404, 3% 500, 2% /admin sem senha (401)
    caminhos = [("/", 50), ("/index.html", 20), ("/sobre.html", 15),
                ("/nao-existe", 10), ("/erro500", 3), ("/admin", 2)]
    rotas, pesos = zip(*caminhos)
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            try:
                await client.get(WEB_URL + random.choices(rotas, pesos)[0])
            except httpx.HTTPError:
                pass
            await asyncio.sleep(random.expovariate(1 / pausa))


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
                elif sorteio < 0.98:  # query LENTA (acima de 200 ms) de proposito
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
        # 85% nomes que existem; 15% nomes inexistentes (resposta NXDOMAIN)
        nome = random.choice(validos) if random.random() < 0.85 else f"nada{random.randint(1, 999)}.lab.local"
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
    if MODO not in PERFIS:
        print(f"[loadgen] modo '{MODO}' ainda nao implementado, usando 'normal'", flush=True)
    perfil = PERFIS.get(MODO, PERFIS["normal"])
    print(f"[loadgen] iniciando no modo {MODO if MODO in PERFIS else 'normal'}: {perfil}", flush=True)
    await asyncio.gather(
        http_loop(perfil["http"]), pg_loop(perfil["pg"]),
        dns_loop(perfil["dns"]), smtp_loop(perfil["smtp"]),
    )


asyncio.run(main())
