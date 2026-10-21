"""
Evaluation of the right-sizing arithmetic against independently computed answers.

    python -m agent.evaluate_right_sizing
    python -m agent.evaluate_right_sizing --write RESULTS_RIGHT_SIZING.md

Every expected value is computed here with plain integer arithmetic, not with
the fractions and math.ceil the module uses. This tests that the engine
computes the stated rule correctly. It does NOT test that the rule is a good
one (the headroom factor is a policy choice), that suggestions save money, or
that one snapshot predicts peak usage.
"""

import argparse
import datetime
import random
import sys
from fractions import Fraction
from typing import Callable, Dict, List

from agent import right_sizing as rs
from agent.evaluate import _result

SEED = 0
CASES = 1000
HEADROOMS = [(3, 2), (2, 1), (5, 4), (1, 1), (7, 5), (11, 10)]


def _usage(rng) -> Fraction:
    """Random usage; one case in ten is exactly zero, which real clusters report often."""
    if rng.random() < 0.1:
        return Fraction(0)
    return Fraction(rng.randint(0, 400_000), rng.choice([1, 10, 1000]))


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def expected(usage: Fraction, num: int, den: int, floor: int, step: int) -> int:
    """max(floor, ceil(usage x num/den, to a multiple of step)), integers only."""
    a = usage.numerator * num
    b = usage.denominator * den * step
    return max(floor, _ceil_div(a, b) * step)


def check_matches_independent_computation(cpu_fn, mem_fn) -> dict:
    rng = random.Random(SEED)
    failures, total = [], 0
    for _ in range(CASES):
        num, den = rng.choice(HEADROOMS)
        u = _usage(rng)
        h = Fraction(num, den)
        for label, fn, floor, step in (("cpu", cpu_fn, rs.CPU_FLOOR_M, rs.CPU_STEP_M),
                                       ("mem", mem_fn, rs.MEM_FLOOR_MI, rs.MEM_STEP_MI)):
            total += 1
            want = expected(u, num, den, floor, step)
            got = fn(u, h)
            if got != want:
                failures.append(f"{label} usage {u} headroom {num}/{den}: expected {want}, got {got}")
    return _result("Suggestion matches an independent computation",
                   "CPU and memory suggestions equal max(floor, round_up(usage x headroom, step)) "
                   "computed with integers only, over random usage and headroom.",
                   total - len(failures), total, failures)


def check_properties(cpu_fn, mem_fn) -> dict:
    rng = random.Random(SEED + 1)
    failures, total = [], 0
    for _ in range(CASES):
        num, den = rng.choice(HEADROOMS)
        u = _usage(rng)
        h = Fraction(num, den)
        for label, fn, floor, step in (("cpu", cpu_fn, rs.CPU_FLOOR_M, rs.CPU_STEP_M),
                                       ("mem", mem_fn, rs.MEM_FLOOR_MI, rs.MEM_STEP_MI)):
            total += 1
            s = fn(u, h)
            need = u * h
            problems = []
            if s < floor:
                problems.append("below the floor")
            if s < need:
                problems.append("below usage x headroom")
            if s % step:
                problems.append("not a multiple of the step")
            if s - step >= max(floor, need):
                problems.append("larger than needed")
            if problems:
                failures.append(f"{label} usage {u} headroom {num}/{den}: {', '.join(problems)}")
    return _result("Suggestion has the required properties",
                   "Never below the floor, never below usage x headroom, always a multiple of "
                   "the step, and never one step larger than needed.",
                   total - len(failures), total, failures)


def check_monotonic(cpu_fn, mem_fn) -> dict:
    rng = random.Random(SEED + 2)
    failures = []
    for _ in range(CASES):
        a, b = sorted((_usage(rng), _usage(rng)))
        h1, h2 = sorted((Fraction(*rng.choice(HEADROOMS)), Fraction(*rng.choice(HEADROOMS))))
        for label, fn in (("cpu", cpu_fn), ("mem", mem_fn)):
            if fn(a, h1) > fn(b, h1):
                failures.append(f"{label}: more usage ({a} to {b}) gave a smaller suggestion")
                break
            if fn(a, h1) > fn(a, h2):
                failures.append(f"{label}: more headroom ({h1} to {h2}) gave a smaller suggestion")
                break
    return _result("More usage or more headroom never lowers the suggestion",
                   "For random pairs, the suggestion is non-decreasing in usage and in headroom.",
                   CASES - len(failures), CASES, failures)


def check_status(cpu_fn=None, mem_fn=None) -> dict:
    rng = random.Random(SEED + 3)
    failures = []
    for _ in range(CASES):
        rc, rm = rng.randint(1, 4000), rng.randint(1, 8000)
        uc, um = _usage(rng) / 100, _usage(rng) / 100
        row = rs.analyze([{"name": "deployment/x", "request_cpu_m": rc, "request_mem_mi": rm,
                           "usage_cpu_m": uc, "usage_mem_mi": um}])[0]
        for label, request, usage, floor, step, status, suggested in (
                ("cpu", rc, uc, rs.CPU_FLOOR_M, rs.CPU_STEP_M, row["cpu_status"], row["suggested_cpu_m"]),
                ("mem", rm, um, rs.MEM_FLOOR_MI, rs.MEM_STEP_MI, row["mem_status"], row["suggested_mem_mi"])):
            want = expected(usage, 3, 2, floor, step)
            if suggested != want:
                failures.append(f"{label}: suggestion {suggested}, expected {want}")
            elif status != ("request could be lowered" if want < request else
                            "request is below measured use plus headroom" if want > request
                            else "no change"):
                failures.append(f"{label}: request {request}, suggestion {want}, status '{status}'")
    return _result("Status matches the request-versus-suggestion comparison",
                   "Lowered, below measured use, or no change, from the requested value and the "
                   "independently computed suggestion.",
                   CASES - len(failures), CASES, failures)


