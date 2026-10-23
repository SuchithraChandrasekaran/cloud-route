"""Planted-fault test of the grounding scan.

The grounding study found no unsupported facts, so it cannot say what the scan
catches. Here we take the real responses the scan did NOT flag, append one planted
sentence to each, and count how often the scan notices. Twelve kinds of sentence:
ten with a planted fault and two harmless controls (to see false alarms).

The scan is the real one: find_unverifiable_component_like_tokens,
find_unsupported_claims and retrieval.find_unreturned_citations, run on the response
text with the warning block removed. "Caught" means the planted sentence added a flag
that the response did not already have.

The sentences were written by one person and are NOT a sample of what a model would
say; the table measures the scan on these kinds of fault only.

Run (needs grounding_runs.jsonl from the study):
    python -m agent.grounding_seeded_faults [--write results/RESULTS_GROUNDING_SEEDED.md]
"""
import json
import sys

from agent import orchestrator, retrieval
from agent.grounding_checks import find_extra_issues
from agent.nemotron_grounding import (find_unsupported_claims,
                                      find_unverifiable_component_like_tokens)

WARN = "[grounding warning]"
RUNS = "grounding_runs.jsonl"

# (name, sentence, kind) kind: designed = the scan's own docstring says it targets this;
# other = a fault the scan was not built for; control = a harmless sentence.
PLANTS = [
    ("invented service, capitalized hyphenated", " The Billing-Service must also be migrated in Phase 2.", "designed"),
    ("same, with a typographic hyphen", " The Billing‑Service must also be migrated in Phase 2.", "designed"),
    ("invented service, lowercase hyphenated", " The billing-service must also be migrated in Phase 2.", "other"),
    ("invented service, single capitalized word", " The Billing service must also be migrated in Phase 2.", "other"),
    ("invented cost for a real service", " The payment-processing service costs 500 per day to run.", "other"),
    ("invented dependency", " The loan-servicing service also depends on auth.", "other"),
    ("wrong phase count", " There are 3 phases in total.", "other"),
    ("phrase on the scan's list", " This approach will save money.", "designed"),
    ("claim not on the list", " This approach is much faster than the alternative.", "other"),
    ("note id the tool never returned", " See [fm-07] for the risk.", "designed"),
    ("control: true restatement", " Phase 1 covers notification and auth.", "control"),
    ("control: negated listed phrase", " The tool does not say whether they run concurrently.", "control"),
]


def blind(text):
    i = text.find(WARN)
    return text if i < 0 else text[:i].rstrip() + "\n"


def flags(text, raw):
    out = {f"name:{n}" for n in find_unverifiable_component_like_tokens(text, raw)}
    out |= {f"phrase:{p}" for p in find_unsupported_claims(text)}
    out |= {f"cite:{c}" for c in retrieval.find_unreturned_citations(text)}
    return out


def extra_flags(text, raw):
    return {f"{k}:{v}" for k, vs in find_extra_issues(text, raw).items() for v in vs}


def load_raw():
    orchestrator._load_blueprint("mock")
    return orchestrator.compute_migration_plan()


def run(runs_path=RUNS, raw=None):
    raw = raw or load_raw()
    allr = [blind(json.loads(l)["stdout"]) for l in open(runs_path) if json.loads(l)["returncode"] == 0]
    base_texts = [blind(json.loads(l)["stdout"]) for l in open(runs_path)
                  if json.loads(l)["returncode"] == 0 and not json.loads(l)["scan_flagged"]]
    rows = []
    for name, sentence, kind in PLANTS:
        old = sum(1 for t in base_texts if flags(t + sentence, raw) - flags(t, raw))
        new = sum(1 for t in base_texts
                  if (flags(t + sentence, raw) | extra_flags(t + sentence, raw))
                  - (flags(t, raw) | extra_flags(t, raw)))
        rows.append((name, kind, old, new, len(base_texts)))
    alarms = {}
    for t in allr:
        for f in extra_flags(t, raw):
            alarms.setdefault(f, 0)
            alarms[f] += 1
    return rows, alarms, len(allr)


def render(res):
    rows, alarms, n_all = res
    L = ["# Planted-fault test of the grounding scan", "",
         f"Base: {rows[0][4]} real responses the scan did not flag. One planted sentence per response and kind.", "",
         "| Planted sentence | Built for | Original scan | With extra checks |", "|---|---|---|---|"]
    label = {"designed": "yes (per its docstring)", "other": "no", "control": "harmless control"}
    L += [f"| {n} | {label[k]} | {o}/{t} | {w}/{t} |" for n, k, o, w, t in rows]
    L += ["", f"False alarms of the extra checks on all {n_all} real responses (no planted sentence): "
          f"{sum(1 for _ in alarms)} distinct flag(s).", ""]
    L += [f"- `{f}` in {c} response(s)" for f, c in sorted(alarms.items())]
    L += ["", "The sentences were written by one person and are not a sample of what a model would say. "
          "The table shows what the scan does and does not notice for these kinds of fault only.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    text = render(run())
    print(text)
    if "--write" in sys.argv:
        open(sys.argv[sys.argv.index("--write") + 1], "w").write(text)
        print("wrote")
