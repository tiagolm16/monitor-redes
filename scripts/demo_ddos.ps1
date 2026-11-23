# Demo: simula um pico de trafego (DDoS) por 60 s e volta ao normal.
# Uso: .\scripts\demo_ddos.ps1
. "$PSScriptRoot\_comum.ps1"
Verificar-Ambiente
Escrever "=== DEMO DE PICO DE TRAFEGO (DDoS) ===" "White"
$d = (Obter "/api/security").ddos
Escrever ("Baseline antes: media {0:N1} req/s, desvio {1:N2} (RPS atual {2:N1})" -f $d.baseline, $d.desvio, $d.rps)

$inicio = Get-Date
try {
    Definir-Modo "pico"
    $t = Esperar-Alerta "sec_ddos*" 90
    if ($null -ne $t) { Escrever "ALERTA de anomalia de trafego apos $t s." "Red" } else { Escrever "Nenhum alerta em 90 s." "Red" }
    Start-Sleep -Seconds 5
    $s = Obter "/api/security"
    Escrever ("RPS {0:N0} | baseline {1:N1} | z-score {2:N1} | razao {3:N1}x" -f $s.ddos.rps, $s.ddos.baseline, $s.ddos.zscore, $s.ddos.razao) "Red"
    Escrever "Top 5 IPs por volume (ultimos 60 s):"
    $s.top_ips | ForEach-Object { Write-Host ("   {0,-16} {1} requisicoes" -f $_.ip, $_.requisicoes) }
    Escrever "E-mails de alerta:"
    Mostrar-Emails 2
    $restante = 60 - [int]((Get-Date) - $inicio).TotalSeconds
    if ($restante -gt 0) { Escrever "Mantendo o pico por mais $restante s..." "Yellow"; Start-Sleep -Seconds $restante }
}
finally {
    Definir-Modo "normal"
}
$t = Esperar-Resolvido "sec_ddos*" 150
if ($null -ne $t) { Escrever "Alerta RESOLVIDO $t s depois de voltar ao normal." "Green" } else { Escrever "O alerta nao resolveu em 150 s." "Red" }
Mostrar-Emails 2
Escrever "=== FIM ===" "White"