def check_idempotent(cpu_fn=None, mem_fn=None) -> dict:
    rng = random.Random(SEED + 4)
    failures = []
    for _ in range(CASES):
        uc, um = _usage(rng) / 100, _usage(rng) / 100
        first = rs.analyze([{"name": "deployment/x", "request_cpu_m": 1, "request_mem_mi": 1,
                             "usage_cpu_m": uc, "usage_mem_mi": um}])[0]
        again = rs.analyze([{"name": "deployment/x",
                             "request_cpu_m": first["suggested_cpu_m"],
                             "request_mem_mi": first["suggested_mem_mi"],
                             "usage_cpu_m": uc, "usage_mem_mi": um}])[0]
        if again["cpu_status"] != "no change" or again["mem_status"] != "no change":
            failures.append(f"usage {uc}m / {um}Mi: applying the suggestion still changes it")
    return _result("A suggestion applied as the request gives no change",
                   "Using the suggested values as the requests and measuring the same usage "
                   "reports 'no change'.",
                   CASES - len(failures), CASES, failures)


def check_parsing(cpu_fn=None, mem_fn=None) -> dict:
    rng = random.Random(SEED + 5)
    failures = []
    cpu_units = [("n", Fraction(1, 1_000_000)), ("u", Fraction(1, 1000)), ("m", Fraction(1)), ("", Fraction(1000))]
    mem_units = [("Ki", Fraction(1, 1024)), ("Mi", Fraction(1)), ("Gi", Fraction(1024)), ("", Fraction(1, 1024 * 1024))]
    for _ in range(CASES):
        n = rng.randint(0, 10**9)
        suffix, factor = rng.choice(cpu_units)
        if rs.parse_cpu_millicores(f"{n}{suffix}") != n * factor:
            failures.append(f"cpu '{n}{suffix}'")
        suffix, factor = rng.choice(mem_units)
        if rs.parse_memory_mib(f"{n}{suffix}") != n * factor:
            failures.append(f"memory '{n}{suffix}'")
    return _result("Quantities from the cluster parse correctly",
                   "CPU in n, u, m or whole cores; memory in Ki, Mi, Gi or bytes, converted to "
                   "millicores and MiB exactly.",
                   CASES - len(failures), CASES, failures)


def check_missing_readings(cpu_fn=None, mem_fn=None) -> dict:
    failures = []
    for k in range(100):
        row = rs.analyze([{"name": f"deployment/w{k}", "request_cpu_m": 50, "request_mem_mi": 64,
                           "usage_cpu_m": None if k % 2 else Fraction(1),
                           "usage_mem_mi": Fraction(10) if k % 2 else None}])[0]
        if row["suggested_cpu_m"] is not None or row["suggested_mem_mi"] is not None \
                or row["cpu_status"] != "no usage reading":
            failures.append(f"case {k}: a missing reading still produced a suggestion")
    return _result("A workload without a full reading gets no suggestion",
                   "If either CPU or memory usage is missing, no suggestion is made.",
                   100 - len(failures), 100, failures)


CHECKS = [check_matches_independent_computation, check_properties, check_monotonic,
          check_status, check_idempotent, check_parsing, check_missing_readings]


def run_checks(cpu_fn: Callable = rs.suggest_cpu_m, mem_fn: Callable = rs.suggest_mem_mi) -> List[Dict]:
    return [check(cpu_fn, mem_fn) for check in CHECKS]


def render_markdown(results: List[Dict]) -> str:
    lines = [
        "# Right-sizing evaluation results",
        "",
        f"Generated by `python -m agent.evaluate_right_sizing` on "
        f"{datetime.date.today().isoformat()}. Every number below comes from that run.",
        "",
        "## What is being tested",
        "",
        "The engine computes a suggested CPU and memory request for each workload from its "
        "measured usage: `max(floor, round_up(usage x headroom, step))`. This evaluation checks "
        "that arithmetic against answers computed separately with plain integers, over "
        f"{CASES} random cases per check (seed {SEED}).",
        "",
        "| Check | What it verifies | Result |",
        "|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r['name']} | {r['what']} | {r['passed']}/{r['total']} |")
    lines += [
        "",
        "Deliberately wrong versions (no floor, rounding down, no headroom, an off-by-one step) "
        "are run in `tests/test_evaluate_right_sizing.py`; each one is caught by these checks.",
        "",
        "## Limits of this evaluation",
        "",
        "- It shows the arithmetic is computed as stated. It does not show the rule is a good "
        "one: the headroom factor of 1.5, the floors and the steps are policy choices.",
        "- It does not show that following a suggestion saves money or keeps a workload healthy.",
        "- Measured usage comes from one snapshot of the cluster's metrics service, which is "
        "not peak usage. On the idle bank-easy demo every suggestion is the floor value.",
        "- The reading of the live cluster is cross-checked by hand against `kubectl top`; that "
        "observation is recorded in `docs/right-sizing-live-check.md`, not regenerated here.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the right-sizing arithmetic.")
    parser.add_argument("--write", metavar="FILE", help="write a markdown report")
    args = parser.parse_args()
    results = run_checks()
    for r in results:
        print(f"  [{'PASS' if r['passed'] == r['total'] else 'FAIL'}] {r['name']}: {r['passed']}/{r['total']}")
        for f in r["failures"]:
            print(f"        {f}")
    if args.write:
        with open(args.write, "w") as fh:
            fh.write(render_markdown(results))
        print(f"\nWrote {args.write}")
    ok = all(r["passed"] == r["total"] for r in results)
    print("\nAll checks passed." if ok else "\nSome checks FAILED.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
