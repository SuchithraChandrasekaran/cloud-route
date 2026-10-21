"""
Right-sizing facts: what each workload REQUESTS versus what it was MEASURED
using, and a suggested request. Computed by code, never by the model.

    python -m agent.right_sizing                 # the live cluster
    python -m agent.right_sizing --headroom 2    # a different headroom factor

How a suggestion is computed (all of it is printed with the report):

    suggested = max(floor, round_up(measured_usage x headroom, step))

separately for CPU (millicores) and memory (MiB). The headroom factor, the
floors and the steps are POLICY PARAMETERS chosen here, not measurements.
Arithmetic uses exact fractions, so rounding cannot drift.

Limits, stated plainly:
  * One snapshot is not peak usage. A suggestion from an idle moment is only
    valid for an idle workload.
  * With several replicas, the highest-usage replica is used.
  * CPU is reported by the cluster in whole millicores or finer; memory in
    bytes. Readings near zero are dominated by the floor.
  * It suggests. It never changes the cluster.
  * It does not claim the suggestions save money.
"""

import argparse
import json
import math
import sys
from fractions import Fraction
from typing import Any, Dict, List, Optional

HEADROOM = Fraction(3, 2)
CPU_FLOOR_M = 10
CPU_STEP_M = 10
MEM_FLOOR_MI = 32
MEM_STEP_MI = 16

DEFINITION = (
    "suggested = max(floor, round_up(measured usage x headroom, step)), for CPU "
    "and for memory. Headroom, floors and steps are policy parameters, not "
    "measurements. One snapshot is not peak usage."
)


# --------------------------------------------------------------------------
# Parsing what the cluster reports
# --------------------------------------------------------------------------

def parse_cpu_millicores(text: str) -> Fraction:
    """'250m' -> 250, '1' -> 1000, '1234567n' -> 1.234567, '500u' -> 0.5."""
    text = str(text).strip()
    if not text:
        return Fraction(0)
    scale = {"n": Fraction(1, 1_000_000), "u": Fraction(1, 1000),
             "m": Fraction(1), "": Fraction(1000)}
    suffix = text[-1] if text[-1] in "num" else ""
    number = text[:-1] if suffix else text
    try:
        return Fraction(number) * scale[suffix]
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


def parse_memory_mib(text: str) -> Fraction:
    """'10Mi' -> 10, '1Gi' -> 1024, '10240Ki' -> 10, plain bytes -> MiB."""
    text = str(text).strip()
    if not text:
        return Fraction(0)
    scale = {"Ki": Fraction(1, 1024), "Mi": Fraction(1), "Gi": Fraction(1024),
             "Ti": Fraction(1024 * 1024)}
    for suffix, factor in scale.items():
        if text.endswith(suffix):
            try:
                return Fraction(text[:-len(suffix)]) * factor
            except (ValueError, ZeroDivisionError):
                return Fraction(0)
    try:
        return Fraction(text) / (1024 * 1024)
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------

def _round_up(value: Fraction, step: int) -> int:
    return math.ceil(Fraction(value) / step) * step


def suggest_cpu_m(usage_m, headroom=HEADROOM, floor=CPU_FLOOR_M, step=CPU_STEP_M) -> int:
    return max(floor, _round_up(Fraction(usage_m) * Fraction(headroom), step))


def suggest_mem_mi(usage_mi, headroom=HEADROOM, floor=MEM_FLOOR_MI, step=MEM_STEP_MI) -> int:
    return max(floor, _round_up(Fraction(usage_mi) * Fraction(headroom), step))


def _status(requested, suggested) -> str:
    if suggested < requested:
        return "request could be lowered"
    if suggested > requested:
        return "request is below measured use plus headroom"
    return "no change"


def analyze(workloads: List[Dict[str, Any]], headroom=HEADROOM) -> List[Dict[str, Any]]:
    """
    workloads: [{"name", "request_cpu_m", "request_mem_mi",
                 "usage_cpu_m" or None, "usage_mem_mi" or None}]
    Returns one row per workload, in the order given.
    """
    rows = []
    for w in workloads:
        row = {"name": w["name"],
               "request_cpu_m": w["request_cpu_m"],
               "request_mem_mi": w["request_mem_mi"]}
        if w.get("usage_cpu_m") is None or w.get("usage_mem_mi") is None:
            row.update({"measured": False, "usage_cpu_m": None, "usage_mem_mi": None,
                        "suggested_cpu_m": None, "suggested_mem_mi": None,
                        "cpu_status": "no usage reading", "mem_status": "no usage reading"})
        else:
            sc = suggest_cpu_m(w["usage_cpu_m"], headroom)
            sm = suggest_mem_mi(w["usage_mem_mi"], headroom)
            row.update({"measured": True,
                        "usage_cpu_m": float(w["usage_cpu_m"]),
                        "usage_mem_mi": float(w["usage_mem_mi"]),
                        "suggested_cpu_m": sc, "suggested_mem_mi": sm,
                        "cpu_status": _status(w["request_cpu_m"], sc),
                        "mem_status": _status(w["request_mem_mi"], sm)})
        rows.append(row)
    return rows


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "workloads": len(rows),
        "measured": sum(1 for r in rows if r["measured"]),
        "cpu_request_could_be_lowered": sum(r["cpu_status"] == "request could be lowered" for r in rows),
        "mem_request_could_be_lowered": sum(r["mem_status"] == "request could be lowered" for r in rows),
        "cpu_request_below_use": sum(r["cpu_status"].startswith("request is below") for r in rows),
        "mem_request_below_use": sum(r["mem_status"].startswith("request is below") for r in rows),
    }


