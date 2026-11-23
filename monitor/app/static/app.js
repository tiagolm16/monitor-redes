// Front-end sem framework: roteamento por hash (#/web, #/alertas...), fetch na API a cada 5 s, Chart.js.
"use strict";

const NIVEL = { 1: "Verde", 2: "Amarelo", 3: "Vermelho" };
const SERVICOS = ["web", "db", "dns", "smtp"];
const NOMES = { web: "Web Server (nginx)", db: "Banco de Dados (PostgreSQL)", dns: "DNS (CoreDNS)", smtp: "SMTP (Mailpit)" };
const CORES = ["#38bdf8", "#f97316", "#a78bfa", "#22c55e", "#f43f5e"];
const INTERVALO_MS = 5000;

// Metricas principais no card da Visao Geral: [metrica, rotulo, unidade, casas decimais]
const RESUMO = {
  web: { spark: "rps", kpis: [["rps", "RPS", "/s", 1], ["latency_ms", "Latência", " ms", 0], ["error_rate_5xx", "Erro 5xx", "%", 1]] },
  db: { spark: "qps", kpis: [["qps", "QPS", "/s", 1], ["connections_percent", "Conexões", "%", 0], ["slow_queries", "Slow queries", "", 0]] },
  dns: { spark: "resolve_ms", kpis: [["resolve_ms", "Resolução", " ms", 1], ["qps", "QPS", "/s", 1], ["failure_rate", "Falhas", "%", 1]] },
  smtp: { spark: "send_latency_ms", kpis: [["delivery_rate", "Entrega", "%", 0], ["queue_size", "Fila", "", 0], ["send_latency_ms", "Latência", " ms", 0]] },
};

// Tiles de valor atual no topo da pagina de cada servico: [metrica, rotulo, unidade, decimais, fator]
const TILES = {
  web: [["rps", "RPS", "/s", 1], ["latency_ms", "Latência", " ms", 0], ["error_rate_4xx", "Erro 4xx", "%", 1], ["error_rate_5xx", "Erro 5xx", "%", 1], ["active_connections", "Conexões ativas", "", 0]],
  db: [["qps", "QPS", "/s", 1], ["connections", "Conexões", "", 0], ["cpu_percent", "CPU", "%", 1], ["memory_mb", "Memória", " MB", 0], ["db_size_bytes", "Tamanho", " MB", 1, 1 / 1048576],
    ["db_growth_mb_per_h", "Crescimento", " MB/h", 3], ["db_growth_gb_per_day", "Projeção", " GB/dia", 4], ["slow_queries", "Slow queries (5 s)", "", 0]],
  dns: [["resolve_ms", "Resolução", " ms", 1], ["qps", "QPS", "/s", 1], ["failure_rate", "Falhas do servidor", "%", 1], ["nxdomain_rate", "NXDOMAIN", "%", 1]],
  smtp: [["delivery_rate", "Entrega", "%", 0], ["queue_size", "Fila", "", 0], ["send_latency_ms", "Latência", " ms", 0], ["error_rate", "Erros", "%", 1], ["volume_per_min", "Volume", "/min", 1]],
};

