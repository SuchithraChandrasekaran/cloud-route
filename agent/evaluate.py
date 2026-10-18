"""
Evaluation of the deterministic engine against independently computed answers.

The engine decides the migration order. These checks do NOT compare the
engine with itself: every expected answer below is computed here, in plain
Python, without networkx and without calling the engine.

    python -m agent.evaluate                       # the 70-component dataset
    python -m agent.evaluate --source k3s          # the live cluster
    python -m agent.evaluate --source both --write RESULTS.md

What it does NOT evaluate: whether the overhead heuristic matches real cost
(it is an unvalidated proxy), whether the order is the cheapest possible, or
the Nemotron explanations (those are covered by the grounding checks).
"""

import argparse
import copy
import datetime
import random
import sys
from collections import Counter, deque
from typing import Any, Dict, List, Optional, Set

from agent.engine import CloudRouteOptimizer

TRIALS = 200
SEED = 0
BATCH_CAPS = (1, 2, 3, 5)

Components = List[Dict[str, Any]]


# --------------------------------------------------------------------------
# Independent ground truth (no networkx, no engine)
# --------------------------------------------------------------------------

def _deps(components: Components) -> Dict[str, List[str]]:
    return {c["id"]: list(c.get("dependencies", [])) for c in components}


def has_cycle(components: Components) -> bool:
    deps = _deps(components)
    state: Dict[str, int] = {}  # 1 = on the current path, 2 = finished

    def visit(node: str) -> bool:
        state[node] = 1
        for d in deps.get(node, []):
            if state.get(d) == 1:
                return True
            if state.get(d) is None and visit(d):
                return True
        state[node] = 2
        return False

    return any(state.get(n) is None and visit(n) for n in deps)


def expected_levels(components: Components) -> Dict[str, int]:
    """Level 0 = no dependencies; otherwise 1 + the highest level of any dependency.
    The engine's phase number for a component must equal this."""
    deps = _deps(components)
    level: Dict[str, int] = {}

    def visit(node: str) -> int:
        if node not in level:
            level[node] = 0 if not deps[node] else 1 + max(visit(d) for d in deps[node])
        return level[node]

    for n in deps:
        visit(n)
    return level


def transitive_deps(components: Components, node: str) -> Set[str]:
    deps = _deps(components)
    seen: Set[str] = set()
    stack = list(deps[node])
    while stack:
        d = stack.pop()
        if d not in seen:
            seen.add(d)
            stack.extend(deps[d])
    return seen


def expected_blast_radius(components: Components, failed: str) -> Set[str]:
    """The failed component plus everything that depends on it, directly or not."""
    dependents: Dict[str, List[str]] = {c["id"]: [] for c in components}
    for c in components:
        for d in c.get("dependencies", []):
            dependents[d].append(c["id"])
    seen = {failed}
    queue = deque([failed])
    while queue:
        for nxt in dependents[queue.popleft()]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


# --------------------------------------------------------------------------
# Running the engine
# --------------------------------------------------------------------------

def _plan(components: Components, optimizer_cls, cap: Optional[int] = None):
    optimizer = optimizer_cls()
    optimizer.load_blueprint(components)
    phases, overhead = optimizer.calculate_cost_optimized_sequence(cap)
    return optimizer, phases, overhead


def _result(name: str, what: str, passed: int, total: int, failures: List[str]) -> dict:
    return {"name": name, "what": what, "passed": passed, "total": total,
            "failures": failures[:5]}


def _phase_of(phases: List[List[str]]) -> Dict[str, int]:
    return {c: i for i, phase in enumerate(phases) for c in phase}


# --------------------------------------------------------------------------
# Checks. Each returns {"name", "what", "passed", "total", "failures"}.
# --------------------------------------------------------------------------

