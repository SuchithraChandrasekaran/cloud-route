"""Grounding study: how often does the model's text go beyond the plan, and does
the scan notice?

Three steps, each resumable:
  python -m agent.grounding_study --run [--repeats 3]   run the real CLI, save every response
  python -m agent.grounding_study --label               you label each response y/n (blind)
  python -m agent.grounding_study --score [--write RESULTS_GROUNDING.md]

Items are fixed here, before any response was seen. Responses are produced by the
real orchestrator CLI on the mock plan (no cluster needed). The scan's verdict is
read from the "[grounding warning]" block the CLI prints. Labels are yours.
"""
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

MODULE = os.environ.get("STUDY_MODULE", "agent.orchestrator")
RUNS = "grounding_runs.jsonl"
LABELS = "grounding_labels.jsonl"
WARN = "[grounding warning]"

ITEMS = [
    ("explain-engineer", "explain", "engineer"),
    ("explain-pm", "explain", "pm"),
    ("explain-client", "explain", "client"),
    ("ask-first", "ask", "Which services can migrate first?"),
    ("ask-order", "ask", "Why does payment-processing come after account-ledger?"),
    ("ask-phases", "ask", "How many phases are there and what is in each?"),
    ("ask-parallel", "ask", "Which services can move at the same time?"),
    ("ask-overhead", "ask", "What is the projected overhead and what does it mean?"),
    ("ask-auth", "ask", "What depends on auth?"),
    ("ask-expensive", "ask", "Which phase is the most expensive?"),
    ("ask-swap", "ask", "Is it safe to migrate loan-servicing before credit-scoring?"),
    ("ask-ledger", "ask", "If account-ledger fails, what else is affected?"),
    ("ask-manager", "ask", "Give me a one-line summary for my manager."),
    ("replan-cost", "replan", "lowest cost"),
    ("replan-phases", "replan", "fewest phases"),
    ("replan-safe", "replan", "safest first"),
]
FLAG = {"explain": "--explain", "ask": "--ask", "replan": "--replan"}


def _read(path):
    out = []
    if os.path.exists(path):
        for line in open(path):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def run_one(item, run):
    iid, kind, arg = item
    cmd = [sys.executable, "-m", MODULE, "--source", "mock", FLAG[kind], arg]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        out, rc = p.stdout, p.returncode
    except subprocess.TimeoutExpired:
        out, rc = "", -1
    return {"id": iid, "kind": kind, "arg": arg, "run": run, "stdout": out,
            "scan_flagged": WARN in out, "returncode": rc}