// Graficos de cada servico. s = series: m metrica, n nome, f fator de escala, step = linha em degrau
const UP = { t: "Disponibilidade (1 = no ar, 0 = fora)", s: [{ m: "up", n: "up", step: true }], max: 1 };
const GRAFICOS = {
  web: [UP,
    { t: "Requisições por segundo (RPS)", s: [{ m: "rps", n: "RPS" }] },
    { t: "Latência HTTP (ms)", s: [{ m: "latency_ms", n: "latência" }] },
    { t: "Taxa de erro (%, janela de 30 s)", s: [{ m: "error_rate_4xx", n: "4xx" }, { m: "error_rate_5xx", n: "5xx" }] },
    { t: "Conexões ativas", s: [{ m: "active_connections", n: "ativas" }] },
    { t: "Respostas por código HTTP (a cada 5 s)", bar: true, m: "requests_by_code", label: "code" }],
  db: [UP,
    { t: "Consultas por segundo (QPS)", s: [{ m: "qps", n: "QPS" }] },
    { t: "Rollbacks por segundo", s: [{ m: "rollbacks_per_s", n: "rollbacks/s" }] },
    { t: "Conexões abertas", s: [{ m: "connections", n: "abertas" }] },
    { t: "CPU do container (%)", s: [{ m: "cpu_percent", n: "CPU" }] },
    { t: "Memória do container (MB)", s: [{ m: "memory_mb", n: "memória" }] },
    { t: "IO de disco do container (KB/s)", s: [{ m: "io_bytes_per_s", n: "IO", f: 1 / 1024 }] },
    { t: "Tamanho do banco (MB)", s: [{ m: "db_size_bytes", n: "tamanho", f: 1 / 1048576 }] },
    { t: "Crescimento do banco (MB/h)", s: [{ m: "db_growth_mb_per_h", n: "MB/h" }] },
    { t: "Slow queries (novas a cada 5 s)", bar: true, s: [{ m: "slow_queries", n: "slow queries" }] }],
  dns: [UP,
    { t: "Tempo de resolução (ms)", s: [{ m: "resolve_ms", n: "resolução" }] },
    { t: "Consultas por segundo (QPS)", s: [{ m: "qps", n: "QPS" }] },
    { t: "Falhas (%, janela de 30 s)", s: [{ m: "failure_rate", n: "falha do servidor" }, { m: "nxdomain_rate", n: "NXDOMAIN" }] }],
  smtp: [UP,
    { t: "Taxa de entrega (%)", s: [{ m: "delivery_rate", n: "entrega" }], max: 100 },
    { t: "Fila de envio (e-mails)", s: [{ m: "queue_size", n: "fila" }] },
    { t: "Latência de envio (ms)", s: [{ m: "send_latency_ms", n: "latência" }] },
    { t: "Taxa de erro (%)", s: [{ m: "error_rate", n: "erro" }] },
    { t: "Volume (e-mails por minuto)", s: [{ m: "volume_per_min", n: "e-mails/min" }] }],
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hora = (ts) => new Date(ts * 1000).toLocaleTimeString("pt-BR");
const dataHora = (ts) => new Date(ts * 1000).toLocaleString("pt-BR");
const num = (v, d) => (v === undefined || v === null ? "-" : Number(v).toFixed(d));
const selo = (n, txt) => `<span class="selo n${n}">${esc(txt || NIVEL[n])}</span>`;

Chart.defaults.color = "#8b97ad";
Chart.defaults.borderColor = "#243049";
Chart.defaults.animation = false;

let periodo = "15m";
let pagina = null;      // objeto { atualizar() } da pagina atual
let charts = {};        // graficos vivos da pagina atual
let ocupado = false;
let pendente = false;   // pedido de atualizacao que chegou enquanto outra estava em andamento

// ---------------- acesso a API ----------------
async function api(caminho) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 4000);
  try {
    const r = await fetch(caminho, { signal: ctl.signal });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  } finally { clearTimeout(timer); }
}

let ultimoOk = null;
function marcarOk(health) {
  ultimoOk = Date.now();
  $("ponto").classList.remove("erro");
  $("atualizacao").textContent = "Última atualização: " + new Date().toLocaleTimeString("pt-BR");
  const aviso = $("aviso");
  if (health.status !== "ok") {
    aviso.textContent = "A API responde, mas a coleta de métricas está atrasada.";
    aviso.className = "amarelo visivel";
  } else { aviso.className = ""; }
}
function marcarFalha() {
  $("ponto").classList.add("erro");
  const seg = ultimoOk ? Math.round((Date.now() - ultimoOk) / 1000) : null;
  $("atualizacao").textContent = "Sem resposta" + (seg !== null ? ` (última leitura há ${seg}s)` : "");
  $("aviso").textContent = "A API do monitor não está respondendo. Os dados exibidos podem estar desatualizados.";
  $("aviso").className = "visivel";
}

// ---------------- graficos ----------------
function destruirCharts() { Object.values(charts).forEach((c) => c.destroy()); charts = {}; }

function corDoCodigo(c) {
  if (c === "401") return "#a78bfa";
  return { 2: "#22c55e", 3: "#38bdf8", 4: "#eab308", 5: "#ef4444" }[c[0]] || "#94a3b8";
}

