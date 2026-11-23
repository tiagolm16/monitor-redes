"""Cenarios de falha e ataque: derrubam servicos e mudam o modo do loadgen, e conferem dashboard e e-mail."""
import re
import time

import pytest
from playwright.sync_api import expect

from conftest import (BASE, NGINX_CONF, alerta_ativo, alerta_resolvido, api, assuntos_emails, compose, esperar,
                      evidencia, graficos_com_dados, loadgen_modo)


@pytest.fixture(autouse=True)
def restaurar_ao_final():
    yield
    loadgen_modo("normal")
    compose("start", "nginx", "postgres", "coredns", "mailpit")


def _queda(page, container, card, rotulo_regra, nome_evid):
    t0 = time.time()
    try:
        compose("stop", container)
        page.goto(BASE)
        expect(page.locator(f"#card-{card}")).to_have_class(re.compile("nivel3"), timeout=60000)
        evidencia(page, f"{nome_evid}_vermelho")
        page.goto(f"{BASE}/#/alertas")
        expect(page.locator("#ativos")).to_contain_text(rotulo_regra, timeout=20000)
        esperar(lambda: any(s.startswith(f"[CRÍTICO] {card}") for s in assuntos_emails(t0)), 30, descricao="e-mail critico")
    finally:
        compose("start", container)
    page.goto(BASE)
    expect(page.locator(f"#card-{card}")).to_have_class(re.compile("nivel1"), timeout=120000)
    esperar(lambda: any(s.startswith(f"[RECUPERADO] {card}") for s in assuntos_emails(t0)), 30, descricao="e-mail de recuperacao")
    evidencia(page, f"{nome_evid}_recuperado")


def test_T10_queda_postgres(page):
    _queda(page, "postgres", "db", "PostgreSQL fora do ar", "T10_queda_postgres")


def test_T11_queda_nginx(page):
    _queda(page, "nginx", "web", "Web fora do ar", "T11_queda_nginx")


def test_T12_filtros_da_pagina_alertas(page):
    """Usa os incidentes criados pelos testes T10 e T11."""
    page.goto(f"{BASE}/#/alertas")
    page.wait_for_selector("#historico table")
    total = page.locator("#historico tr").count()
    page.select_option("#f-serv", "db")
    linhas = page.locator("#historico tr:not(:first-child)")
    assert linhas.count() >= 1
    for i in range(linhas.count()):
        assert linhas.nth(i).locator("td").nth(1).inner_text() == "db"
    page.select_option("#f-serv", "")
    page.select_option("#f-nivel", "3")
    linhas = page.locator("#historico tr:not(:first-child)")
    assert linhas.count() >= 2
    for i in range(linhas.count()):
        assert "Vermelho" in linhas.nth(i).locator("td").nth(2).inner_text()
    evidencia(page, "T12_filtros_alertas")
    assert total >= 3


def test_T13_ddos_zscore(page):
    t0 = time.time()
    loadgen_modo("pico")
    esperar(lambda: alerta_ativo("sec_ddos", t0), 60, descricao="alerta de anomalia de trafego")
    page.goto(f"{BASE}/#/seguranca")
    graficos_com_dados(page, "main", 3)
    expect(page.locator("#top-ips table")).to_contain_text("203.0.113.", timeout=20000)
    # O alerta amarelo (z > 3) dispara antes do pico "encher" a janela; espera o z-score passar do limiar vermelho
    esperar(lambda: api("/api/security")["ddos"]["zscore"] > 6, 40, descricao="z-score acima de 6")
    esperar(lambda: any("security: Anomalia de tráfego" in s for s in assuntos_emails(t0)), 30, descricao="e-mail de DDoS")
    evidencia(page, "T13_ddos")
    loadgen_modo("normal")
    esperar(lambda: alerta_resolvido("sec_ddos", t0), 120, descricao="alerta de DDoS resolvido")


