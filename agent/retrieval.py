"""
Retrieval over short failure-mode notes (docs/failure-modes/*.md).

The notes are GENERAL guidance about what can go wrong in a migration. They
are not findings about any particular cluster, and every result says so.

Retrieval is plain BM25 keyword scoring in pure Python: no embeddings, no
extra dependencies, no API calls. The same query always returns the same
passages, so it can be tested exactly, and a reader can see why a note matched.

The model may state a failure mode only by using a returned note, and cite it
by id (for example [fm-03]). find_unreturned_citations() flags any cited id that
the tool did not return in this run.
"""

import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

NOTES_DIR = Path(__file__).resolve().parent.parent / "docs" / "failure-modes"

LABEL = ("General guidance about migrations. These notes are not findings "
         "about this cluster or its components.")
NO_MATCH = ("No note matches this topic. Say that the tool has no note on it. "
            "Do not answer from general knowledge.")

K1 = 1.5
B = 0.75
MIN_SCORE = 4.0          # below this the best note is not a real match
RELATIVE_CUTOFF = 0.5    # other notes must score at least this share of the best
MAX_RESULTS = 3
# Hybrid retrieval (BM25 + embeddings). Off unless a caller switches it on, so
# tests never touch the network. Cutoff chosen from the gap between in-scope
# and off-topic scores in evaluate_retrieval (see RESULTS_RETRIEVAL.md).
USE_EMBEDDINGS = False
# The user's own question while one is being answered; lookup() searches with it
# because the model's shortened topic can drop words that matter.
QUESTION: Optional[str] = None
EMBED_MIN_SCORE = 0.45

_STOPWORDS = frozenset(
    "a an and are as at be but by can do does for from has have how if in into is it its "
    "of on or so than that the their then there these they this to was we what when where "
    "which while who why will with would you your about after before during".split())
_CITATION = re.compile(r"\bfm-\d{2}\b", re.IGNORECASE)

# ids returned by lookup() in this process
RETURNED_IDS: set = set()

# results of lookup() calls since the last reset_last(); the orchestrator prints
# these verbatim instead of the model's wording
LAST_RESULTS: list = []

NO_NOTE_ANSWER = "The tool has no note on that topic."
ANSWER_LABEL = "General guidance, not a finding about this cluster:"


def reset_last() -> None:
    LAST_RESULTS.clear()


def render_answer(results: list) -> str:
    """The answer printed to the user: the retrieved notes, word for word, or the
    fixed no-match sentence. No model wording is involved."""
    seen, blocks = set(), []
    for result in results:
        for p in result.get("passages", []):
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            blocks.append(f"{p['title']} [{p['id']}]\n{p['text']}")
    if not blocks:
        return NO_NOTE_ANSWER
    return ANSWER_LABEL + "\n\n" + "\n\n".join(blocks)


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> List[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())
            if w not in _STOPWORDS]


def _parse(path: Path) -> Dict[str, str]:
    header, _, body = path.read_text().partition("\n\n")
    fields = {}
    for line in header.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    for required in ("id", "title", "keywords"):
        if not fields.get(required):
            raise ValueError(f"{path.name}: missing '{required}' in the header")
    if not body.strip():
        raise ValueError(f"{path.name}: the note has no text")
    return {"id": fields["id"], "title": fields["title"],
            "keywords": fields["keywords"], "text": body.strip()}


def load_notes(directory: Optional[Path] = None) -> List[Dict[str, str]]:
    directory = Path(directory) if directory else NOTES_DIR
    notes = [_parse(p) for p in sorted(directory.glob("fm-*.md"))]
    ids = [n["id"] for n in notes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate note ids")
    return notes


def _doc_tokens(note: Dict[str, str]) -> List[str]:
    # the title and keywords describe the note, so they count for more than the body
    return (tokenize(note["title"]) * 2 + tokenize(note["keywords"]) * 3
            + tokenize(note["text"]))


def search(query: str, notes: List[Dict[str, str]]) -> List[Dict]:
    """Returns [{"note": ..., "score": ...}] best first, only real matches."""
    terms = set(tokenize(query))
    if not terms or not notes:
        return []
    docs = [Counter(_doc_tokens(n)) for n in notes]
    lengths = [sum(d.values()) for d in docs]
    avg = sum(lengths) / len(lengths)
    scored = []
    for note, doc, length in zip(notes, docs, lengths):
        score = 0.0
        for term in terms:
            tf = doc.get(term, 0)
            if not tf:
                continue
            df = sum(1 for d in docs if term in d)
            idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
            score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / avg))
        scored.append({"note": note, "score": round(score, 4)})
    scored.sort(key=lambda r: (-r["score"], r["note"]["id"]))
    best = scored[0]["score"]
    if best < MIN_SCORE:
        return []
    return [r for r in scored if r["score"] >= max(MIN_SCORE, best * RELATIVE_CUTOFF)][:MAX_RESULTS]


def _find(topic: str, notes: list, directory: Optional[Path]) -> list:
    """Hybrid search when enabled; BM25 if disabled, a custom directory, or any error."""
    query = QUESTION or topic
    if USE_EMBEDDINGS and directory is None:
        try:
            from agent import embed_retrieval as er
            index = er.build_index(notes)
            pairs = er.search_hybrid(query, notes, index, min_score=EMBED_MIN_SCORE)
            return [{"note": n, "score": round(s, 4)} for n, s in pairs]
        except Exception:
            pass
    return search(query, notes)


def lookup(topic: str, directory: Optional[Path] = None) -> Dict:
    """The tool result: matching notes with their ids, or an explicit no-match."""
    notes = load_notes(directory)
    hits = _find(topic, notes, directory)
    for h in hits:
        RETURNED_IDS.add(h["note"]["id"].lower())
    if not hits:
        result = {"topic": topic, "label": LABEL, "passages": [], "note": NO_MATCH}
        LAST_RESULTS.append(result)
        return result
    result = {
        "topic": topic,
        "label": LABEL,
        "passages": [{"id": h["note"]["id"], "title": h["note"]["title"],
                      "text": h["note"]["text"]} for h in hits],
        "note": "Cite a note by its id in square brackets, for example [fm-03].",
    }
    LAST_RESULTS.append(result)
    return result


def find_unreturned_citations(text: str) -> List[str]:
    """Ids cited in the text that lookup() did not return in this process."""
    cited = {m.group(0).lower() for m in _CITATION.finditer(text)}
    return sorted(cited - RETURNED_IDS)
