"""
Tests for the right-sizing facts.

The rule is checked against an independent integer computation on 500 generated
cases, and against deliberately wrong versions (a mutant must be caught).
"""

import random
from fractions import Fraction
from types import SimpleNamespace as NS

import pytest

from agent import right_sizing as rs


# --- parsing ---------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("250m", 250), ("1", 1000), ("0m", 0), ("2", 2000),
    ("500u", Fraction(1, 2)), ("1234567n", Fraction(1234567, 1_000_000)), ("", 0), ("junk", 0),
])
def test_cpu_parsing(text, expected):
    assert rs.parse_cpu_millicores(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("10Mi", 10), ("1Gi", 1024), ("10240Ki", 10), ("1048576", 1), ("", 0), ("junk", 0),
])
def test_memory_parsing(text, expected):
    assert rs.parse_memory_mib(text) == expected


# --- the rule --------------------------------------------------------------

def test_hand_worked_cases():
    assert rs.suggest_cpu_m(0) == 10            # floor
    assert rs.suggest_cpu_m(1) == 10            # 1.5 -> rounds up to 10
    assert rs.suggest_cpu_m(7) == 20            # 10.5 -> 20
    assert rs.suggest_cpu_m(20) == 30           # 30 exactly stays 30
    assert rs.suggest_mem_mi(10) == 32          # 15 -> floor 32
    assert rs.suggest_mem_mi(40) == 64          # 60 -> 64
    assert rs.suggest_mem_mi(32) == 48          # 48 exactly stays 48


