"""Extra grounding checks, added after the planted-fault test showed what the first scan misses.

Each check compares the response with the plan the tool returned (`raw`):
  1. unknown_lowercase_names  - a hyphenated lowercase token that looks like a service name
                                (in backticks, or ending in a service word) and is not in the plan.
  2. unknown_numbers          - a number that is not in the tool output and is not a small count.
  3. phase_count_errors       - "N phases" with N larger than the real count, or a "Phase K"
                                that does not exist; a stated total that differs from the real one.
  4. dependency_claims        - "depends on" style claims; the tool returns phases, not edges.

Still NOT checked: a single-word invented name, a wrong claim about which phase a real service
is in, a wrong dependency stated without those words, a claim about cost that uses no number.
These are heuristics tuned on a small set; they are a floor, not a fact-checker.
"""
import math
import re
from typing import Any, Dict, List

from agent.nemotron_grounding import (BENIGN_HYPHENATED_TERMS, _NEGATION_BEFORE,
                                      _SENTENCE_SPLIT, _known_components,
                                      _tool_prose, normalize_text)

SERVICE_WORDS = {"service", "services", "svc", "gateway", "api", "db", "database", "engine",
                 "worker", "proxy", "cache", "queue", "server", "manager", "processor",
                 "scoring", "ledger", "detection", "processing", "servicing", "store", "broker"}
_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_LOWER_TOKEN = re.compile(r"(?<![\w-])[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?![\w-])")
_NUMBER = re.compile(r"(?<![\w.\-])\d[\d,]*(?:\.\d+)?(?![\w\-]|\.\d)")
_DEPENDS = re.compile(r"\b(depends? on|depends? upon|dependency on|dependencies on|relies on)\b")


def _strings_and_numbers(obj, out):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        for m in _NUMBER.finditer(normalize_text(obj)):
            out.append(float(m.group().replace(",", "")))
    elif isinstance(obj, dict):
        for v in obj.values():
            _strings_and_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _strings_and_numbers(v, out)


def _allowed_numbers(raw: Dict[str, Any]) -> set:
    nums: List[float] = []
    _strings_and_numbers({k: v for k, v in raw.items() if k != "phases"}, nums)
    allowed = set()
    for n in nums:
        allowed |= {round(n, 2), round(n, 1), float(math.floor(n)), float(math.ceil(n))}
    phases = raw.get("phases", [])
    n_comp = len(_known_components(raw))
    allowed |= {float(i) for i in range(0, max(n_comp, len(phases)) + 1)}
    return allowed


def _scrub(text: str, raw: Dict[str, Any]) -> str:
    """Remove things that contain digits but are not claims: note ids, component names."""
    text = normalize_text(text)
    text = re.sub(r"\bfm-\d+\b", " ", text, flags=re.I)
    for c in sorted(_known_components(raw), key=len, reverse=True):
        text = text.replace(c, " ")
    return text


def unknown_lowercase_names(text: str, raw: Dict[str, Any]) -> List[str]:
    text = normalize_text(text)
    known = set(_ids_by_name(raw))  # full ids and the bare names inside kind/name ids
    prose = _tool_prose(raw)
    out = set()
    for m in _LOWER_TOKEN.finditer(text):
        tok = m.group()
        if tok in known or tok in BENIGN_HYPHENATED_TERMS or tok in prose or re.fullmatch(r"fm-\d+", tok):
            continue
        in_ticks = text[max(0, m.start() - 1):m.start()] == "`"
        if in_ticks or tok.split("-")[-1] in SERVICE_WORDS:
            out.add(tok)
    return sorted(out)


def unknown_numbers(text: str, raw: Dict[str, Any]) -> List[str]:
    allowed = _allowed_numbers(raw)
    scrubbed = _scrub(text, raw)
    scrubbed = re.sub(r"\bphase\s+\d+\b", " ", scrubbed, flags=re.I)
    bad = set()
    for m in _NUMBER.finditer(scrubbed):
        s = m.group().replace(",", "")
        if float(s) not in allowed:
            bad.add(m.group())
    return sorted(bad)


def phase_count_errors(text: str, raw: Dict[str, Any]) -> List[str]:
    """A stated phase count must match the plan or, in a sentence about batch
    caps, a count the tool returned for some cap."""
    real = len(raw.get("phases", []))
    if not real:
        return []
    cap_counts = {e["phase_count"] for e in (raw.get("batch_size_comparison") or [])
                  if isinstance(e, dict) and isinstance(e.get("phase_count"), int)}
    most = max(cap_counts | {real})
    errs = set()
    pattern = (r"\b(\d+|" + "|".join(_WORD_NUM)
               + r")[\s-](?:migration\s+|safe\s+|separate\s+|distinct\s+)?phases?\b")
    for sentence in _SENTENCE_SPLIT.split(normalize_text(text).lower()):
        about_caps = bool(re.search(r"batch|\bcaps?\b|capped", sentence))
        valid = (cap_counts | {real}) if about_caps else {real}
        for m in re.finditer(r"\bphase\s+(\d+)\b", sentence):
            if int(m.group(1)) > real:
                errs.add(f"Phase {m.group(1)}")
        for m in re.finditer(pattern, sentence):
            n = int(m.group(1)) if m.group(1).isdigit() else _WORD_NUM[m.group(1)]
            before = sentence[max(0, m.start() - 25):m.start()]
            total = bool(re.search(
                r"(there are|there is|total of|in total|across|into|has|have|of)\s*$", before)) or \
                bool(re.match(r"[^.]{0,12}in total", sentence[m.end():]))
            if n > most or (n not in valid and (total or about_caps)):
                errs.add(m.group())
    return sorted(errs)