// Transforma as linhas da API (ts, metric, value, labels) em labels + datasets do Chart.js
function montarDados(linhas, g) {
  let series = g.s;
  if (g.label) {  // uma serie por valor do label (ex.: um codigo HTTP)
    const vals = [...new Set(linhas.filter((r) => r.metric === g.m && r.labels).map((r) => r.labels[g.label]))].sort();
    series = vals.map((v) => ({ m: g.m, n: v, lab: v }));
  }
  const metricas = new Set(series.map((s) => s.m));
  const rel = linhas.filter((r) => metricas.has(r.metric));
  const tempos = [...new Set(rel.map((r) => r.ts))].sort((a, b) => a - b);
  const datasets = series.map((s, i) => {
    const mapa = new Map();
    for (const r of rel) {
      if (r.metric === s.m && (!s.lab || (r.labels && r.labels[g.label] === s.lab))) mapa.set(r.ts, r.value * (s.f || 1));
    }
    const cor = g.label ? corDoCodigo(s.lab) : CORES[i % CORES.length];
    return {
      label: s.n, data: tempos.map((t) => (mapa.has(t) ? mapa.get(t) : null)),
      borderColor: cor, backgroundColor: g.bar ? cor : cor + "33", borderWidth: 2, pointRadius: 0,
      tension: 0.25, stepped: !!s.step, fill: !g.bar && series.length === 1, spanGaps: false,
    };
  });
  return { labels: tempos.map(hora), datasets };
}

function criarOuAtualizar(chave, canvas, g, linhas) {
  const dados = montarDados(linhas, g);
  if (charts[chave]) {
    charts[chave].data = dados;
    charts[chave].update("none");
    return;
  }
  charts[chave] = new Chart(canvas, {
    type: g.bar ? "bar" : "line",
    data: dados,
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: dados.datasets.length > 1 || !!g.label, labels: { boxWidth: 12 } } },
      scales: {
        x: { stacked: !!g.label, ticks: { maxTicksLimit: 6, maxRotation: 0 } },
        y: { stacked: !!g.label, beginAtZero: true, suggestedMax: g.max, ticks: { maxTicksLimit: 5 } },
      },
    },
  });
}

function sparkline(chave, canvas, linhas, cor) {
  const dados = { labels: linhas.map((r) => hora(r.ts)), datasets: [{ data: linhas.map((r) => r.value), borderColor: cor, backgroundColor: cor + "22", fill: true, borderWidth: 1.5, pointRadius: 0, tension: 0.3 }] };
  if (charts[chave]) { charts[chave].data = dados; charts[chave].update("none"); return; }
  charts[chave] = new Chart(canvas, {
    type: "line", data: dados,
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { display: false }, y: { display: false, beginAtZero: true } } },
  });
}

// ---------------- Visao Geral ----------------
function paginaGeral() {
  $("conteudo").innerHTML = `<h2>Visão Geral</h2>
    <div class="grade" id="cards">${SERVICOS.map((s) => `
      <a class="card nivel1" id="card-${s}" href="#/${s}">
        <div class="card-topo"><strong>${NOMES[s]}</strong><span id="selo-${s}"></span></div>
        <div class="kpis" id="kpis-${s}"></div>
        <div class="sparkbox"><canvas id="spark-${s}"></canvas></div>
        <div class="rodape" id="rodape-${s}"></div>
      </a>`).join("")}</div>
    <h3>Últimos alertas</h3><div class="card" id="ultimos"></div>`;
  return {
    async atualizar() {
      const [servicos, alertas, ...series] = await Promise.all([
        api("/api/services"), api("/api/alerts?limit=8"),
        ...SERVICOS.map((s) => api(`/api/metrics?service=${s}&metric=${RESUMO[s].spark}&since=5m`)),
      ]);
      for (const sv of servicos) {
        const s = sv.service, nivel = sv.nivel || 1;
        $("card-" + s).className = `card nivel${nivel}`;
        $("selo-" + s).innerHTML = sv.up === false ? selo(3, "FORA DO AR") : selo(nivel);
        $("kpis-" + s).innerHTML = RESUMO[s].kpis.map(([m, rot, un, d]) =>
          `<div class="kpi"><small>${rot}</small><b>${sv.up === false || sv.metrics[m] === undefined ? "-" : num(sv.metrics[m], d) + un}</b></div>`).join("");
        $("rodape-" + s).textContent = sv.alertas_ativos ? `${sv.alertas_ativos} alerta(s) ativo(s)` : "Nenhum alerta ativo";
      }
      SERVICOS.forEach((s, i) => sparkline("spark-" + s, $("spark-" + s), series[i], "#38bdf8"));
      $("ultimos").innerHTML = alertas.length ? `<ul class="lista-alertas">${alertas.map(linhaAlerta).join("")}</ul>`
        : `<div class="vazio">Nenhum alerta registrado. Tudo verde por enquanto.</div>`;
    },
  };
}

