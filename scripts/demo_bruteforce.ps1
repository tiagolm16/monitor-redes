# Demo: simula brute force (senhas erradas no /admin do nginx e no Postgres) por 60 s e volta ao normal.
# Uso: .\scripts\demo_bruteforce.ps1
. "$PSScriptRoot\_comum.ps1"
Verificar-Ambiente
Escrever "=== DEMO DE BRUTE FORCE ===" "White"
$inicio = Get-Date
try {
    Definir-Modo "bruteforce"
    $t = Esperar-Alerta "sec_bruteforce*" 90
    if ($null -ne $t) { Escrever "ALERTA de brute force apos $t s." "Red" } else { Escrever "Nenhum alerta em 90 s." "Red" }
    Start-Sleep -Seconds 8
    $b = (Obter "/api/security").brute
    Escrever "IPs com falhas de login nos ultimos $($b.janela_s) s:"
    $b.ips | Select-Object -First 5 | ForEach-Object {
        Write-Host ("   {0,-16} {1,4} falhas  fonte: {2}" -f $_.ip, $_.falhas, ($_.fontes -join ", "))
    }
    Escrever "Contas mais atacadas:"
    $b.contas | Select-Object -First 4 | ForEach-Object { Write-Host ("   {0,-18} {1} falhas" -f $_.conta, $_.falhas) }
    Escrever "E-mails de alerta:"
    Mostrar-Emails 2
    $restante = 60 - [int]((Get-Date) - $inicio).TotalSeconds
    if ($restante -gt 0) { Escrever "Mantendo o ataque por mais $restante s..." "Yellow"; Start-Sleep -Seconds $restante }
}
finally {
    Definir-Modo "normal"
}
$t = Esperar-Resolvido "sec_bruteforce*" 150
if ($null -ne $t) { Escrever "Alerta RESOLVIDO $t s depois de voltar ao normal." "Green" } else { Escrever "O alerta nao resolveu em 150 s." "Red" }
Mostrar-Emails 2
Escrever "=== FIM ===" "White"
