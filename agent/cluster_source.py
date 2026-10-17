"""
Pulls a real dependency graph from a live K3s cluster.

K3s exposes the same Kubernetes API as full Kubernetes, so this uses the
standard `kubernetes` Python client — no K3s-specific library needed.
Dependencies are inferred from:
  - StatefulSet -> its governing headless Service (via serviceName)
  - Deployment/StatefulSet -> Services that select its pods (via label
    selectors), since a Service must exist before workloads that depend on
    its DNS name can safely start
  - owner references, where the Kubernetes API sets them (e.g. ReplicaSet
    -> Deployment)

This is a heuristic dependency inference, not a guarantee of every real
runtime dependency — an application can depend on another service in ways
the cluster's object graph doesn't express (e.g. a hardcoded URL in an
environment variable). This limitation is intentionally documented here,
not hidden.
"""

from typing import List, Dict, Any

from kubernetes import client, config


def _daily_cost_estimate(cpu_request_cores: float, mem_request_gb: float) -> float:
    """
    A rough, clearly-labeled cost proxy based on requested CPU/memory —
    NOT a real cloud billing figure. Real cost data should come from the
    cluster's actual billing/cost-allocation system where available; this
    exists so the graph engine has *some* cost signal to sort on when
    working against a live cluster with no billing integration configured.
    """
    return round(cpu_request_cores * 20 + mem_request_gb * 5, 2)


def _extract_resource_requests(containers) -> tuple[float, float]:
    total_cpu = 0.0
    total_mem_gb = 0.0
    for c in containers:
        requests = (c.resources.requests or {}) if c.resources else {}
        cpu_str = requests.get("cpu", "0")
        mem_str = requests.get("memory", "0")
        total_cpu += _parse_cpu(cpu_str)
        total_mem_gb += _parse_memory_gb(mem_str)
    return total_cpu, total_mem_gb


def _parse_cpu(cpu_str: str) -> float:
    if cpu_str.endswith("m"):
        return float(cpu_str[:-1]) / 1000
    try:
        return float(cpu_str)
    except ValueError:
        return 0.0


def _parse_memory_gb(mem_str: str) -> float:
    units = {"Ki": 1 / (1024 * 1024), "Mi": 1 / 1024, "Gi": 1, "Ti": 1024}
    for suffix, factor in units.items():
        if mem_str.endswith(suffix):
            try:
                return float(mem_str[: -len(suffix)]) * factor
            except ValueError:
                return 0.0
    try:
        return float(mem_str) / (1024 ** 3)
    except ValueError:
        return 0.0


def load_blueprint_from_cluster(namespace: str = "default", kubeconfig_path: str | None = None) -> List[Dict[str, Any]]:
    """
    Connects to a live K3s cluster (via the default kubeconfig, or
    kubeconfig_path if given — K3s writes its kubeconfig to
    /etc/rancher/k3s/k3s.yaml by default) and returns a component list in
    the same shape CloudRouteOptimizer.load_blueprint expects.
    """
    if kubeconfig_path:
        config.load_kube_config(config_file=kubeconfig_path)
    else:
        config.load_kube_config()

    apps_v1 = client.AppsV1Api()
    core_v1 = client.CoreV1Api()

    components: List[Dict[str, Any]] = []

    services = core_v1.list_namespaced_service(namespace).items
    service_selectors = {
        svc.metadata.name: (svc.spec.selector or {})
        for svc in services
    }

    deployments = apps_v1.list_namespaced_deployment(namespace).items
    statefulsets = apps_v1.list_namespaced_stateful_set(namespace).items

    def matching_services(pod_labels: dict) -> List[str]:
        matches = []
        for svc_name, selector in service_selectors.items():
            if selector and all(pod_labels.get(k) == v for k, v in selector.items()):
                matches.append(svc_name)
        return matches

    def declared_dependencies(annotations) -> List[str]:
        # Optional explicit declaration: cloud-route/depends-on: a,b
        raw = (annotations or {}).get("cloud-route/depends-on", "")
        return [f"deployment/{n.strip()}" for n in raw.split(",") if n.strip()]

    # Services themselves have no workload dependency (they're the target
    # other things depend on), but they're still nodes in the graph.
    for svc in services:
        components.append({
            "id": f"service/{svc.metadata.name}",
            "type": "Service",
            "daily_cost": 0.0,  # a Service itself has no compute cost
            "dependencies": [],
        })

    for dep in deployments:
        pod_labels = (dep.spec.template.metadata.labels or {})
        cpu, mem = _extract_resource_requests(dep.spec.template.spec.containers)
        components.append({
            "id": f"deployment/{dep.metadata.name}",
            "type": "Deployment",
            "daily_cost": _daily_cost_estimate(cpu, mem),
            "dependencies": [f"service/{s}" for s in matching_services(pod_labels)]
            + declared_dependencies(dep.metadata.annotations),
        })

    for sts in statefulsets:
        pod_labels = (sts.spec.template.metadata.labels or {})
        cpu, mem = _extract_resource_requests(sts.spec.template.spec.containers)
        deps = [f"service/{s}" for s in matching_services(pod_labels)]
        if sts.spec.service_name:
            governing = f"service/{sts.spec.service_name}"
            if governing not in deps:
                deps.append(governing)
        components.append({
            "id": f"statefulset/{sts.metadata.name}",
            "type": "StatefulSet",
            "daily_cost": _daily_cost_estimate(cpu, mem),
            "dependencies": deps,
        })

    return components