def do_run(repeats=3, workers=4):
    done = {(r["id"], r["run"]) for r in _read(RUNS) if r["returncode"] == 0}
    jobs = [(it, k) for it in ITEMS for k in range(repeats) if (it[0], k) not in done]
    print(f"{len(jobs)} runs to do ({len(done)} already saved)", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rec in pool.map(lambda j: run_one(*j), jobs):
            with open(RUNS, "a") as f:
                f.write(json.dumps(rec) + "\n")
            print(f"  saved {rec['id']} run {rec['run']} (rc={rec['returncode']})", file=sys.stderr, flush=True)


def blind(text):
    """The response as the labeler sees it: the scan's warning block removed."""
    i = text.find(WARN)
    return text if i < 0 else text[:i].rstrip() + "\n"


def facts_text(blueprint, optimizer_cls):
    """Reference facts from the real engine: what the tools can actually return."""
    opt = optimizer_cls(); opt.load_blueprint(blueprint)
    phases, over = opt.calculate_cost_optimized_sequence(None)
    L = ["REFERENCE FACTS (from the engine; the model's tools return these)", "",
         f"No cap: {len(phases)} phases, overhead {over:.1f}"]
    for k, ph in enumerate(phases, 1):
        L.append(f"  Phase {k}: {ph}")
    for cap in (1, 2, 3, 5):
        ph, ov = opt.calculate_cost_optimized_sequence(cap)
        L.append(f"Max batch size {cap}: {len(ph)} phases, overhead {ov:.1f}")
    L += ["", "Dependencies (component -> what it depends on):"]
    for c in blueprint:
        L.append(f"  {c['id']} -> {', '.join(c.get('dependencies', [])) or 'none'}")
    L += ["", "If a component fails, these must also be rolled back:"]
    for c in blueprint:
        L.append(f"  {c['id']}: {opt.compute_blast_radius_rollback(c['id']) or 'nothing else'}")
    L += ["", "Per-component costs are NOT returned by the tools: a cost for one component counts as unsupported."]
    return "\n".join(L)


def load_facts():
    try:
        from agent.engine import CloudRouteOptimizer
        from agent.orchestrator import MOCK_MIGRATION_BLUEPRINT
        return facts_text(MOCK_MIGRATION_BLUEPRINT, CloudRouteOptimizer)
    except Exception as e:  # keep labeling usable even if the import fails
        return f"(could not build the reference facts: {e})"


_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_NAME = re.compile(r"\b[a-z]+(?:-[a-z]+)+\b", re.IGNORECASE)
_OK_WORDS = {"cloud-route", "depends-on", "unit-less", "cheapest-first", "non-zero", "re-plan",
             "double-billed", "read-only", "free-form", "one-line", "step-by-step"}


def _numbers(text):
    out = set()
    for m in _NUM.findall(text):
        try:
            out.add(round(float(m.replace(",", "")), 4))
        except ValueError:
            pass
    return out


def hints(response, facts):
    """Numbers and hyphenated names in the model's text that neither the reference
    facts nor the plan block printed at the top of the response contain."""
    body = blind(response)
    k = body.find("Projected parallel-cost overhead")
    head = body[:body.find("\n", k)] if k >= 0 else ""
    text = body[len(head):]
    known_nums = _numbers(facts) | _numbers(head)
    nums = sorted({m for m in _NUM.findall(text)
                   if round(float(m.replace(",", "")), 4) not in known_nums}, key=str)
    known_names = {n.lower() for n in _NAME.findall(facts)} | {n.lower() for n in _NAME.findall(head)} | _OK_WORDS
    names = sorted({n.lower() for n in _NAME.findall(text)
                    if n.lower() not in known_names and not re.fullmatch(r"fm-\d\d", n.lower())})
    return nums, names


def do_label():
    runs = [r for r in _read(RUNS) if r["returncode"] == 0]
    have = {(l["id"], l["run"]) for l in _read(LABELS)}
    todo = [r for r in runs if (r["id"], r["run"]) not in have]
    facts = load_facts()
    print(__doc__.split("\n")[0])
    print(facts + "\n")
    print("Label rule: answer y if the model's text states a fact (a service, a number, an order,\n"
          "a cost, a dependency) that is NOT in the plan facts or the REFERENCE FACTS above, or that\n"
          "contradicts them. Type f to show the reference facts again. Style, advice or hedging alone is not enough. n otherwise. s skips, q quits.\n")
    for k, r in enumerate(todo, 1):
        print("=" * 78)
        print(f"[{k}/{len(todo)}] {r['id']} run {r['run']}   ({r['kind']}: {r['arg']})")
        print("=" * 78)
        print(blind(r["stdout"]))
        nums, names = hints(r["stdout"], facts) if not facts.startswith("(could not") else (["?"], [])
        clean = not nums and not names
        print("HINTS (automatic, an aid only): " + ("none found. Still glance at the order and dependency sentences."
              if clean else f"numbers not in the facts: {nums or 'none'}; names not in the facts: {names or 'none'}"))
        while True:
            a = input("unsupported fact? [y/n/s/q/f=show facts" + ("; Enter = n" if clean else "") + "] ").strip().lower()
            if a == "" and clean:
                a = "n"
            if a == "f":
                print(facts)
                continue
            if a in ("y", "n", "s", "q"):
                break
        if a == "q":
            break
        if a == "s":
            continue
        note = input("one-line note (optional): ").strip() if a == "y" else ""
        with open(LABELS, "a") as f:
            f.write(json.dumps({"id": r["id"], "run": r["run"], "label": a, "note": note, "aided": True}) + "\n")


def do_score():
    runs = {(r["id"], r["run"]): r for r in _read(RUNS) if r["returncode"] == 0}
    labels = {(l["id"], l["run"]): l for l in _read(LABELS)}
    both = [(runs[k], labels[k]) for k in labels if k in runs]
    tp = sum(1 for r, l in both if l["label"] == "y" and r["scan_flagged"])
    fn = sum(1 for r, l in both if l["label"] == "y" and not r["scan_flagged"])
    fp = sum(1 for r, l in both if l["label"] == "n" and r["scan_flagged"])
    tn = sum(1 for r, l in both if l["label"] == "n" and not r["scan_flagged"])
    n = len(both); bad = tp + fn
    lines = ["# Grounding study", "",
             f"Responses labeled: {n} of {len(runs)} saved ({len(ITEMS)} items, mock plan). "
             "Labels are by hand, made without seeing the scan's warning, with an automatic aid that lists numbers and hyphenated names not in the reference facts (it does not check order or dependency claims).", "",
             "| | Scan flagged | Scan silent |", "|---|---|---|",
             f"| Unsupported fact (labeled y) | {tp} | {fn} |",
             f"| Nothing unsupported (labeled n) | {fp} | {tn} |", "",
             f"- Responses with an unsupported fact: {bad}/{n}" + (f" ({100*bad/n:.0f}%)" if n else ""),
             f"- Scan caught: {tp}/{bad}" if bad else "- Scan caught: no unsupported facts were labeled",
             f"- Scan missed: {fn}/{bad}" if bad else "",
             f"- False alarms: {fp}/{fp + tn}" if (fp + tn) else "", ""]
    by = {}
    for r, l in both:
        d = by.setdefault(r["kind"], [0, 0, 0])
        d[0] += 1; d[1] += l["label"] == "y"; d[2] += r["scan_flagged"]
    lines += ["| Kind | Responses | Unsupported (hand) | Flagged (scan) |", "|---|---|---|---|"]
    lines += [f"| {k} | {v[0]} | {v[1]} | {v[2]} |" for k, v in by.items()]
    notes = [(l["id"], l["run"], l["note"]) for _, l in both if l["label"] == "y" and l["note"]]
    if notes:
        lines += ["", "## Notes on the unsupported facts", ""] + [f"- {i} run {k}: {t}" for i, k, t in notes]
    lines += ["", "Small sample, one labeler, one plan: the figures describe these responses only.", ""]
    return "\n".join(x for x in lines if x is not None)


if __name__ == "__main__":
    a = sys.argv
    if "--run" in a:
        do_run(int(a[a.index("--repeats") + 1]) if "--repeats" in a else 3)
    elif "--label" in a:
        do_label()
    elif "--score" in a:
        t = do_score(); print(t)
        if "--write" in a:
            open(a[a.index("--write") + 1], "w").write(t); print("wrote")
    else:
        print(__doc__)
