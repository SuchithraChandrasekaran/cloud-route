# Task 4 — K3s Live Cluster Test

**Goal:** prove migrate-grid can read a real, live Kubernetes cluster graph.

## Tasks completed

- [x] Installed K3s (`curl -sfL https://get.k3s.io | sh -`)
- [x] Confirmed cluster running: `sudo k3s kubectl get nodes` → `desktop-u4bofg0` Ready, control-plane, v1.36.4+k3s1
- [x] Set up `~/.kube/config` with correct ownership and permissions (`chmod 600`)
- [x] Fixed kubeconfig resolution issue — `kubectl` was falling back to `/etc/rancher/k3s/k3s.yaml` (root-only) instead of `~/.kube/config` because `$KUBECONFIG` wasn't actually exported in the active shell
- [x] Made the fix permanent: added `export KUBECONFIG=$HOME/.kube/config` to `~/.bashrc`
- [x] Verified Python's `kubernetes` client can connect: `list_node()` returned `['desktop-u4bofg0']`
- [x] Applied a sample deployment: `kubectl create deployment nginx-test --image=nginx` → pod reached `Running`
- [x] Ran the real target: `python -m agent.orchestrator --source k3s`

## Result

```
Safe migration phases (cheapest-first within each phase):
  Phase 1: ['service/kubernetes', 'deployment/nginx-test']
  Projected parallel-cost overhead (heuristic): 0.00
```

`cluster_source.py` successfully extracted a live dependency graph from the real K3s cluster, and the deterministic engine sequenced it with a cost estimate. End-to-end live-cluster connection confirmed.

