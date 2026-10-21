# Right-sizing: live cross-check against `kubectl top`

A recorded observation, not a generated result. It checks that `agent/right_sizing.py`
reads the same usage numbers the cluster reports.

**Date:** 2026-10-21. **Cluster:** K3s, namespace `default`, the seven bank-easy
Deployments. **Requests:** 50m CPU and 64Mi memory each.

**Idle cluster.** `kubectl top pods` showed 0m to 1m CPU and 10Mi to 12Mi memory per pod.
The module read 0 to 0.02m and 10.8Mi to 12.8Mi (the metrics service reports finer values
than `top` prints). Every workload's suggestion was the floor, 10m CPU and 32Mi memory.

**Under load.** A busy loop was run inside the `loan-servicing` pod for 90 seconds:

    kubectl exec deploy/loan-servicing -- node -e "const e=Date.now()+90000;while(Date.now()<e){}"

Every 15 seconds, `kubectl top pods` and the module were run back to back:

| Time | `kubectl top` CPU | Module: measured CPU | Module: suggested CPU |
|---|---|---|---|
| 15s | 1m | 796.05m | 1200m |
| 30s | 968m | 967.09m | 1460m |
| 45s | 1046m | 1045.89m | 1570m |
| 60s | 1046m | 1045.89m | 1570m |

At 15 seconds the two differ because the load's first reading reached the metrics service
between the two commands. From 30 seconds on they agree to within rounding (`top` prints
whole millicores). The suggestion at 45 seconds checks by hand: 1045.89 x 1.5 = 1568.8,
rounded up to a multiple of 10 is 1570. Memory was 19Mi to 20Mi under load, so its suggestion
stayed at the floor of 32Mi.

**Limits.** This is one run on one cluster. The load is synthetic, a busy loop and not
real traffic. It shows the module reads the cluster's numbers correctly. It does not show
that the suggestions are right for a real workload.
