"""LLM-only baseline: ask the model directly for a safe migration order, no tools.

Uses the same generated graphs as evaluate_generated.py and an independent
checker written here (it does not use the engine). Answers are scored on:
  parsed    the reply contained usable JSON phases
  complete  every component appears exactly once, no unknown ids
  safe      every dependency is in a strictly earlier phase
  minimal   the number of phases equals the shortest possible (longest chain)
  all_ok    parsed and complete and safe
API errors are counted separately and are NOT counted as model mistakes.

Run:  python -m agent.evaluate_llm_baseline --seeds 5 --cache llm_cache.jsonl --write RESULTS_LLM_BASELINE.md
"""
import json
import os
import re
import sys
from collections import defaultdict

from agent.evaluate_generated import SHAPES, generate_case

MODEL = os.environ.get("NEBIUS_MODEL", "nvidia/nemotron-3-super-120b-a12b")
BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
MAX_TOKENS = int(os.environ.get("BASELINE_MAX_TOKENS", "30000"))
RAW = []   # (shape, seed, finish_reason, reply) for inspection

PROMPT = """You are planning a cloud migration. Each component lists the components it
depends on. A component can only migrate in a phase AFTER every component it depends
on has migrated. Components with no remaining dependencies can migrate together in the
same phase. Use as few phases as possible.

Components (id, dependencies):
{lines}

Reply with JSON only, in this exact form:
{{"phases": [["id", "id"], ["id"]]}}
Every component must appear exactly once."""


def render_prompt(components):
    lines = []
    for c in sorted(components, key=lambda c: c["id"]):
        deps = ", ".join(c["dependencies"]) or "none"
        lines.append(f"- {c['id']}: depends on {deps}")
    return PROMPT.format(lines="\n".join(lines))


def parse_phases(text):
    """List of lists of ids, or None if the reply has no usable JSON."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    for m in re.finditer(r"\{.*\}", text, flags=re.S):
        try:
            data = json.loads(m.group(0))
            ph = data["phases"]
            if isinstance(ph, list) and all(isinstance(p, list) for p in ph):
                return [[str(x) for x in p] for p in ph]
        except (ValueError, KeyError, TypeError):
            continue
    return None


def shortest_phase_count(components):
    """Longest dependency chain, counted in components (independent of the engine)."""
    deps = {c["id"]: c["dependencies"] for c in components}
    memo = {}

    def depth(i):
        if i not in memo:
            memo[i] = 1 + max((depth(d) for d in deps[i]), default=0)
        return memo[i]
    return max(depth(i) for i in deps)


def score(components, phases):
    ids = [c["id"] for c in components]
    if phases is None:
        return {"parsed": False, "complete": False, "safe": False, "minimal": False,
                "all_ok": False, "violations": 0}
    flat = [x for p in phases for x in p]
    complete = sorted(flat) == sorted(ids)
    where = {}
    for n, p in enumerate(phases):
        for x in p:
            where.setdefault(x, n)
    violations = 0
    for c in components:
        for d in c["dependencies"]:
            if c["id"] in where and d in where and where[d] >= where[c["id"]]:
                violations += 1
            elif c["id"] in where and d not in where:
                violations += 1
    safe = violations == 0
    nonempty = [p for p in phases if p]
    minimal = complete and safe and len(nonempty) == shortest_phase_count(components)
    return {"parsed": True, "complete": complete, "safe": safe, "minimal": minimal,
            "all_ok": complete and safe, "violations": violations}


def api_ask(prompt):
    from openai import OpenAI
    client = OpenAI(base_url=BASE_URL, api_key=os.environ["NEBIUS_API_KEY"])
    out = client.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}])
    ch = out.choices[0]
    return ch.message.content, ch.finish_reason


def _ask_with_retry(ask, prompt, tries=3):
    import time
    for k in range(tries):
        try:
            return ask(prompt)
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(5 * 2 ** k)


def run(seeds=5, ask=api_ask, shapes=None, workers=6, cache=None):
    """One row per (shape, seed). Answers are saved to `cache` (JSON lines) as they
    arrive, so a stopped run resumes without repeating finished cases."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    done = {}
    if cache and os.path.exists(cache):
        for line in open(cache):
            try:
                d = json.loads(line)
                done[(d["shape"], d["seed"])] = d
            except ValueError:
                pass
    lock = threading.Lock()
    jobs = [(sh, sd) for sh in (shapes or SHAPES) for sd in range(seeds)]

    def work(job):
        shape, seed = job
        if job in done:
            return done[job]
        comps = generate_case(shape, seed)
        try:
            res = _ask_with_retry(ask, render_prompt(comps))
            reply, fin = res if isinstance(res, tuple) else (res, None)
            rec = {"shape": shape, "seed": seed, "finish": fin, "reply": reply, "error": False}
        except Exception as e:  # network or API problem, not a model mistake
            rec = {"shape": shape, "seed": seed, "finish": None, "reply": None,
                   "error": str(e)[:80]}
        if cache and not rec["error"]:
            with lock:
                with open(cache, "a") as f:
                    f.write(json.dumps(rec) + "\n")
        print(f"  finished {shape} seed {seed}", file=sys.stderr, flush=True)
        return rec

    with ThreadPoolExecutor(max_workers=workers) as pool:
        recs = list(pool.map(work, jobs))
    rows = []
    for rec in recs:
        comps = generate_case(rec["shape"], rec["seed"])
        row = {"shape": rec["shape"], "seed": rec["seed"], "n": len(comps),
               "error": rec["error"], "finish": rec["finish"]}
        if not rec["error"]:
            row.update(score(comps, parse_phases(rec["reply"])))
        rows.append(row)
        RAW.append(rec)
    return rows