def _independent_cpu(usage_m: int, num: int, den: int) -> int:
    need = -(-(usage_m * num) // den)                 # ceil(usage x headroom)
    return max(10, -(-need // 10) * 10)


def _independent_mem(usage_mi: int, num: int, den: int) -> int:
    need = -(-(usage_mi * num) // den)
    return max(32, -(-need // 16) * 16)


def test_rule_matches_an_independent_integer_computation_on_500_cases():
    rng = random.Random(0)
    for _ in range(500):
        num, den = rng.choice([(3, 2), (2, 1), (5, 4), (1, 1), (7, 5)])
        cpu, mem = rng.randint(0, 4000), rng.randint(0, 8000)
        h = Fraction(num, den)
        assert rs.suggest_cpu_m(cpu, h) == _independent_cpu(cpu, num, den), (cpu, num, den)
        assert rs.suggest_mem_mi(mem, h) == _independent_mem(mem, num, den), (mem, num, den)


def _violations(usage, suggested, headroom, floor, step):
    """Properties every suggestion must have."""
    problems = []
    if suggested < floor:
        problems.append("below the floor")
    if suggested < Fraction(usage) * headroom:
        problems.append("below measured usage plus headroom")
    if suggested % step:
        problems.append("not a multiple of the step")
    if suggested - step >= max(floor, Fraction(usage) * headroom):
        problems.append("larger than needed")
    return problems


def test_every_suggestion_has_the_required_properties():
    rng = random.Random(1)
    h = rs.HEADROOM
    for _ in range(500):
        u = rng.randint(0, 5000)
        assert _violations(u, rs.suggest_cpu_m(u), h, rs.CPU_FLOOR_M, rs.CPU_STEP_M) == []
        assert _violations(u, rs.suggest_mem_mi(u), h, rs.MEM_FLOOR_MI, rs.MEM_STEP_MI) == []


def test_the_property_check_catches_wrong_versions():
    h = rs.HEADROOM
    no_floor = lambda u: -(-(u * 3 // 2) // 10) * 10                      # ignores the floor
    rounds_down = lambda u: max(10, (u * 3 // 2) // 10 * 10)              # rounds down
    ignores_headroom = lambda u: max(10, -(-u // 10) * 10)                # no headroom
    assert any(_violations(0, no_floor(0), h, 10, 10) for _ in [0])
    assert any(_violations(u, rounds_down(u), h, 10, 10) for u in range(1, 200))
    assert any(_violations(u, ignores_headroom(u), h, 10, 10) for u in range(1, 200))


def test_a_larger_headroom_never_gives_a_smaller_suggestion():
    for u in range(0, 300, 7):
        assert rs.suggest_cpu_m(u, 2) >= rs.suggest_cpu_m(u, Fraction(3, 2)) >= rs.suggest_cpu_m(u, 1)


def test_a_suggestion_applied_as_the_request_gives_no_change():
    row = rs.analyze([{"name": "deployment/a", "request_cpu_m": 10, "request_mem_mi": 32,
                       "usage_cpu_m": 1, "usage_mem_mi": 10}])[0]
    assert row["cpu_status"] == row["mem_status"] == "no change"
    again = rs.analyze([{"name": "deployment/a", "request_cpu_m": row["suggested_cpu_m"],
                         "request_mem_mi": row["suggested_mem_mi"],
                         "usage_cpu_m": 1, "usage_mem_mi": 10}])[0]
    assert again["cpu_status"] == again["mem_status"] == "no change"


# --- analysis --------------------------------------------------------------

def _w(name, rc, rm, uc, um):
    return {"name": name, "request_cpu_m": rc, "request_mem_mi": rm,
            "usage_cpu_m": uc, "usage_mem_mi": um}


def test_statuses():
    rows = rs.analyze([_w("deployment/idle", 50, 64, 1, 10),
                       _w("deployment/busy", 50, 64, 100, 200),
                       _w("deployment/fit", 30, 48, 20, 32)])
    idle, busy, fit = rows
    assert idle["cpu_status"] == idle["mem_status"] == "request could be lowered"
    assert busy["cpu_status"].startswith("request is below")
    assert busy["mem_status"].startswith("request is below")
    assert fit["cpu_status"] == fit["mem_status"] == "no change"


def test_a_workload_without_a_reading_gets_no_suggestion():
    row = rs.analyze([_w("deployment/x", 50, 64, None, None)])[0]
    assert row["measured"] is False
    assert row["suggested_cpu_m"] is None and row["suggested_mem_mi"] is None
    assert row["cpu_status"] == "no usage reading"


def test_summary_counts():
    rows = rs.analyze([_w("deployment/a", 50, 64, 1, 10), _w("deployment/b", 50, 64, None, None),
                       _w("deployment/c", 10, 32, 100, 200)])
    s = rs.summarize(rows)
    assert s == {"workloads": 3, "measured": 2, "cpu_request_could_be_lowered": 1,
                 "mem_request_could_be_lowered": 1, "cpu_request_below_use": 1,
                 "mem_request_below_use": 1}


# --- reading the cluster (with fakes) -------------------------------------

def _pod(name, owner_kind, owner_name):
    return NS(metadata=NS(name=name, owner_references=[NS(kind=owner_kind, name=owner_name)]))


def _metric(name, *containers):
    return {"metadata": {"name": name}, "containers": [{"usage": u} for u in containers]}


def test_usage_uses_the_busiest_replica_and_sums_containers():
    out = rs.usage_by_workload(
        [_metric("p1", {"cpu": "10m", "memory": "20Mi"}, {"cpu": "5m", "memory": "10Mi"}),
         _metric("p2", {"cpu": "100m", "memory": "5Mi"})],
        {"p1": "deployment/a", "p2": "deployment/a"})
    assert out["deployment/a"] == {"cpu": 100, "mem": 30}


def test_pods_that_belong_to_no_workload_are_ignored():
    assert rs.usage_by_workload([_metric("stray", {"cpu": "1m", "memory": "1Mi"})], {}) == {}


def test_pod_owner_mapping():
    assert rs._workload_of(_pod("auth-65c4f4cff5-82xgw", "ReplicaSet", "auth-65c4f4cff5")) == "deployment/auth"
    assert rs._workload_of(_pod("db-0", "StatefulSet", "db")) == "statefulset/db"
    assert rs._workload_of(NS(metadata=NS(name="x", owner_references=None))) is None


def _container(cpu, mem):
    return NS(resources=NS(requests={"cpu": cpu, "memory": mem}))


def test_workloads_from_a_fake_cluster():
    deployments = [NS(metadata=NS(name="auth"),
                      spec=NS(template=NS(spec=NS(containers=[_container("50m", "64Mi")])))),
                   NS(metadata=NS(name="silent"),
                      spec=NS(template=NS(spec=NS(containers=[_container("100m", "128Mi")]))))]
    apps = NS(list_namespaced_deployment=lambda ns: NS(items=deployments),
              list_namespaced_stateful_set=lambda ns: NS(items=[]))
    core = NS(list_namespaced_pod=lambda ns: NS(items=[_pod("auth-aaa-bbb", "ReplicaSet", "auth-aaa")]))
    custom = NS(list_namespaced_custom_object=lambda g, v, ns, p: {
        "items": [_metric("auth-aaa-bbb", {"cpu": "1m", "memory": "12Mi"})]})

    ws = rs.workloads_from_cluster(apps_api=apps, core_api=core, custom_api=custom)
    by_name = {w["name"]: w for w in ws}
    assert by_name["deployment/auth"]["request_cpu_m"] == 50
    assert by_name["deployment/auth"]["request_mem_mi"] == 64
    assert by_name["deployment/auth"]["usage_cpu_m"] == 1
    assert by_name["deployment/auth"]["usage_mem_mi"] == 12
    assert by_name["deployment/silent"]["usage_cpu_m"] is None

    rows = rs.analyze(ws)
    assert [r["name"] for r in rows] == ["deployment/auth", "deployment/silent"]
    assert rows[0]["suggested_cpu_m"] == 10 and rows[0]["suggested_mem_mi"] == 32
    assert rows[1]["cpu_status"] == "no usage reading"


# --- the report ------------------------------------------------------------

def test_the_report_states_its_policy_and_its_limits():
    text = rs.format_report(rs.analyze([_w("deployment/a", 50, 64, 1, 10)]))
    assert "headroom x1.5" in text
    assert "policy parameters, not measurements" in text
    assert "One snapshot is not peak usage" in text
    assert "Nothing is changed in the cluster" in text
    assert "deployment/a: cpu 50m requested, 1m measured, 10m suggested" in text
