# Prepara o ambiente para a apresentação: sobe tudo, espera ficar verde, limpa o histórico de alertas
# e abre o painel e o Mailpit no navegador.
# Uso: .\scripts\preparar_apresentacao.ps1
. "$PSScriptRoot\_comum.ps1"
Set-Location $Raiz
Escrever "=== PREPARANDO A APRESENTAÇÃO ===" "White"

# Espera a API do monitor responder (até $limite segundos)
function Esperar-Api([int]$limite = 300) {
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $limite) {
        try { Obter "/api/health" | Out-Null; return $true } catch { Start-Sleep -Seconds 2 }
    }
    return $false
}

# 1) Sobe os containers (na primeira vez baixa imagens e constrói; leva alguns minutos)
Escrever "Subindo os containers (docker compose up -d --build)..." "Yellow"
docker compose up -d --build | Out-Null
if ($LASTEXITCODE -ne 0) { Escrever "Falha ao subir os containers. Confira se o Docker Desktop está aberto." "Red"; exit 1 }
if (-not (Esperar-Api)) { Escrever "O monitor não respondeu em 5 minutos. Veja: docker compose logs monitor" "Red"; exit 1 }
Escrever "Monitor no ar." "Green"

# 2) Garante o modo normal do gerador de tráfego
try { Definir-Modo "normal" } catch { Escrever "Não consegui falar com o loadgen (:8090)." "Red" }

# 3) Limpa o histórico de alertas (a tabela alerts; as métricas são mantidas) e reinicia o monitor
#    para que o motor de alertas recarregue o estado limpo.
Escrever "Limpando o histórico de alertas..." "Yellow"
docker exec rd-monitor python -c "import sqlite3;c=sqlite3.connect('/data/metrics.db');c.execute('delete from alerts');c.commit()"
docker compose restart monitor | Out-Null
Start-Sleep -Seconds 3
if (-not (Esperar-Api 120)) { Escrever "O monitor não voltou após o reinício." "Red"; exit 1 }

# 4) Espera os 4 serviços ficarem verdes
Escrever "Aguardando todos os serviços ficarem verdes (até 4 minutos cada)..." "Yellow"
$ok = $true
foreach ($s in @("web", "db", "dns", "smtp")) {
    $t = Esperar-Nivel $s 1 240
    if ($null -eq $t) { Escrever "O serviço $s não ficou verde." "Red"; $ok = $false }
}
Mostrar-Status

# Logo depois do reinício o monitor pode registrar picos passageiros de latência (conexões frias).
# Apagamos os incidentes já resolvidos para o histórico começar limpo (os ativos são mantidos).
docker exec rd-monitor python -c "import sqlite3;c=sqlite3.connect('/data/metrics.db');c.execute('delete from alerts where resolved_ts is not null');c.commit()"

# 5) Avisos sobre o que pode atrapalhar a demonstração
$sec = Obter "/api/security"
if ($sec.config.alterados -gt 0) {
    Escrever "Atenção: $($sec.config.alterados) arquivo(s) de configuração diferem da baseline. Na aba Segurança, use 'Aceitar nova baseline'." "Red"
}
if (($sec.vulns.PSObject.Properties | Measure-Object).Count -eq 0) {
    Escrever "O scan de vulnerabilidades ainda não foi executado. Rode: docker compose --profile scan run --rm trivy" "DarkYellow"
}
Escrever "O card de Segurança fica amarelo por causa dos CVEs CRITICAL das imagens públicas (esperado)." "DarkYellow"

# 6) Abre o painel e o Mailpit
Start-Process "http://localhost:8000"
Start-Process "http://localhost:8025"
if ($ok) { Escrever "=== PRONTO. Boa apresentação! ===" "White" }
else { Escrever "=== Ambiente subiu, mas há serviços que não ficaram verdes. Confira o painel. ===" "Red" }