def check_completeness(components, optimizer_cls) -> dict:
    _, phases, _ = _plan(components, optimizer_cls)
    flat = [c for p in phases for c in p]
    counts = Counter(flat)
    failures = []
    for c in components:
        if counts.get(c["id"], 0) != 1:
            failures.append(f"{c['id']} appears {counts.get(c['id'], 0)} times")
    for extra in set(counts) - {c["id"] for c in components}:
        failures.append(f"{extra} is not a component")
    total = len(components)
    return _result("Every component appears exactly once",
                   "No component is dropped, duplicated or invented.",
                   total - len(failures), total, failures)


def check_phase_placement(components, optimizer_cls) -> dict:
    _, phases, _ = _plan(components, optimizer_cls)
    expected = expected_levels(components)
    actual = _phase_of(phases)
    failures = [f"{c}: phase {actual.get(c)} but expected {expected[c]}"
                for c in expected if actual.get(c) != expected[c]]
    total = len(expected)
    return _result("Each component is in the correct phase",
                   "Phase number equals the longest chain of dependencies below it.",
                   total - len(failures), total, failures)


def check_dependency_order(components, optimizer_cls) -> dict:
    _, phases, _ = _plan(components, optimizer_cls)
    position = _phase_of(phases)
    failures, total = [], 0
    for c in components:
        for d in c.get("dependencies", []):
            total += 1
            if not (position.get(d, 10**9) < position.get(c["id"], -1)):
                failures.append(f"{c['id']} is not after its dependency {d}")
    return _result("Every dependency moves first",
                   "For every dependency edge, the dependency is in an earlier phase.",
                   total - len(failures), total, failures)


def check_cheapest_first(components, optimizer_cls) -> dict:
    _, phases, _ = _plan(components, optimizer_cls)
    cost = {c["id"]: float(c.get("daily_cost", 0.0)) for c in components}
    failures = []
    for i, phase in enumerate(phases):
        costs = [cost[c] for c in phase if c in cost]
        if costs != sorted(costs):
            failures.append(f"phase {i + 1} is not in non-decreasing cost order")
    total = len(phases)
    return _result("Cheapest first within each phase",
                   "Costs never decrease along a phase (ties allowed).",
                   total - len(failures), total, failures)


def check_blast_radius(components, optimizer_cls) -> dict:
    optimizer, _, _ = _plan(components, optimizer_cls)
    failures = []
    for c in components:
        got = optimizer.compute_blast_radius_rollback(c["id"])
        want = expected_blast_radius(components, c["id"])
        if (not got or got[0] != c["id"] or len(got) != len(set(got))
                or set(got) != want):
            failures.append(f"{c['id']}: expected {len(want)} components, "
                            f"got {len(got)}")
    unknown_ok = optimizer.compute_blast_radius_rollback("no-such-component") == []
    total = len(components) + 1
    if not unknown_ok:
        failures.append("an unknown component should give an empty rollback set")
    return _result("Rollback set is correct for every component",
                   "The set is the failed component plus everything that depends "
                   "on it, with the failed one first.",
                   total - len(failures), total, failures)


def check_cycle_detection(components, optimizer_cls) -> dict:
    rng = random.Random(SEED)
    candidates = [c["id"] for c in components if transitive_deps(components, c["id"])]
    failures = []
    for t in range(TRIALS):
        c = rng.choice(candidates)
        d = rng.choice(sorted(transitive_deps(components, c)))
        variant = copy.deepcopy(components)
        next(v for v in variant if v["id"] == d)["dependencies"].append(c)
        if not has_cycle(variant):
            raise RuntimeError("evaluator bug: the injected cycle was not a cycle")
        _, phases, overhead = _plan(variant, optimizer_cls)
        if phases != [] or overhead != 0.0:
            failures.append(f"trial {t}: cycle {d} <-> {c} was not rejected")
    return _result("Injected cycles are rejected",
                   f"{TRIALS} graphs, each with one deliberately added circular "
                   "dependency, must be reported as unsafe.",
                   TRIALS - len(failures), TRIALS, failures)