# --------------------------------------------------------------------------
# Reading the cluster
# --------------------------------------------------------------------------

def _workload_of(pod) -> Optional[str]:
    """Pod -> 'deployment/<name>' or 'statefulset/<name>' via its owner."""
    for ref in (pod.metadata.owner_references or []):
        if ref.kind == "ReplicaSet":
            return "deployment/" + ref.name.rsplit("-", 1)[0]
        if ref.kind == "StatefulSet":
            return "statefulset/" + ref.name
    return None


def usage_by_workload(metrics_items: List[Dict[str, Any]],
                      pod_to_workload: Dict[str, str]) -> Dict[str, Dict[str, Fraction]]:
    """Per workload: the highest-usage replica (sum over that pod's containers)."""
    best: Dict[str, Dict[str, Fraction]] = {}
    for item in metrics_items:
        workload = pod_to_workload.get(item["metadata"]["name"])
        if workload is None:
            continue
        cpu = sum((parse_cpu_millicores(c["usage"].get("cpu", "0"))
                   for c in item.get("containers", [])), Fraction(0))
        mem = sum((parse_memory_mib(c["usage"].get("memory", "0"))
                   for c in item.get("containers", [])), Fraction(0))
        cur = best.setdefault(workload, {"cpu": cpu, "mem": mem})
        cur["cpu"], cur["mem"] = max(cur["cpu"], cpu), max(cur["mem"], mem)
    return best


def workloads_from_cluster(namespace: str = "default", kubeconfig_path: Optional[str] = None,
                           apps_api=None, core_api=None, custom_api=None) -> List[Dict[str, Any]]:
    """Requests from the workload specs, usage from the cluster's metrics API."""
    from agent.cluster_source import _extract_resource_requests

    if apps_api is None or core_api is None or custom_api is None:
        from kubernetes import client, config
        if kubeconfig_path:
            config.load_kube_config(config_file=kubeconfig_path)
        else:
            config.load_kube_config()
        apps_api = apps_api or client.AppsV1Api()
        core_api = core_api or client.CoreV1Api()
        custom_api = custom_api or client.CustomObjectsApi()

    pod_to_workload = {}
    for pod in core_api.list_namespaced_pod(namespace).items:
        owner = _workload_of(pod)
        if owner:
            pod_to_workload[pod.metadata.name] = owner

    metrics = custom_api.list_namespaced_custom_object(
        "metrics.k8s.io", "v1beta1", namespace, "pods")["items"]
    usage = usage_by_workload(metrics, pod_to_workload)

    workloads = []
    for kind, items in (("deployment", apps_api.list_namespaced_deployment(namespace).items),
                        ("statefulset", apps_api.list_namespaced_stateful_set(namespace).items)):
        for obj in items:
            name = f"{kind}/{obj.metadata.name}"
            cores, gib = _extract_resource_requests(obj.spec.template.spec.containers)
            u = usage.get(name)
            workloads.append({
                "name": name,
                "request_cpu_m": round(cores * 1000),
                "request_mem_mi": round(gib * 1024),
                "usage_cpu_m": u["cpu"] if u else None,
                "usage_mem_mi": u["mem"] if u else None,
            })
    return sorted(workloads, key=lambda w: w["name"])


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def _num(x) -> str:
    """At most two decimals, no trailing zeros: 0.017645 -> 0.02, 1.0 -> 1."""
    return f"{x:.2f}".rstrip("0").rstrip(".") or "0"


def format_report(rows: List[Dict[str, Any]], headroom=HEADROOM) -> str:
    s = summarize(rows)
    lines = [
        "Source: live cluster",
        f"Workloads: {s['workloads']} ({s['measured']} with a usage reading)",
        f"Policy: headroom x{float(headroom):g}; CPU floor {CPU_FLOOR_M}m in steps of {CPU_STEP_M}m; "
        f"memory floor {MEM_FLOOR_MI}Mi in steps of {MEM_STEP_MI}Mi",
        f"Rule: {DEFINITION}",
        f"CPU request could be lowered: {s['cpu_request_could_be_lowered']}; "
        f"below measured use plus headroom: {s['cpu_request_below_use']}",
        f"Memory request could be lowered: {s['mem_request_could_be_lowered']}; "
        f"below measured use plus headroom: {s['mem_request_below_use']}",
        "",
    ]
    for r in rows:
        if not r["measured"]:
            lines.append(f"{r['name']}: no usage reading")
            continue
        lines.append(
            f"{r['name']}: cpu {r['request_cpu_m']}m requested, {_num(r['usage_cpu_m'])}m measured, "
            f"{r['suggested_cpu_m']}m suggested ({r['cpu_status']}); "
            f"memory {r['request_mem_mi']}Mi requested, {_num(r['usage_mem_mi'])}Mi measured, "
            f"{r['suggested_mem_mi']}Mi suggested ({r['mem_status']})")
    lines += ["", "One snapshot is not peak usage. Nothing is changed in the cluster."]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Suggest resource requests from measured usage.")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--kubeconfig", default=None)
    parser.add_argument("--headroom", default="1.5", help="multiplier on measured usage (default 1.5)")
    parser.add_argument("--json", action="store_true", help="print the rows as JSON")
    args = parser.parse_args(argv)
    headroom = Fraction(args.headroom)
    if headroom < 1:
        print("headroom must be at least 1", file=sys.stderr)
        return 2
    rows = analyze(workloads_from_cluster(args.namespace, args.kubeconfig), headroom)
    print(json.dumps(rows, indent=2) if args.json else format_report(rows, headroom))
    return 0


if __name__ == "__main__":
    sys.exit(main())
