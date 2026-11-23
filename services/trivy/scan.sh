#!/bin/sh
# Escaneia as imagens dos 4 servicos monitorados e grava um JSON por servico em /results.
# Uso: docker compose --profile scan run --rm trivy
mkdir -p /results
for par in "web=nginx:1.27-alpine" "db=postgres:16" "dns=coredns/coredns:1.11.3" "smtp=axllent/mailpit:v1.21"; do
  svc=${par%%=*}
  img=${par#*=}
  echo ">> Escaneando $svc ($img)"
  trivy image --quiet --scanners vuln --format json --output "/results/$svc.json" "$img" \
    || echo "!! falhou: $svc"
done
echo ">> Pronto. Resultados em /results (o monitor le automaticamente)."