def check_no_false_cycles(components, optimizer_cls) -> dict:
    rng = random.Random(SEED + 1)
    failures = []
    for t in range(TRIALS):
        keep = rng.uniform(0.5, 0.9)
        variant = copy.deepcopy(components)
        for v in variant:
            v["dependencies"] = [d for d in v["dependencies"] if rng.random() < keep]
        assert not has_cycle(variant)  # removing edges cannot create a cycle
        _, phases, _ = _plan(variant, optimizer_cls)
        actual = _phase_of(phases)
        expected = expected_levels(variant)
        if len(actual) != len(variant) or any(actual.get(c) != expected[c] for c in expected):
            failures.append(f"trial {t}: a valid graph was planned incorrectly")
    return _result("Valid graphs are accepted and ordered correctly",
                   f"{TRIALS} graphs made by deleting random dependencies must all "
                   "be planned, with every component in the correct phase.",
                   TRIALS - len(failures), TRIALS, failures)


def check_batch_caps(components, optimizer_cls) -> dict:
    failures = []
    overheads = []
    for cap in (None,) + tuple(sorted(BATCH_CAPS, reverse=True)):
        _, phases, overhead = _plan(components, optimizer_cls, cap)
        overheads.append(overhead)
        if cap is None:
            continue
        position = _phase_of(phases)
        flat = [c for p in phases for c in p]
        problems = []
        if sorted(flat) != sorted(c["id"] for c in components):
            problems.append("components missing or duplicated")
        if any(len(p) > cap for p in phases):
            problems.append("a phase is larger than the cap")
        if any(position[d] >= position[c["id"]]
               for c in components for d in c.get("dependencies", [])):
            problems.append("dependency order broken")
        if problems:
            failures.append(f"cap {cap}: " + ", ".join(problems))
    if overheads != sorted(overheads):
        failures.append("smaller caps lowered the overhead heuristic")
    total = len(BATCH_CAPS) + 1
    return _result("Batch-size caps keep the plan safe",
                   f"Caps {', '.join(map(str, BATCH_CAPS))}: no component lost, no "
                   "phase over the cap, dependency order kept, and smaller caps "
                   "never lower the overhead heuristic.",
                   total - len(failures), total, failures)


CHECKS = [
    check_completeness,
    check_phase_placement,
    check_dependency_order,
    check_cheapest_first,
    check_blast_radius,
    check_cycle_detection,
    check_no_false_cycles,
    check_batch_caps,
]


def validate_input(components: Components) -> None:
    """The graph under test must itself be well formed, or the answers mean nothing."""
    ids = [c["id"] for c in components]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate component ids")
    known = set(ids)
    for c in components:
        for d in c.get("dependencies", []):
            if d not in known:
                raise ValueError(f"{c['id']} depends on unknown component {d}")
    if has_cycle(components):
        raise ValueError("the graph under test contains a cycle")


def run_checks(components: Components, optimizer_cls=CloudRouteOptimizer) -> List[dict]:
    validate_input(components)
    return [check(components, optimizer_cls) for check in CHECKS]


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def describe(components: Components) -> dict:
    levels = expected_levels(components)
    return {
        "components": len(components),
        "dependencies": sum(len(c.get("dependencies", [])) for c in components),
        "phases": max(levels.values()) + 1 if levels else 0,
        "sources": dict(Counter(c.get("source", "unlabelled") for c in components)),
    }


def print_report(title: str, components: Components, results: List[dict]) -> None:
    info = describe(components)
    print(f"\n{title}")
    print(f"  {info['components']} components, {info['dependencies']} dependencies, "
          f"{info['phases']} phases; sources: {info['sources']}")
    for r in results:
        mark = "PASS" if r["passed"] == r["total"] else "FAIL"
        print(f"  [{mark}] {r['name']}: {r['passed']}/{r['total']}")
        for f in r["failures"]:
            print(f"         - {f}")


