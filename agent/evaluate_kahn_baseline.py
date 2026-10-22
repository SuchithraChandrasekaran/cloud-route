"""Plain topological sort (Kahn's algorithm) against the engine, on the generated graphs.

The baseline is written here from scratch (no networkx, no engine code). It returns
the dependency generations in id order and, when a batch cap is given, cuts each
generation into chunks in that same order. The engine does the same but sorts each
generation cheapest-first. Overhead uses the engine's documented formula:
    sum over phases of (phase cost) x (phases remaining, counting the phase itself)
It is a heuristic proxy, not a bill.

Measured on every graph, for no cap and for caps 2 and 3:
  - are the baseline's phases the same sets as the engine's?     (no cap)
  - does the engine's reported overhead equal our own calculation on its phases?
  - is the engine's overhead <= the baseline's, and how often is it strictly lower?

Run:  python -m agent.evaluate_kahn_baseline --write RESULTS_KAHN_BASELINE.md
"""
import sys
from collections import defaultdict

from agent.evaluate_generated import BASE_SEED, SEEDS_PER_SHAPE, SHAPES, generate_case

CAPS = (None, 2, 3)
EPS = 1e-9


def kahn_generations(components):
    """Generations by Kahn's algorithm; ids inside a generation in plain id order."""
    indeg = {c["id"]: len(c["dependencies"]) for c in components}
    users = defaultdict(list)
    for c in components:
        for d in c["dependencies"]:
            users[d].append(c["id"])
    level = sorted(i for i, k in indeg.items() if k == 0)
    out = []
    while level:
        out.append(level)
        nxt = []
        for i in level:
            for u in users[i]:
                indeg[u] -= 1
                if indeg[u] == 0:
                    nxt.append(u)
        level = sorted(nxt)
    return out


def chunk(generations, cap):
    if cap is None:
        return [list(g) for g in generations]
    return [g[s:s + cap] for g in generations for s in range(0, len(g), cap)]


def overhead(phases, cost):
    total = len(phases)
    return sum(sum(cost[i] for i in p) * (total - k) for k, p in enumerate(phases))


def run(optimizer_cls=None, seeds=SEEDS_PER_SHAPE, shapes=None):
    if optimizer_cls is None:
        from agent.evaluate_generated import CloudRouteOptimizer as optimizer_cls
    rows = []
    for shape in (shapes or SHAPES):
        for k in range(seeds):
            comps = generate_case(shape, BASE_SEED + k)
            cost = {c["id"]: float(c["daily_cost"]) for c in comps}
            base = kahn_generations(comps)
            for cap in CAPS:
                opt = optimizer_cls()
                opt.load_blueprint(comps)
                phases, reported = opt.calculate_cost_optimized_sequence(cap)
                plain = chunk(base, cap)
                mine = overhead(phases, cost)
                rows.append({
                    "shape": shape, "seed": BASE_SEED + k, "cap": cap, "n": len(comps),
                    "same_sets": [sorted(p) for p in phases] == [sorted(p) for p in plain],
                    "same_count": len(phases) == len(plain),
                    "formula_ok": abs(mine - reported) <= EPS * max(1.0, abs(mine)),
                    "engine": mine, "plain": overhead(plain, cost),
                })
    return rows


def render(rows):
    lines = ["# Plain topological sort against the engine", "",
             f"Graphs: {len(rows) // len(CAPS)} ({len(SHAPES)} shapes). The baseline is Kahn's algorithm "
             "with ids in plain order; the engine sorts each generation cheapest-first.", "",
             "| Cap | Graphs | Same phases as the engine | Engine overhead matches our formula | "
             "Engine <= plain | Engine strictly lower | Mean reduction when lower |",
             "|---|---|---|---|---|---|---|"]
    for cap in CAPS:
        rs = [r for r in rows if r["cap"] == cap]
        n = len(rs)
        low = [r for r in rs if r["engine"] < r["plain"] - EPS * max(1.0, r["plain"])]
        red = (sum((r["plain"] - r["engine"]) / r["plain"] for r in low) / len(low) * 100) if low else 0.0
        lines.append(f"| {'none' if cap is None else cap} | {n} | "
                     f"{sum(r['same_sets'] for r in rs)}/{n} | {sum(r['formula_ok'] for r in rs)}/{n} | "
                     f"{sum(r['engine'] <= r['plain'] + EPS * max(1.0, r['plain']) for r in rs)}/{n} | "
                     f"{len(low)}/{n} | {red:.1f}% |")
    lines += ["", "With no cap the two give the same phases and the same overhead, because the overhead "
              "depends only on each phase's total cost. A cap makes the order inside a generation matter.",
              "The overhead is the engine's own heuristic, not a measured cost. Rollback sets, residency, "
              "right-sizing and the security scan have no counterpart in a plain sort.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    text = render(run())
    print(text)
    if "--write" in sys.argv:
        path = sys.argv[sys.argv.index("--write") + 1]
        open(path, "w").write(text)
        print("wrote", path)
