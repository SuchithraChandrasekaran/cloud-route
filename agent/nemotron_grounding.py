"""
Grounding-check utilities for cloud-route's Nemotron layer.

The actual model-calling logic lives in orchestrator.py's Strands Agent
(compute_migration_plan tool + system prompt). This module holds the
grounding checks used by tests/test_nemotron_grounding.py and by the
orchestrator's post-response warning:

  * component checks: does a response only reference components that
    actually appear in the engine's real output?
  * unsupported-claim check: does a response contain phrases that assert
    causes, costs or predictions the tool never supplied?

These are coarse checks, not formal proofs of groundedness. They catch
invented component names and a known list of drift phrases, not subtler
misrepresentation (e.g. a correct component name with a wrong cost
attached), so read them as one signal among several.
"""

import re
from typing import Any, Dict, List

# Models often emit typographic hyphens (e.g. U+2011 non-breaking hyphen) in
# names like "Auth‑Service". Normalize so those still match real components.
_HYPHEN_VARIANTS = "\u2010\u2011\u2012\u2013\u2014\u2212"
_HYPHEN_TABLE = {ord(c): "-" for c in _HYPHEN_VARIANTS}
_HYPHEN_TABLE.update({0x2019: "'", 0x2018: "'"})

# Phrases that indicate the model went past the tool's data. Matched
# case-insensitively after hyphen normalization. Extend as new drift appears.
UNSUPPORTED_PHRASES = [
    "contention",
    "licensing",
    "network traffic",
    "lowest combined cost",
    "lowest total cost",
    "minimal overhead",
    "less overhead",
    "reduce the overhead",
    "lower the overhead",
    "lower it",
    "splitting a phase",
    "split a phase",
    "moving one component",
    "concurrent",
    "simultaneous",
    "in parallel",
    "executed together",
    "migrated together",
    "run together",
    "runs together",
    "execute in the order",
    "together",
    "at once",
    "smoothly",
    "one at a time",
    "come directly from",
    "comes directly from",
    "execute in order",
    "at the same time",
    "validate any changes",
    "staging environment",
    "savings",
    "save money",
    "saves money",
    "wasted",
    "wasteful",
    "cheaper",
    "reduce costs",
    "reduce the cost",
    "lower costs",
    "lower the cost",
    "improve performance",
    "better performance",
]


def normalize_text(text: str) -> str:
    """Replaces typographic hyphen variants with an ASCII hyphen."""
    return text.translate(_HYPHEN_TABLE)


# Hyphenated terms that belong to this project's own vocabulary and are not
# component names. Compared case-insensitively.
BENIGN_HYPHENATED_TERMS = {
    "parallel-cost",
    "cost-ordered",
    "cost-optimized",
    "cheapest-first",
    "unit-less",
    "per-component",
    "non-breaking",
}


def _tool_prose(engine_output: Dict[str, Any]) -> str:
    """
    Lowercased, hyphen-normalized text of every string the tool returned
    other than component lists (e.g. heuristic_definition, ordering_note,
    note). A hyphenated phrase that appears in the tool's own prose is
    grounded, even if the model re-cased it as "Parallel-Cost".
    """
    parts = [
        v for k, v in engine_output.items()
        if k != "phases" and isinstance(v, str)
    ]
    return normalize_text(" ".join(parts)).lower()


def _known_components(engine_output: Dict[str, Any]) -> set:
    return {
        component
        for phase in engine_output.get("phases", [])
        for component in phase
    }


def extract_referenced_components(text: str, engine_output: Dict[str, Any]) -> List[str]:
    """Returns which real component names (from engine_output) appear in text."""
    text = normalize_text(text)
    referenced = []
    for phase in engine_output.get("phases", []):
        for component in phase:
            if component in text:
                referenced.append(component)
    return referenced


def find_unverifiable_component_like_tokens(text: str, engine_output: Dict[str, Any]) -> List[str]:
    """
    A coarse heuristic: looks for capitalized hyphenated tokens in `text`
    (the shape real component names take in this project, e.g.
    "Core-Database") that do NOT appear anywhere in engine_output. This
    catches the most likely form of a hallucinated component name; it is
    not a general-purpose fact-checker and will miss inventions that don't
    match this naming pattern. Hyphenated phrases that appear in the tool's
    own prose (heuristic_definition, ordering_note) or in
    BENIGN_HYPHENATED_TERMS are not treated as invented. Segments after a hyphen may start with a
    capital letter or a digit, so names like "Batch-Processor-2" match whole.
    """
    text = normalize_text(text)
    candidate_pattern = re.compile(r"\b[A-Z][a-zA-Z0-9]*(?:-[A-Z0-9][a-zA-Z0-9]*)+\b")
    candidates = set(candidate_pattern.findall(text))
    prose = _tool_prose(engine_output)
    unverifiable = {
        c for c in candidates - _known_components(engine_output)
        if c.lower() not in BENIGN_HYPHENATED_TERMS and c.lower() not in prose
    }
    return sorted(unverifiable)


# A phrase is treated as a disclaimer, not a claim, when one of these appears
# earlier in the same sentence (e.g. "the tool does not specify whether they
# run concurrently"). Deliberately narrow: bare "is not" is excluded because
# "it is not a dollar figure, and contention adds cost" must still be flagged.
_NEGATION_BEFORE = re.compile(
    r"\b(does not|doesn't|do not|don't|did not|not specify|not state|not say|"
    r"not provide|not indicate|not expose|not confirm|no information|no data|"
    r"cannot|can't|unknown|unclear|not known|should not|shouldn't|"
    r"not be interpreted|not measure|not measuring|not a measure of)\b"
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def find_unsupported_claims(text: str) -> List[str]:
    """
    Returns the UNSUPPORTED_PHRASES found in `text` as claims. A hit means
    the model asserted something (a cause, a cost, a prediction, or
    unrequested advice) that compute_migration_plan never returned.

    A phrase is not counted when a negation/disclaimer marker precedes it in
    the same sentence ("the tool does not specify whether they run
    concurrently"). A negation that comes AFTER the phrase does not exempt
    it ("they run concurrently, which the tool does not confirm" is still
    flagged): the check errs toward flagging.
    """
    hits: List[str] = []
    for sentence in _SENTENCE_SPLIT.split(normalize_text(text).lower()):
        for phrase in UNSUPPORTED_PHRASES:
            if phrase in hits:
                continue
            start = 0
            while True:
                idx = sentence.find(phrase, start)
                if idx == -1:
                    break
                if not _NEGATION_BEFORE.search(sentence[:idx]):
                    hits.append(phrase)
                    break
                start = idx + len(phrase)
    return [p for p in UNSUPPORTED_PHRASES if p in hits]
