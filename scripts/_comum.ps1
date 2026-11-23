# Funcoes comuns aos scripts de demonstracao. Uso: . "$PSScriptRoot\_comum.ps1"
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Raiz = Split-Path -Parent $PSScriptRoot      # raiz do projeto (onde está o docker-compose.yml)
$Api = "http://localhost:8000"                # API do monitor
$Loadgen = "http://localhost:8090"            # API de controle do gerador de tráfego
$Mailpit = "http://localhost:8025"

function Escrever([string]$msg, [string]$cor = "Cyan") {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg) -ForegroundColor $cor
}

# O PowerShell 5.1 le JSON sem "charset" como Latin-1 e estraga os acentos; por isso decodificamos como UTF-8.
function Ler-Json([string]$url) {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 8
    [System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()) | ConvertFrom-Json
}

function Obter([string]$caminho) {
    Ler-Json "$Api$caminho"
}

function Definir-Modo([string]$modo) {
    Invoke-RestMethod -Method Post -Uri "$Loadgen/mode/$modo" -TimeoutSec 8 | Out-Null
    Escrever "Modo do gerador de tráfego: $modo" "Yellow"
}

function Mostrar-Status {
    $nomes = @{ 1 = "VERDE"; 2 = "AMARELO"; 3 = "VERMELHO" }
    $cores = @{ 1 = "Green"; 2 = "Yellow"; 3 = "Red" }
    foreach ($s in (Obter "/api/services")) {
        $n = [int]$s.nivel
        Write-Host ("   {0,-9} {1,-9} alertas ativos: {2}" -f $s.service, $nomes[$n], $s.alertas_ativos) -ForegroundColor $cores[$n]
    }
}

# Espera um alerta ATIVO cuja regra combine com o padrão (ex.: "sec_ddos*"). Retorna os segundos ou $null.
function Esperar-Alerta([string]$padrão, [int]$limite = 120) {
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $limite) {
        $achou = Obter "/api/alerts?active=true&limit=100" | Where-Object { $_.rule -like $padrão }
        if ($achou) { return [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) }
        Start-Sleep -Seconds 1
    }
    return $null
}

# Espera não haver mais alerta ativo para o padrão. Retorna os segundos ou $null.
function Esperar-Resolvido([string]$padrão, [int]$limite = 150) {
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $limite) {
        $achou = Obter "/api/alerts?active=true&limit=100" | Where-Object { $_.rule -like $padrão }
        if (-not $achou) { return [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) }
        Start-Sleep -Seconds 1
    }
    return $null
}

# Espera o card de um serviço atingir um nível (1 verde, 2 amarelo, 3 vermelho).
function Esperar-Nivel([string]$servico, [int]$nivel, [int]$limite = 120) {
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $limite) {
        $s = (Obter "/api/services") | Where-Object { $_.service -eq $servico }
        if ([int]$s.nivel -eq $nivel) { return [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) }
        Start-Sleep -Seconds 1
    }
    return $null
}

# Assuntos dos e-mails de alerta mais recentes no Mailpit (só os que começam com colchete).
function Mostrar-Emails([int]$quantos = 4) {
    $msgs = (Ler-Json "$Mailpit/api/v1/messages?limit=60").messages |
        Where-Object { $_.Subject -like "[[]*" } | Select-Object -First $quantos
    foreach ($m in $msgs) {
        Write-Host ("   e-mail {0}  {1}" -f ([datetime]$m.Created).ToLocalTime().ToString("HH:mm:ss"), $m.Subject) -ForegroundColor Magenta
    }
}

function Verificar-Ambiente {
    try { Obter "/api/health" | Out-Null }
    catch { Write-Host "O monitor não responde em $Api. Rode antes: docker compose up -d --build" -ForegroundColor Red; exit 1 }
}