def render_markdown(sections: List[dict]) -> str:
    today = datetime.date.today().isoformat()
    lines = [
        "# Evaluation results",
        "",
        f"Generated by `python -m agent.evaluate` on {today}. Every number below "
        "comes from that run.",
        "",
        "## What is being tested",
        "",
        "cloud-route's engine decides the migration order, the rollback sets and "
        "which graphs are unsafe. Nemotron only explains those results. So this "
        "evaluation checks the engine, against answers computed separately in "
        "plain Python (no `networkx`, no calls into the engine).",
        "",
    ]
    for s in sections:
        info = describe(s["components"])
        lines += [f"## {s['title']}", ""]
        lines.append(f"{info['components']} components, {info['dependencies']} "
                     f"dependencies, {info['phases']} phases. Components by source: "
                     f"{info['sources']}.")
        if s.get("note"):
            lines += ["", s["note"]]
        lines += ["", "| Check | What it verifies | Result |", "|---|---|---|"]
        for r in s["results"]:
            lines.append(f"| {r['name']} | {r['what']} | {r['passed']}/{r['total']} |")
        failing = [r for r in s["results"] if r["failures"]]
        if failing:
            lines += ["", "Failures:"]
            for r in failing:
                lines += [f"- {r['name']}: " + "; ".join(r["failures"])]
        lines.append("")
    lines += [
        "## Limits of this evaluation",
        "",
        "- Only 7 of the 70 dataset components are deployed. The other 63 are "
        "modeled to give the engine a graph of realistic size and depth. The "
        "results show the engine is correct on a graph of that shape, not that "
        "a real 70-service system was migrated.",
        "- Dependencies on the live cluster are inferred from Service selectors "
        "and `cloud-route/depends-on` annotations. A dependency that appears in "
        "neither is invisible to the engine.",
        "- \"Cheapest first\" orders by a cost proxy (requested CPU and memory), "
        "not a cloud bill. On the live cluster all deployments request the same "
        "resources, so their order within a phase is a tie.",
        "- The overhead heuristic is not validated against real migration costs. "
        "It is not part of the pass/fail results above.",
        "- The checks show the engine's output is correct and safe. They do not "
        "show it is the cheapest possible order.",
        "- The Nemotron explanations are not evaluated here; they are covered by "
        "the grounding checks in `tests/`.",
        "",
    ]
    return "\n".join(lines)


def _load(source: str) -> Components:
    if source == "dataset":
        from agent.evaluation_dataset import EVALUATION_DATASET
        return copy.deepcopy(EVALUATION_DATASET)
    from agent.cluster_source import load_blueprint_from_cluster
    return load_blueprint_from_cluster()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the cloud-route engine")
    parser.add_argument("--source", choices=["dataset", "k3s", "both"], default="dataset")
    parser.add_argument("--write", metavar="FILE", help="write the results as Markdown")
    args = parser.parse_args()

    plan = []
    if args.source in ("dataset", "both"):
        plan.append(("dataset", "Dataset: 70-component bank platform",
                     "7 components are the deployed bank-easy services; 63 are "
                     "modeled and are not deployed."))
    if args.source in ("k3s", "both"):
        plan.append(("k3s", "Live cluster: bank-easy on K3s",
                     "The graph read from the running cluster at the time of the run. "
                     "It includes the cluster's Service objects as components."))

    sections, all_passed = [], True
    for source, title, note in plan:
        components = _load(source)
        results = run_checks(components)
        print_report(title, components, results)
        sections.append({"title": title, "note": note, "components": components,
                         "results": results})
        all_passed = all_passed and all(r["passed"] == r["total"] for r in results)

    if args.write:
        with open(args.write, "w") as fh:
            fh.write(render_markdown(sections))
        print(f"\nWrote {args.write}")
    print("\nAll checks passed." if all_passed else "\nSome checks FAILED.")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