function linhaAlerta(a) {
  const estado = a.resolved_ts ? `resolvido às ${hora(a.resolved_ts)}` : "ATIVO";
  return `<li>${selo(a.max_level)} <b>${esc(a.service)}</b> <span>${esc(a.message)}</span>
    <span class="suave">${dataHora(a.opened_ts)} · ${estado}</span></li>`;
}

// ---------------- Pagina de um servico ----------------
function paginaServico(s) {
  const graficos = GRAFICOS[s];
  $("conteudo").innerHTML = `<h2>${NOMES[s]} <span id="selo"></span></h2>
    <div class="barra">${["5m", "15m", "1h"].map((p) => `<button data-p="${p}" class="${p === periodo ? "ativo" : ""}">${p === "1h" ? "1 hora" : p.replace("m", " min")}</button>`).join("")}
      <span class="suave">atualiza a cada 5 s</span></div>
    <div class="card"><div class="kpis" id="tiles"></div></div>
    <h3>Gráficos</h3>
    <div class="grade graficos">${graficos.map((g, i) => `<div class="card"><h4>${esc(g.t)}</h4><div class="chartbox"><canvas id="g${i}"></canvas></div></div>`).join("")}</div>
    <h3>Regras de alerta deste serviço</h3><div class="tabela" id="regras"></div>`;
  document.querySelectorAll(".barra button").forEach((b) => b.addEventListener("click", () => {
    periodo = b.dataset.p;
    document.querySelectorAll(".barra button").forEach((x) => x.classList.toggle("ativo", x === b));
    destruirCharts();
    tick();
  }));
  return {
    async atualizar() {
      const limite = periodo === "1h" ? 20000 : 10000;
      const [servicos, linhas, regras] = await Promise.all([
        api("/api/services"), api(`/api/metrics?service=${s}&since=${periodo}&limit=${limite}`), api("/api/alert-rules"),
      ]);
      const sv = servicos.find((x) => x.service === s);
      $("selo").innerHTML = sv.up === false ? selo(3, "FORA DO AR") : selo(sv.nivel || 1);
      $("tiles").innerHTML = [`<div class="kpi"><small>Disponibilidade</small><b>${sv.up === null ? "-" : sv.up ? "no ar" : "fora"}</b></div>`]
        .concat(TILES[s].map(([m, rot, un, d, f]) => {
          const v = sv.up === false ? undefined : sv.metrics[m];  // servico fora: valores antigos viram "-"
          return `<div class="kpi"><small>${rot}</small><b>${v === undefined ? "-" : num(v * (f || 1), d) + un}</b></div>`;
        })).join("");
      graficos.forEach((g, i) => criarOuAtualizar("g" + i, $("g" + i), g, linhas));
      $("regras").innerHTML = `<table><tr><th>Nível</th><th>Regra</th><th>Valor atual</th><th>Amarelo</th><th>Vermelho</th><th>Ciclos</th></tr>
        ${regras.filter((r) => r.servico === s).map((r) => `<tr><td>${selo(r.nivel)}</td><td>${esc(r.descricao)}</td>
          <td>${num(r.valor, 2)}${esc(r.unidade)}</td><td>${r.amarelo === null ? "-" : r.operador + " " + r.amarelo}</td>
          <td>${r.vermelho === null ? "-" : r.operador + " " + r.vermelho}</td><td>${r.ciclos}</td></tr>`).join("")}</table>`;
    },
  };
}

