"""
Deterministic security checks on Kubernetes workloads.

Five plain checks on the pod spec of every Deployment and StatefulSet. The
results are facts, like the migration phases: a model may explain them but
never decides them.

    python -m agent.security_scan                      # the live cluster
    python -m agent.security_scan k8s/bank-easy.yaml   # a manifest file

What it does NOT do: it is not a security audit. It does not scan images for
vulnerabilities, check network policies or RBAC, or look at anything outside
these five checks. A workload with no findings has passed these five checks
only; that does not mean it is secure. A secret value is never printed: only
the variable's name is reported.
"""

import argparse
import re
import sys
from typing import Any, Dict, List, Tuple

import yaml
from kubernetes import client, config

CHECK_DEFINITIONS = {
    "missing-limits": (
        "The container sets no CPU limit, no memory limit, or neither, so "
        "nothing caps how much of the node it can use."
    ),
    "latest-image": (
        "The image has no tag or uses the latest tag, so what runs can "
        "change without the manifest changing."
    ),
    "secret-in-env": (
        "An environment variable whose name suggests a secret has its value "
        "written directly in the manifest. Only the variable's name is "
        "reported, never its value."
    ),
    "privileged": (
        "The container runs in privileged mode, which gives it broad access "
        "to the node."
    ),
    "may-run-as-root": (
        "Neither the container nor the pod asks to run as a non-root user, "
        "so the container may run as root."
    ),
}

Workloads = List[Tuple[str, Dict[str, Any]]]

_SECRET_NAME = re.compile(
    r"password|passwd|secret|token|api[_-]?key|private[_-]?key|credential",
    re.IGNORECASE,
)


def _finding(component: str, container: str, check: str, detail: str) -> Dict[str, str]:
    return {"component": component, "container": container,
            "check": check, "detail": detail}


def _image_is_unpinned(image: str) -> bool:
    last = image.rsplit("/", 1)[-1]
    if "@" in last:  # pinned by digest
        return False
    if ":" not in last:  # no tag
        return True
    return last.split(":", 1)[1] == "latest"


def _is_zero_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _is_nonzero_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value != 0


def _scan_container(component: str, container: Dict[str, Any],
                    pod_spec: Dict[str, Any]) -> List[Dict[str, str]]:
    name = container.get("name", "?")
    found: List[Dict[str, str]] = []

    limits = (container.get("resources") or {}).get("limits") or {}
    missing = [r for r in ("cpu", "memory") if not limits.get(r)]
    if missing:
        found.append(_finding(component, name, "missing-limits",
                              ", ".join(f"no {r} limit" for r in missing)))

    image = container.get("image") or ""
    if _image_is_unpinned(image):
        found.append(_finding(component, name, "latest-image",
                              f"image {image or '(none)'} has no tag or uses the latest tag"))

    for env in container.get("env") or []:
        var = env.get("name") or ""
        if (_SECRET_NAME.search(var)
                and env.get("value") not in (None, "")
                and not env.get("valueFrom")):
            found.append(_finding(component, name, "secret-in-env",
                                  f"environment variable {var} has its value "
                                  f"written in the manifest"))

    sc = container.get("securityContext") or {}
    pod_sc = pod_spec.get("securityContext") or {}
    if sc.get("privileged") is True:
        found.append(_finding(component, name, "privileged",
                              "the container runs in privileged mode"))

    non_root = sc["runAsNonRoot"] if "runAsNonRoot" in sc else pod_sc.get("runAsNonRoot")
    user = sc["runAsUser"] if "runAsUser" in sc else pod_sc.get("runAsUser")
    if _is_zero_int(user):
        found.append(_finding(component, name, "may-run-as-root",
                              "runs as user 0 (root)"))
    elif non_root is not True and not _is_nonzero_int(user):
        found.append(_finding(component, name, "may-run-as-root",
                              "neither the container nor the pod sets runAsNonRoot "
                              "to true or a non-zero runAsUser"))
    return found


def scan_workloads(workloads: Workloads) -> List[Dict[str, str]]:
    """Runs every check on every container. The result is sorted, so it is repeatable."""
    findings: List[Dict[str, str]] = []
    for component, pod_spec in workloads:
        pod_spec = pod_spec or {}
        containers = (list(pod_spec.get("initContainers") or [])
                      + list(pod_spec.get("containers") or []))
        for container in containers:
            findings.extend(_scan_container(component, container, pod_spec))
    return sorted(findings, key=lambda f: (f["component"], f["container"], f["check"]))


def summarize(findings: List[Dict[str, str]]) -> Dict[str, Any]:
    by_check: Dict[str, int] = {}
    for f in findings:
        by_check[f["check"]] = by_check.get(f["check"], 0) + 1
    return {
        "total": len(findings),
        "by_check": by_check,
        "components_with_findings": len({f["component"] for f in findings}),
    }


def workloads_from_manifest(text: str) -> Workloads:
    """Deployments and StatefulSets in a manifest, named like the engine names them."""
    out: Workloads = []
    for doc in yaml.safe_load_all(text):
        if not isinstance(doc, dict) or doc.get("kind") not in ("Deployment", "StatefulSet"):
            continue
        name = (doc.get("metadata") or {}).get("name")
        if not name:
            continue
        pod_spec = ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}
        out.append((f"{doc['kind'].lower()}/{name}", pod_spec))
    return out


def workloads_from_cluster(namespace: str = "default",
                           kubeconfig_path: str | None = None) -> Workloads:
    """Deployments and StatefulSets from the live cluster."""
    if kubeconfig_path:
        config.load_kube_config(config_file=kubeconfig_path)
    else:
        config.load_kube_config()
    apps_v1 = client.AppsV1Api()
    to_dict = client.ApiClient().sanitize_for_serialization
    out: Workloads = []
    for dep in apps_v1.list_namespaced_deployment(namespace).items:
        out.append((f"deployment/{dep.metadata.name}", to_dict(dep.spec.template.spec) or {}))
    for sts in apps_v1.list_namespaced_stateful_set(namespace).items:
        out.append((f"statefulset/{sts.metadata.name}", to_dict(sts.spec.template.spec) or {}))
    return out


def format_findings(source: str, workload_count: int, findings: List[Dict[str, str]]) -> str:
    summary = summarize(findings)
    lines = [f"Source: {source}",
             f"Workloads scanned: {workload_count}",
             f"Findings: {summary['total']}"]
    for check in sorted(summary["by_check"]):
        lines.append(f"  {check}: {summary['by_check'][check]}")
    for f in findings:
        lines.append(f"{f['component']} [{f['container']}] {f['check']}: {f['detail']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic security checks on Kubernetes workloads")
    parser.add_argument("manifest", nargs="?", default=None,
                        help="a manifest file; leave out to scan the live cluster")
    args = parser.parse_args(argv)
    if args.manifest:
        with open(args.manifest) as handle:
            workloads = workloads_from_manifest(handle.read())
        source = args.manifest
    else:
        workloads = workloads_from_cluster()
        source = "live cluster"
    print(format_findings(source, len(workloads), scan_workloads(workloads)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