_CLAUSE_END = re.compile(
    r"\b(?:which|so|because|but|while|whereas|since|therefore|meaning|hence)\b|[;:]")


def _ids_by_name(raw: Dict[str, Any]) -> Dict[str, set]:
    """Every name the text might use for a component, mapped to the real ids."""
    table: Dict[str, set] = {}
    for c in _known_components(raw):
        low = c.lower()
        table.setdefault(low, set()).add(low)
        if "/" in low:
            table.setdefault(low.rsplit("/", 1)[1], set()).add(low)
    return table


def dependency_claims(text: str, raw: Dict[str, Any] | None = None) -> List[str]:
    """Without raw: every dependency statement (the original behaviour).
    With raw: only statements 'X depends on Y' where (X, Y) is not an edge in
    the tool's dependencies map. Negated sentences are skipped."""
    if raw is None:
        hits = []
        for sentence in _SENTENCE_SPLIT.split(normalize_text(text).lower()):
            for m in _DEPENDS.finditer(sentence):
                if not _NEGATION_BEFORE.search(sentence[:m.start()]):
                    hits.append(m.group())
        return sorted(set(hits))

    table = _ids_by_name(raw)
    if not table:
        return []
    mention = re.compile(r"(?<![\w/-])(?:"
                         + "|".join(re.escape(n) for n in sorted(table, key=len, reverse=True))
                         + r")(?![\w-])")
    edges = {(a.lower(), b.lower())
             for a, deps in (raw.get("dependencies") or {}).items() for b in deps}
    bad = set()
    for sentence in _SENTENCE_SPLIT.split(normalize_text(text).lower()):
        marks = [m for m in _DEPENDS.finditer(sentence)
                 if not _NEGATION_BEFORE.search(sentence[:m.start()])]
        if not marks:
            continue
        mentions = [(m.start(), m.end(), m.group()) for m in mention.finditer(sentence)]
        for k, dm in enumerate(marks):
            before = [x for x in mentions if x[1] <= dm.start()]
            if not before:
                continue
            subject = before[-1]
            end = len(sentence)
            if k + 1 < len(marks):
                nxt = marks[k + 1]
                nxt_subject = [x for x in mentions if dm.end() <= x[0] and x[1] <= nxt.start()]
                end = nxt_subject[-1][0] if nxt_subject else nxt.start()
            stop = _CLAUSE_END.search(sentence, dm.end(), end)
            if stop:
                end = stop.start()
            for obj in [x for x in mentions if dm.end() <= x[0] and x[1] <= end]:
                if obj[2] == subject[2]:
                    continue
                if not any((a, b) in edges for a in table[subject[2]] for b in table[obj[2]]):
                    bad.add(f"{subject[2]} depends on {obj[2]}")
    return sorted(bad)


def phase_number_errors(text: str, raw: Dict[str, Any]) -> List[str]:
    """'X is in phase N' must match the plan, numbered from 1. 'Phase 0' is never right.
    A clause that names more than one component or phase number, or that is about
    batch caps, is not judged."""
    phases = raw.get("phases") or []
    if not phases:
        return []
    table = _ids_by_name(raw)
    number = {}
    for i, group in enumerate(phases, start=1):
        for cid in group:
            number[cid.lower()] = i
    mention = None
    if table:
        mention = re.compile(r"(?<![\w/-])(?:"
                             + "|".join(re.escape(n) for n in sorted(table, key=len, reverse=True))
                             + r")(?![\w-])")
    errs = set()
    for sentence in _SENTENCE_SPLIT.split(normalize_text(text).lower()):
        for clause in re.split(r"[;,]|\b(?:and|while|whereas|but)\b", sentence):
            nums = [int(n) for n in re.findall(r"\bphase\s+(\d+)\b", clause)]
            if 0 in nums:
                errs.add("phase 0")
            if len(nums) != 1 or nums[0] == 0 or mention is None:
                continue
            if re.search(r"batch|\bcaps?\b|capped", clause):
                continue
            names = {m.group() for m in mention.finditer(clause)}
            if len(names) != 1:
                continue
            name = names.pop()
            valid = {number[i] for i in table[name] if i in number}
            if valid and nums[0] not in valid:
                errs.add(f"{name} in phase {nums[0]}")
    return sorted(errs)


def find_extra_issues(text: str, raw: Dict[str, Any]) -> Dict[str, List[str]]:
    res = {
        "unknown lowercase names": unknown_lowercase_names(text, raw),
        "numbers not in the tool output": unknown_numbers(text, raw),
        "phase-count errors": phase_count_errors(text, raw),
        "phase-number errors": phase_number_errors(text, raw),
        "dependency claims not in the tool's map": dependency_claims(text, raw),
    }
    return {k: v for k, v in res.items() if v}
