# Demo: derruba um servico, mostra o card ficando vermelho e o e-mail critico, depois religa.
# Uso: .\scripts\demo_queda.ps1 [nginx|postgres|coredns|mailpit]    (padrao: postgres)
param([string]$Servico = "postgres")
. "$PSScriptRoot\_comum.ps1"
Verificar-Ambiente

# Aceita tambem os nomes curtos dos cards
$mapa = @{ web = "nginx"; db = "postgres"; dns = "coredns"; smtp = "mailpit" }
if ($mapa.ContainsKey($Servico)) { $Servico = $mapa[$Servico] }
$card = @{ nginx = "web"; postgres = "db"; coredns = "dns"; mailpit = "smtp" }[$Servico]
if (-not $card) { Write-Host "Servico invalido. Use: nginx, postgres, coredns ou mailpit." -ForegroundColor Red; exit 1 }

Set-Location $Raiz
Escrever "=== DEMO DE QUEDA: $Servico (card '$card') ===" "White"
Escrever "Estado antes da queda:"
Mostrar-Status

try {
    Escrever "Parando o container $Servico..." "Yellow"
    docker compose stop $Servico | Out-Null
    $t = Esperar-Nivel $card 3 90
    if ($null -ne $t) { Escrever "Card '$card' ficou VERMELHO apos $t s." "Red" } else { Escrever "O card nao ficou vermelho em 90 s." "Red" }
    Start-Sleep -Seconds 3
    Mostrar-Status
    if ($Servico -eq "mailpit") {
        Escrever "Obs.: com o Mailpit parado nao ha para onde enviar o e-mail critico (ele fica registrado so no log e no dashboard)." "DarkYellow"
    } else {
        Escrever "E-mails de alerta no Mailpit (http://localhost:8025):"
        Mostrar-Emails 2
    }
}
finally {
    Escrever "Religando $Servico..." "Yellow"
    docker compose start $Servico | Out-Null
}

$t = Esperar-Nivel $card 1 120
if ($null -ne $t) { Escrever "Card '$card' voltou ao VERDE apos $t s." "Green" } else { Escrever "O card nao voltou ao verde em 120 s." "Red" }
Mostrar-Status
Escrever "E-mails de alerta:"
Mostrar-Emails 3
Escrever "=== FIM ===" "White"
