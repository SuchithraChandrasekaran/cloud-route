#!/usr/bin/env bash
# Exposes the four services the page uses on localhost. Ctrl+C stops all of them.
set -e
if command -v kubectl >/dev/null 2>&1; then KUBECTL="kubectl"; else KUBECTL="sudo k3s kubectl"; fi
trap 'kill $(jobs -p) 2>/dev/null' EXIT
for pair in auth:4001 account-ledger:4002 payment-processing:4003 loan-servicing:4006; do
  svc="${pair%%:*}"; port="${pair##*:}"
  $KUBECTL port-forward "svc/$svc" "$port:$port" >/dev/null &
done
echo "port-forwarding auth 4001, account-ledger 4002, payment-processing 4003, loan-servicing 4006"
wait