def engine_rows(seeds=5, shapes=None, optimizer_cls=None):
    """Run the real engine on the same graphs and score it with the same checker."""
    if optimizer_cls is None:
        from agent.evaluate_generated import CloudRouteOptimizer as optimizer_cls
    rows = []
    for shape in (shapes or SHAPES):
        for seed in range(seeds):
            comps = generate_case(shape, seed)
            opt = optimizer_cls()
            opt.load_blueprint(comps)
            phases, _ = opt.calculate_cost_optimized_sequence(None)
            row = {"shape": shape, "seed": seed, "n": len(comps), "error": False}
            row.update(score(comps, [list(p) for p in phases]))
            rows.append(row)
    return rows


def render_engine(rows, eng):
    n = len(rows); ok = [r for r in rows if not r["error"]]

    def c(rs, k):
        return sum(1 for r in rs if r.get(k))
    lines = ["## Engine on the same graphs", "",
             "Same graphs, same checker. The model rows exclude API errors.", "",
             "| Measure | LLM only | Engine |", "|---|---|---|",
             f"| Reply finished and parsed | {c(ok,'parsed')}/{len(ok)} | n/a |",
             f"| Every component exactly once | {c(ok,'complete')}/{len(ok)} | {c(eng,'complete')}/{len(eng)} |",
             f"| Every dependency in an earlier phase | {c(ok,'safe')}/{len(ok)} | {c(eng,'safe')}/{len(eng)} |",
             f"| Complete and safe | {c(ok,'all_ok')}/{len(ok)} | {c(eng,'all_ok')}/{len(eng)} |",
             f"| Fewest possible phases | {c(ok,'minimal')}/{len(ok)} | {c(eng,'minimal')}/{len(eng)} |", ""]
    return "\n".join(lines) + "\n"


def render(rows):
    ok = [r for r in rows if not r["error"]]
    errs = len(rows) - len(ok)
    n = len(ok)

    def cnt(k):
        return sum(1 for r in ok if r.get(k))
    lines = ["# LLM-only baseline", "",
             f"Model: {MODEL}, no tools, temperature 0. Graphs: {len(rows)} "
             f"({len(SHAPES)} shapes, same generator as the 550-case set).", "",
             "| Measure | LLM only |", "|---|---|",
             f"| Reply parsed | {cnt('parsed')}/{n} |",
             f"| Every component exactly once | {cnt('complete')}/{n} |",
             f"| No dependency violated | {cnt('safe')}/{n} |",
             f"| Complete and safe | {cnt('all_ok')}/{n} |",
             f"| Also the fewest phases | {cnt('minimal')}/{n} |", ""]
    cut = [r for r in ok if r.get("finish") == "length"]
    unparsed = [r for r in ok if not r.get("parsed")]
    lines.append(f"Replies cut off at the token limit ({MAX_TOKENS}): {len(cut)}. "
                 f"Unparsed replies that were NOT cut off: {sum(1 for r in unparsed if r.get('finish') != 'length')}.\n")
    if errs:
        lines.append(f"{errs} case(s) hit an API error and are excluded from the counts.\n")
    by = defaultdict(list)
    for r in ok:
        by[r["shape"]].append(r)
    lines += ["## By shape (complete and safe)", "", "| Shape | ok | avg components |", "|---|---|---|"]
    for sh, rs in by.items():
        lines.append(f"| {sh} | {sum(1 for r in rs if r['all_ok'])}/{len(rs)} | {sum(r['n'] for r in rs)/len(rs):.0f} |")
    bad = [r for r in ok if not r["all_ok"]]
    viol = sum(r.get("violations", 0) for r in ok)
    lines += ["", f"Total dependency violations across all answers: {viol}.", "",
              "The engine's result on the same generator is in RESULTS_GENERATED.md."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    seeds = int(sys.argv[sys.argv.index("--seeds") + 1]) if "--seeds" in sys.argv else 5
    cache = sys.argv[sys.argv.index("--cache") + 1] if "--cache" in sys.argv else None
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6
    rows = run(seeds, workers=workers, cache=cache)
    text = render(rows)
    if "--engine" in sys.argv:
        text += "\n" + render_engine(rows, engine_rows(seeds))
    print(text)
    if "--raw" in sys.argv:
        json.dump(RAW, open(sys.argv[sys.argv.index("--raw") + 1], "w"), indent=1)
    if "--write" in sys.argv:
        path = sys.argv[sys.argv.index("--write") + 1]
        open(path, "w").write(text)
        print("wrote", path)
