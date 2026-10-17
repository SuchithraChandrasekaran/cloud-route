#!/usr/bin/env bash
# Failure demo: what happens when a dependency is migrated too early.
cd "$(dirname "$0")/.."

pause() { echo; read -r -p "[press Enter to continue] "; echo; }

cleanup() {
  echo "--- cleaning up"
  kubectl scale deployment credit-scoring --replicas=1 > /dev/null 2>&1
  kill $PF1 $PF2 2> /dev/null
}
trap cleanup EXIT

kubectl port-forward svc/account-ledger 4002:4002 > /dev/null 2>&1 &
PF1=$!
kubectl port-forward svc/loan-servicing 4006:4006 > /dev/null 2>&1 &
PF2=$!
until curl -s http://localhost:4002/health > /dev/null; do sleep 0.5; done
until curl -s http://localhost:4006/health > /dev/null; do sleep 0.5; done

loan() {
  curl -s -X POST http://localhost:4006/loans -H "Content-Type: application/json" \
    -d '{"accountId":"'$ACCT'","amount":100000,"termMonths":6}'
  echo
}

echo "=== 1. What cloud-route plans for the live cluster"
python -m agent.orchestrator --source k3s
pause

echo "=== 2. Everything healthy: a customer asks for a loan"
ACCT=$(curl -s -X POST http://localhost:4002/accounts -H "Content-Type: application/json" -d '{"owner":"demo"}' | sed 's/.*"id":"\([^"]*\)".*/\1/')
for i in 1 2 3; do
  curl -s -X POST http://localhost:4002/accounts/$ACCT/transactions -H "Content-Type: application/json" -d '{"type":"deposit","amount":100000}' > /dev/null
done
loan
pause

echo "=== 3. Credit-scoring is migrated too early (taken down)"
kubectl scale deployment credit-scoring --replicas=0
kubectl wait --for=delete pod -l app=credit-scoring --timeout=60s > /dev/null 2>&1
sleep 2
loan
pause

echo "=== 4. Credit-scoring is back, loans work again"
kubectl scale deployment credit-scoring --replicas=1
kubectl rollout status deployment/credit-scoring --timeout=60s
sleep 2
loan
echo
pause

echo "=== 5. The agent explains why loan-servicing has to wait"
if [ -z "$NEBIUS_API_KEY" ]; then
  echo "(skipped: NEBIUS_API_KEY is not set in this shell)"
else
  python -m agent.orchestrator --source k3s --ask "why is loan-servicing in the last phase?"
fi
echo
echo "=== done"
