"""
Evaluation of the engine's data-residency check against independently
computed answers.

For every graph the expected lists are computed here with plain loops, without
networkx and without calling the engine, and then compared with the engine.

    python -m agent.evaluate_residency
    python -m agent.evaluate_residency --write RESULTS_RESIDENCY.md

What it does NOT show: that data really sits in these regions. Regions are
declared labels. The check tests the engine's logic on those labels.
"""

import argparse
import copy
import datetime
import random
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

from agent.engine import CloudRouteOptimizer
from agent.evaluation_dataset import EVALUATION_DATASET

SEED = 0
TRIALS = 200
REGION_POOL = ("eu-west-1", "eu-central-1", "us-east-1")
EXTRA_REGION = "ap-south-1"  # appears on components, never in an allowed list
DATASET_ALLOWED = ["eu-west-1", "eu-central-1"]

Components = List[Dict[str, Any]]


def tag_dataset(components: Components) -> Components:
    """Fixed rule: positions 0, 7, 14... get no region; the rest cycle the pool."""
    tagged = copy.deepcopy(components)
    for i, comp in enumerate(tagged):
        if i % 7 != 0:
            comp["region"] = REGION_POOL[i % 3]
    return tagged


def expected_residency(components: Components, allowed: Optional[List[str]]) -> Dict[str, Any]:
    """Ground truth in plain Python (no networkx, no engine)."""
    region = {c["id"]: c.get("region") for c in components}
    out_of_policy = sorted(
        cid for cid, r in region.items()
        if r is not None and allowed is not None and r not in allowed
    )
    unassigned = sorted(cid for cid, r in region.items() if r is None)
    pairs = set()
    for comp in components:
        for dep in comp.get("dependencies", []):
            a, b = region[dep], region[comp["id"]]
            if a is not None and b is not None and a != b:
                pairs.add((dep, comp["id"]))
    return {
        "out_of_policy": out_of_policy,
        "cross_region_dependencies": sorted([d, n] for d, n in pairs),
        "unassigned": unassigned,
    }


def random_case(rng: random.Random):
    n = rng.randint(3, 30)
    ids = [f"c{i}" for i in range(n)]
    comps = []
    for i, cid in enumerate(ids):
        deps = [d for d in ids[:i] if rng.random() < 0.25]
        comp = {"id": cid, "daily_cost": round(rng.uniform(0.5, 50), 2),
                "dependencies": deps}
        if rng.random() > 0.2:
            comp["region"] = rng.choice(REGION_POOL + (EXTRA_REGION,))
        comps.append(comp)
    if rng.random() < 0.2:
        allowed = None
    else:
        allowed = rng.sample(list(REGION_POOL), rng.randint(0, len(REGION_POOL)))
    return comps, allowed


def _plan(factory, components: Components):
    opt = factory()
    opt.load_blueprint(components)
    return opt.calculate_cost_optimized_sequence()


def _check_case(factory, components: Components, allowed):
    problems = []
    opt = factory()
    opt.load_blueprint(components)
    got = opt.check_residency(allowed)
    want = expected_residency(components, allowed)

    for key in ("out_of_policy", "cross_region_dependencies", "unassigned"):
        if got.get(key) != want[key]:
            problems.append(f"{key}: engine {got.get(key)}, expected {want[key]}")

    flagged = set(got.get("out_of_policy", []))
    for pair in got.get("cross_region_dependencies", []):
        flagged.update(pair)
    leaked = flagged & set(want["unassigned"])
    if leaked:
        problems.append(f"components with no region were flagged: {sorted(leaked)}")

    stripped = [{k: v for k, v in c.items() if k != "region"} for c in components]
    if _plan(factory, components) != _plan(factory, stripped):
        problems.append("the plan changed when region labels were present")
    return problems, want


