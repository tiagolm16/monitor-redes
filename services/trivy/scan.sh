#!/bin/sh
# Escaneia as imagens dos 4 servicos monitorados e grava um JSON por servico em /results.
# Uso: docker compose --profile scan run --rm trivy
mkdir -p /results
for par in "web=nginx:stable-alpine3.23" "db=postgres:17-alpine" "dns=coredns/coredns:1.13.1" "smtp=axllent/mailpit:v1.28"; do
  svc=${par%%=*}
  img=${par#*=}
  echo ">> Escaneando $svc ($img)"
  trivy image --quiet --scanners vuln --format json --output "/results/$svc.json" "$img" \
    || echo "!! falhou: $svc"
done
echo ">> Pronto. Resultados em /results (o monitor le automaticamente)."