// ---------------- Alertas ----------------
function paginaAlertas() {
  $("conteudo").innerHTML = `<h2>Alertas</h2>
    <h3>Ativos agora</h3><div class="ativos" id="ativos"></div>
    <h3>Histórico</h3>
    <div class="barra">
      <label class="suave">Nível <select id="f-nivel"><option value="">todos</option><option value="2">Amarelo</option><option value="3">Vermelho</option></select></label>
      <label class="suave">Serviço <select id="f-serv"><option value="">todos</option>${SERVICOS.map((s) => `<option value="${s}">${s}</option>`).join("")}</select></label>
    </div>
    <div class="tabela" id="historico"></div>
    <h3>Regras configuradas (alerts.yaml)</h3><div class="tabela" id="regras"></div>`;
  const filtros = () => ({ nivel: $("f-nivel").value, serv: $("f-serv").value });
  let ultimo = [];
  const desenhar = () => {
    const f = filtros();
    const lista = ultimo.filter((a) => (!f.nivel || a.max_level == f.nivel) && (!f.serv || a.service === f.serv));
    $("historico").innerHTML = lista.length ? `<table><tr><th>Abertura</th><th>Serviço</th><th>Pior nível</th><th>Nível atual</th><th>Mensagem</th><th>Situação</th></tr>
      ${lista.map((a) => `<tr><td>${dataHora(a.opened_ts)}</td><td>${esc(a.service)}</td><td>${selo(a.max_level)}</td>
        <td>${a.resolved_ts ? "-" : selo(a.level)}</td><td class="msg">${esc(a.message)}</td>
        <td>${a.resolved_ts ? "resolvido " + hora(a.resolved_ts) + " (" + Math.round(a.resolved_ts - a.opened_ts) + " s)" : "<b>ATIVO</b>"}</td></tr>`).join("")}</table>`
      : `<div class="vazio">Nenhum alerta com esses filtros.</div>`;
  };
  $("f-nivel").addEventListener("change", desenhar);
  $("f-serv").addEventListener("change", desenhar);
  return {
    async atualizar() {
      const [todos, regras] = await Promise.all([api("/api/alerts?limit=300"), api("/api/alert-rules")]);
      ultimo = todos;
      const ativos = todos.filter((a) => !a.resolved_ts);
      $("ativos").innerHTML = ativos.length ? ativos.map((a) => `<div class="ativo-card n${a.level}">${selo(a.level)} <b>${esc(a.service)}</b>
          ${esc(a.message)}<div class="suave">desde ${dataHora(a.opened_ts)}</div></div>`).join("")
        : `<div class="card vazio">Nenhum alerta ativo. Todos os serviços estão verdes.</div>`;
      desenhar();
      $("regras").innerHTML = `<table><tr><th>Nível</th><th>Serviço</th><th>Regra</th><th>Métrica</th><th>Agregação</th><th>Amarelo</th><th>Vermelho</th><th>Ciclos (piora/melhora)</th><th>Valor</th></tr>
        ${regras.map((r) => `<tr><td>${selo(r.nivel)}</td><td>${r.servico}</td><td>${esc(r.descricao)}</td><td>${r.metrica}</td>
          <td>${r.agregacao}${r.agregacao === "ultimo" ? "" : " " + r.janela_s + "s"}</td>
          <td>${r.amarelo === null ? "-" : r.operador + " " + r.amarelo}</td><td>${r.vermelho === null ? "-" : r.operador + " " + r.vermelho}</td>
          <td>${r.ciclos} / ${r.ciclos_recuperacao}</td><td>${num(r.valor, 2)}${esc(r.unidade)}</td></tr>`).join("")}</table>`;
    },
  };
}

function paginaSeguranca() {
  $("conteudo").innerHTML = `<h2>Segurança</h2><div class="card"><p>Esta área será construída na Fase 3: detecção de brute force
    (rajadas de 401 no <code>/admin</code>), picos de tráfego (DDoS) e alteração de arquivos de configuração.</p></div>`;
  return { async atualizar() {} };
}

// ---------------- roteamento e ciclo de atualizacao ----------------
function rotear() {
  const r = (location.hash || "#/").slice(2);
  document.querySelectorAll("#menu a").forEach((a) => a.classList.toggle("ativo", a.dataset.r === r));
  destruirCharts();
  if (SERVICOS.includes(r)) pagina = paginaServico(r);
  else if (r === "alertas") pagina = paginaAlertas();
  else if (r === "seguranca") pagina = paginaSeguranca();
  else pagina = paginaGeral();
  tick();
}

async function tick() {
  if (ocupado) { pendente = true; return; }
  ocupado = true;
  try {
    marcarOk(await api("/api/health"));
    await pagina.atualizar();
  } catch (e) {
    marcarFalha();
  } finally {
    ocupado = false;
    if (pendente) { pendente = false; tick(); }
  }
}

window.addEventListener("hashchange", rotear);
setInterval(tick, INTERVALO_MS);
setInterval(() => { if (ultimoOk && Date.now() - ultimoOk > 8000) marcarFalha(); }, 2000);
rotear();