def run_checks(engine_factory=CloudRouteOptimizer, trials: int = TRIALS, seed: int = SEED):
    dataset = tag_dataset(EVALUATION_DATASET)
    problems, want = _check_case(engine_factory, dataset, DATASET_ALLOWED)
    ds = {
        "components": len(dataset),
        "assigned": len(dataset) - len(want["unassigned"]),
        "unassigned": len(want["unassigned"]),
        "out_of_policy": len(want["out_of_policy"]),
        "cross_pairs": len(want["cross_region_dependencies"]),
        "problems": problems,
    }

    rng = random.Random(seed)
    failed = []
    stats = Counter()
    for i in range(trials):
        comps, allowed = random_case(rng)
        probs, want = _check_case(engine_factory, comps, allowed)
        if probs:
            failed.append((i, probs))
        if want["out_of_policy"]:
            stats["with_out_of_policy"] += 1
        if want["cross_region_dependencies"]:
            stats["with_cross"] += 1
        if want["unassigned"]:
            stats["with_unassigned"] += 1
        if allowed is None:
            stats["no_policy"] += 1
        if allowed == []:
            stats["empty_policy"] += 1
    rnd = {"cases": trials, "seed": seed, "failed": failed, **stats}
    for key in ("with_out_of_policy", "with_cross", "with_unassigned",
                "no_policy", "empty_policy"):
        rnd.setdefault(key, 0)
    return {"dataset": ds, "random": rnd}


def format_report(results, today) -> str:
    ds, rnd = results["dataset"], results["random"]
    passed = rnd["cases"] - len(rnd["failed"])
    status = "passed" if not ds["problems"] else "FAILED"
    lines = [
        "# Residency check results",
        "",
        f"Generated by `python -m agent.evaluate_residency` on {today}. "
        "Every number below comes from that run.",
        "",
        f"**Bank platform dataset: {status}. "
        f"Random graphs: {passed}/{rnd['cases']} passed.**",
        "",
        "For each graph the engine's residency check is compared with lists "
        "computed independently in plain Python: components outside the "
        "allowed regions, dependencies that cross a region boundary, and "
        "components with no region. Two more checks run on every graph: a "
        "component with no region is never flagged, and adding region labels "
        "never changes the migration plan.",
        "",
        "## Bank platform dataset",
        "",
        f"The {ds['components']}-component dataset gets region labels from a "
        f"fixed rule: the component at position 0, 7, 14 and so on has no "
        f"region, and the others cycle through {', '.join(REGION_POOL)} in "
        f"dataset order. The allowed regions are {', '.join(DATASET_ALLOWED)}.",
        "",
        "| Fact | Count |",
        "|---|---|",
        f"| Components | {ds['components']} |",
        f"| With a region | {ds['assigned']} |",
        f"| Without a region | {ds['unassigned']} |",
        f"| Outside the allowed regions | {ds['out_of_policy']} |",
        f"| Dependencies across regions | {ds['cross_pairs']} |",
        "",
        "## Random graphs",
        "",
        f"{rnd['cases']} graphs of 3 to 30 components (seed {rnd['seed']}), with "
        f"random regions (one of them, {EXTRA_REGION}, is never allowed), random "
        "allowed lists, and some components with no region.",
        "",
        "| Kind of case | Graphs |",
        "|---|---|",
        f"| Had components outside the allowed regions | {rnd['with_out_of_policy']} |",
        f"| Had dependencies across regions | {rnd['with_cross']} |",
        f"| Had components with no region | {rnd['with_unassigned']} |",
        f"| Had no allowed list at all | {rnd['no_policy']} |",
        f"| Had an empty allowed list | {rnd['empty_policy']} |",
        "",
        "## Limits",
        "",
        "- Regions are declared labels, not observed data placement. These "
        "checks test the engine's logic on labels. They do not show that any "
        "data really sits in a region.",
        "- The labels on the bank dataset come from the fixed rule above, not "
        "from a real deployment. Only 7 of its components are deployed, and "
        "on the live cluster the demo labels are set by hand.",
        "- The random graphs are synthetic.",
        "- The expected answers are computed independently of the engine, but "
        "by the same author. A shared misreading of the rule would pass both. "
        "The rule is simple: set membership and a comparison of two labels.",
        "- A component with no region is reported on its own list. It is never "
        "judged compliant or non-compliant.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the residency check")
    parser.add_argument("--write", default=None, metavar="FILE",
                        help="write the results to a markdown file")
    args = parser.parse_args()

    results = run_checks()
    ds, rnd = results["dataset"], results["random"]
    passed = rnd["cases"] - len(rnd["failed"])
    print(f"Bank platform dataset: {'passed' if not ds['problems'] else 'FAILED'}")
    for problem in ds["problems"]:
        print(f"  {problem}")
    print(f"Random graphs: {passed}/{rnd['cases']} passed")
    for index, probs in rnd["failed"][:5]:
        print(f"  case {index}: {probs[0]}")

    if args.write:
        text = format_report(results, datetime.date.today().isoformat())
        with open(args.write, "w") as handle:
            handle.write(text)
        print(f"Wrote {args.write}")
    return 0 if not ds["problems"] and not rnd["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
