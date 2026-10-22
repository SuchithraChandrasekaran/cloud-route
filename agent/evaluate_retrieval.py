"""Measure how often retrieval returns the right failure-mode note.

Questions are written by hand, mostly in everyday wording that does NOT copy the
notes' keywords. Each lists the note ids that count as a correct answer.
Questions with an empty list are out of scope: nothing should be returned.

Run:  python -m agent.evaluate_retrieval            (prints a summary)
      python -m agent.evaluate_retrieval --verbose  (every question)
      python -m agent.evaluate_retrieval --write RESULTS_RETRIEVAL.md
"""
import sys

from agent.retrieval import load_notes, search

METHOD = "bm25"
MIN_SCORE = 0.0
SCORES = {}

# (question, acceptable ids, kind)  kind: "plain" = near the note's own words,
# "para" = paraphrase, "out" = should return nothing
QUESTIONS = [
    # --- plain wording ---
    ("What happens if the service moves before its database?", ["fm-01"], "plain"),
    ("Can data be lost while the copy is running?", ["fm-02"], "plain"),
    ("What goes wrong with messages in the queue during the move?", ["fm-03"], "plain"),
    ("Why do some users still hit the old address after cutover?", ["fm-04"], "plain"),
    ("What if a secret was not copied to the new environment?", ["fm-05"], "plain"),
    ("Why did the plan miss a dependency that the service really has?", ["fm-06"], "plain"),
    ("What if the two sides run different API versions?", ["fm-07"], "plain"),
    ("Why do requests fail right after a component starts?", ["fm-08"], "plain"),
    ("Can I roll back a component that stores data?", ["fm-09"], "plain"),
    ("What if a component many others depend on fails?", ["fm-10"], "plain"),
    ("What about calls between the old and new environments?", ["fm-11", "fm-01"], "plain"),
    ("Will alerts still watch the right environment?", ["fm-12"], "plain"),
    # --- paraphrases, avoiding the notes' keywords ---
    ("The app moved but its tables are still where they were. Is that a problem?", ["fm-01"], "para"),
    ("Customers wrote orders while we were duplicating the store. Will they appear?", ["fm-02"], "para"),
    ("Consumers switched sides first and some events were never handled.", ["fm-03"], "para"),
    ("Some visitors keep landing on the retired site for hours.", ["fm-04"], "para"),
    ("The new copy of the app says login refused although the code is identical.", ["fm-05"], "para"),
    ("Our plan ordered things wrongly because one call is only set in a config value.", ["fm-06"], "para"),
    ("One team shipped a newer release and the other did not; the payloads stopped parsing.", ["fm-07"], "para"),
    ("Pages return errors for the first minute after a restart.", ["fm-08"], "para"),
    ("If we go back, will the records created in the meantime still be there?", ["fm-09"], "para"),
    ("How much do we have to undo if the auth service has to be reversed?", ["fm-10"], "para"),
    ("Half the system is in each place and the link between them is slow and blocked.", ["fm-11"], "para"),
    ("We would not notice a crash because the graphs still show the old site.", ["fm-12"], "para"),
    # --- out of scope: nothing should come back ---
    ("What is the capital of France?", [], "out"),
    ("How do I bake sourdough bread?", [], "out"),
    ("Who won the cricket world cup?", [], "out"),
    ("Write a poem about the sea.", [], "out"),
]


def ids_of(results):
    out = []
    for r in results or []:
        if isinstance(r, dict):
            note = r.get("note", r)
            out.append(note.get("id"))
        elif isinstance(r, (tuple, list)):
            first = r[0]
            out.append(first["id"] if isinstance(first, dict) else getattr(first, "id", None))
        else:
            note = getattr(r, "note", r)
            out.append(getattr(note, "id", None) or (note.get("id") if isinstance(note, dict) else None))
    return out


def run(embed=None):
    notes = load_notes()
    rows = []
    if METHOD != "bm25":
        from agent import embed_retrieval as er
        embed = embed or er.api_embed
        index = er.build_index(notes, embed=embed)
    for q, ok, kind in QUESTIONS:
        if METHOD == "bm25":
            res = search(q, notes)
        else:
            top = er.search_embed(q, notes, index, embed=embed, k=1, min_score=-1)
            SCORES[q] = top[0][1] if top else 0.0
            fn = er.search_embed if METHOD == "embed" else er.search_hybrid
            res = fn(q, notes, index, embed=embed, min_score=MIN_SCORE)
        got = ids_of(res)
        if ok:
            rank = next((i + 1 for i, g in enumerate(got) if g in ok), None)
        else:
            rank = None
        rows.append((q, ok, kind, got, rank))
    return rows


def summarise(rows):
    s = {}
    for kind in ("plain", "para", "all", "out"):
        sel = [r for r in rows if (r[2] == kind or (kind == "all" and r[2] != "out"))]
        if kind == "out":
            n = len(sel)
            clean = sum(1 for r in sel if not r[3])
            s[kind] = (n, clean)
        else:
            n = len(sel)
            h1 = sum(1 for r in sel if r[4] == 1)
            h3 = sum(1 for r in sel if r[4] is not None and r[4] <= 3)
            mrr = sum((1 / r[4]) for r in sel if r[4]) / n
            s[kind] = (n, h1, h3, mrr)
    return s


def render(rows):
    s = summarise(rows)
    lines = ["# Retrieval evaluation", "",
             f"Method: {METHOD}" + (f" (min score {MIN_SCORE})" if METHOD != "bm25" else "") + f". Notes: {len(load_notes())}. Questions: {len(rows)} (hand-written).", "",
             "| Question set | n | right note first | right note in top 3 | MRR |",
             "|---|---|---|---|---|"]
    for k, label in (("plain", "Plain wording"), ("para", "Paraphrased"), ("all", "All in scope")):
        n, h1, h3, m = s[k]
        lines.append(f"| {label} | {n} | {h1}/{n} | {h3}/{n} | {m:.2f} |")
    n, clean = s["out"]
    lines += ["", f"Out-of-scope questions that correctly returned nothing: {clean}/{n}.", "",
              "## Misses (right note not first)", ""]
    miss = [r for r in rows if r[1] and r[4] != 1]
    if not miss:
        lines.append("None.")
    for q, ok, kind, got, rank in miss:
        lines.append(f"- [{kind}] {q}  expected {ok}, got {got}")
    bad = [r for r in rows if not r[1] and r[3]]
    if bad:
        lines += ["", "## Out-of-scope questions that returned notes", ""]
        lines += [f"- {q}  got {got}" for q, _, _, got, _ in bad]
    lines += ["", "Questions were written by one person; results show retrieval on these questions only."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if "--method" in sys.argv:
        METHOD = sys.argv[sys.argv.index("--method") + 1]
    if "--min-score" in sys.argv:
        MIN_SCORE = float(sys.argv[sys.argv.index("--min-score") + 1])
    rows = run()
    if "--scores" in sys.argv:
        for q, ok, kind, got, rank in rows:
            print(f"{SCORES.get(q, 0):.3f} [{kind:5}] {'OK ' if rank == 1 else ('-- ' if ok else '   ')}{q}")
    if "--verbose" in sys.argv:
        for q, ok, kind, got, rank in rows:
            print(f"[{kind:5}] rank={rank} expected={ok} got={got}  {q}")
    text = render(rows)
    print(text)
    if "--write" in sys.argv:
        path = sys.argv[sys.argv.index("--write") + 1]
        open(path, "w").write(text)
        print("wrote", path)
