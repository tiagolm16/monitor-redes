# Demo: altera um comentario do nginx.conf, espera o alerta de alteracao de configuracao e desfaz.
# Uso: .\scripts\demo_config.ps1
. "$PSScriptRoot\_comum.ps1"
Verificar-Ambiente
$arquivo = Join-Path $Raiz "services\nginx\nginx.conf"
Escrever "=== DEMO DE ALTERACAO DE CONFIGURACAO ===" "White"
$original = [System.IO.File]::ReadAllBytes($arquivo)    # guarda os bytes originais para desfazer exatamente

try {
    Escrever "Alterando services\nginx\nginx.conf (adicionando um comentario)..." "Yellow"
    $extra = [System.Text.Encoding]::UTF8.GetBytes("`n# alteracao de demonstracao (nao autorizada)`n")
    [System.IO.File]::WriteAllBytes($arquivo, $original + $extra)
    $t = Esperar-Alerta "sec_config*" 60
    if ($null -ne $t) { Escrever "ALERTA de configuracao alterada apos $t s." "Red" } else { Escrever "Nenhum alerta em 60 s." "Red" }
    Start-Sleep -Seconds 2
    $cfg = (Obter "/api/security").config
    foreach ($a in ($cfg.arquivos | Where-Object { $_.status -ne "ok" })) {
        Escrever ("Arquivo: {0} ({1})" -f $a.arquivo, $a.status) "Red"
        Write-Host ("   hash antigo: {0}" -f $a.hash_baseline)
        Write-Host ("   hash novo:   {0}" -f $a.hash_atual)
        Write-Host "   diff:"
        $a.diff -split "`n" | ForEach-Object { Write-Host "      $_" }
    }
    Escrever "E-mails de alerta:"
    Mostrar-Emails 2
}
finally {
    Escrever "Desfazendo a alteracao (restaurando o arquivo original)..." "Yellow"
    [System.IO.File]::WriteAllBytes($arquivo, $original)
}
$t = Esperar-Resolvido "sec_config*" 60
if ($null -ne $t) { Escrever "Alerta RESOLVIDO $t s depois de restaurar o arquivo." "Green" } else { Escrever "O alerta nao resolveu em 60 s." "Red" }
Mostrar-Emails 2
Escrever "=== FIM ===" "White"
