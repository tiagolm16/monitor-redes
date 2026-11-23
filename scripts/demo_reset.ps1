# Volta tudo ao normal: modo normal no gerador de tráfego, todos os containers ligados.
# Uso: .\scripts\demo_reset.ps1
. "$PSScriptRoot\_comum.ps1"
Set-Location $Raiz
Escrever "=== RESET PARA O ESTADO NORMAL ===" "White"

Escrever "Garantindo que todos os containers estao ligados..." "Yellow"
docker compose up -d | Out-Null
Verificar-Ambiente

try { Definir-Modo "normal" } catch { Escrever "Não consegui falar com o loadgen (:8090)." "Red" }

$cfg = (Obter "/api/security").config
if ($cfg.alterados -gt 0) {
    Escrever "Atenção: $($cfg.alterados) arquivo(s) de configuração diferem da baseline." "Red"
    Escrever "Se a mudanca foi proposital, use o botao 'Aceitar nova baseline' na aba Seguranca." "Red"
}

Escrever "Aguardando os alertas voltarem ao verde (até 90 s)..." "Yellow"
foreach ($s in @("web", "db", "dns", "smtp")) {
    $t = Esperar-Nivel $s 1 90
    if ($null -eq $t) { Escrever "O servico $s ainda não esta verde." "Red" }
}
Mostrar-Status
Escrever "=== PRONTO ===" "White"