def test_T14_brute_force(page):
    t0 = time.time()
    loadgen_modo("bruteforce")
    esperar(lambda: alerta_ativo("sec_bruteforce", t0), 60, descricao="alerta de brute force")
    page.goto(f"{BASE}/#/seguranca")
    expect(page.locator("#suspeitos")).to_contain_text("203.0.113.50", timeout=20000)
    expect(page.locator("#suspeitos")).to_contain_text("postgres")          # falhas de login no Postgres
    expect(page.locator("#contas")).to_contain_text("admin")
    esperar(lambda: any("Brute force" in s for s in assuntos_emails(t0)), 30, descricao="e-mail de brute force")
    evidencia(page, "T14_bruteforce")
    loadgen_modo("normal")
    esperar(lambda: alerta_resolvido("sec_bruteforce", t0), 150, descricao="brute force resolvido")


def test_T15_alteracao_de_configuracao(page):
    original = NGINX_CONF.read_bytes()
    t0 = time.time()
    try:
        NGINX_CONF.write_bytes(original + b"\n# alteracao de teste automatizado\n")
        esperar(lambda: alerta_ativo("sec_config", t0), 90, descricao="alerta de config")
        page.goto(f"{BASE}/#/seguranca")
        expect(page.locator("#config")).to_contain_text("ALTERADO", timeout=30000)
        expect(page.locator("#diffs")).to_contain_text("alteracao de teste automatizado")
        cfg = api("/api/security")["config"]["arquivos"]
        alterado = [a for a in cfg if a["status"] != "ok"][0]
        assert alterado["hash_baseline"] != alterado["hash_atual"] and len(alterado["hash_atual"]) == 64
        esperar(lambda: any("Arquivo de configuração alterado" in s for s in assuntos_emails(t0)), 30, descricao="e-mail de config")
        evidencia(page, "T15_config_alterada")
    finally:
        NGINX_CONF.write_bytes(original)
    esperar(lambda: alerta_resolvido("sec_config", t0), 120, descricao="config resolvida apos restaurar")


def test_T16_aceitar_nova_baseline(page):
    original = NGINX_CONF.read_bytes()
    t0 = time.time()
    try:
        NGINX_CONF.write_bytes(original + b"\n# mudanca autorizada\n")
        esperar(lambda: alerta_ativo("sec_config", t0), 90, descricao="alerta de config")
        page.goto(f"{BASE}/#/seguranca")
        page.once("dialog", lambda d: d.accept())
        page.click("#aceitar")
        esperar(lambda: alerta_resolvido("sec_config", t0), 90, descricao="alerta resolvido apos aceitar baseline")
        assert api("/api/security")["config"]["alterados"] == 0
    finally:
        NGINX_CONF.write_bytes(original)
        # Espera o monitor ENXERGAR o arquivo restaurado (o Docker Desktop pode atrasar a propagacao)
        # antes de aceitar; senao a baseline guardaria a versao alterada.
        try:
            esperar(lambda: api("/api/security")["config"]["alterados"] == 1, 120, descricao="monitor ve o arquivo restaurado")
            api("/api/security/config/accept", "POST")     # baseline volta ao arquivo original
        except AssertionError:
            pass   # o teste falhou antes de aceitar: a baseline original ja esta correta
        esperar(lambda: api("/api/security")["config"]["alterados"] == 0, 90, descricao="baseline restaurada")
        esperar(lambda: alerta_resolvido("sec_config", t0), 90, descricao="sem alerta de config no final")


def test_T17_vulnerabilidades(page):
    sec = api("/api/security")
    assert set(sec["vulns"]) == {"web", "db", "dns", "smtp"}, "rode o scan: docker compose --profile scan run --rm trivy"
    for svc, v in sec["vulns"].items():
        assert set(v["contagem"]) == {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
        assert v["total"] > 0 and v["principais"]
        topo = v["principais"][0]
        assert topo["id"] and topo["pacote"] and topo["versao"]
    criticos = sum(v["contagem"]["CRITICAL"] for v in sec["vulns"].values())
    if criticos:
        assert alerta_ativo("sec_vuln_critical"), "havia CRITICAL mas nao ha alerta"
    page.goto(f"{BASE}/#/seguranca")
    expect(page.locator("#vulns .card")).to_have_count(4, timeout=15000)
    evidencia(page, "T17_vulnerabilidades")
