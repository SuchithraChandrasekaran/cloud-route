"""
Tests for the failure-mode retrieval layer.

Retrieval must return the right note for a topic, return nothing for an
unrelated topic, be deterministic, and every note must be safe to quote: it must
not trip the grounding scanner that reads the model's answer.
"""

import pytest

from agent import retrieval
from agent.nemotron_grounding import (
    find_unsupported_claims,
    find_unverifiable_component_like_tokens,
)


@pytest.fixture(autouse=True)
def _clean_returned_ids():
    retrieval.RETURNED_IDS.clear()
    yield
    retrieval.RETURNED_IDS.clear()


def test_twelve_well_formed_notes():
    notes = retrieval.load_notes()
    assert len(notes) == 12
    assert [n["id"] for n in notes] == [f"fm-{i:02d}" for i in range(1, 13)]
    for n in notes:
        assert n["title"] and n["keywords"] and len(n["text"]) > 100


@pytest.mark.parametrize("query, expected", [
    ("a service moved before the database it uses", "fm-01"),
    ("writes lost while data is being copied", "fm-02"),
    ("message queue lost messages", "fm-03"),
    ("dns ttl cached address", "fm-04"),
    ("secrets and credentials missing", "fm-05"),
    ("hidden dependency in an environment variable", "fm-06"),
    ("api version mismatch", "fm-07"),
    ("readiness probe before traffic", "fm-08"),
    ("rolling back a component that holds data", "fm-09"),
    ("blast radius when a shared dependency fails", "fm-10"),
    ("firewall between old and new environments", "fm-11"),
    ("monitoring and alerts", "fm-12"),
])
def test_the_right_note_comes_first(query, expected):
    hits = retrieval.search(query, retrieval.load_notes())
    assert hits, query
    assert hits[0]["note"]["id"] == expected


@pytest.mark.parametrize("query", [
    "pizza recipe", "weather in paris", "", "   ", "the a of", "who is the loan service",
])
def test_unrelated_topics_return_nothing(query):
    result = retrieval.lookup(query)
    assert result["passages"] == []
    assert "no note" in result["note"].lower()


def test_lookup_is_deterministic():
    assert retrieval.lookup("dns ttl cached address") == retrieval.lookup("dns ttl cached address")


def test_every_result_is_labeled_as_general_guidance():
    for q in ("dns ttl cached address", "pizza recipe"):
        label = retrieval.lookup(q)["label"].lower()
        assert "not findings about this cluster" in label


def test_at_most_three_passages():
    assert len(retrieval.lookup("database data service")["passages"]) <= 3


def test_citations_must_be_returned_ids():
    assert retrieval.find_unreturned_citations("see [fm-04]") == ["fm-04"]   # not looked up yet
    retrieval.lookup("dns ttl cached address")
    assert retrieval.find_unreturned_citations("see [fm-04]") == []
    assert retrieval.find_unreturned_citations("see [fm-04] and [fm-99]") == ["fm-99"]
    assert retrieval.find_unreturned_citations("FM-04") == []
    assert retrieval.find_unreturned_citations("no citation here") == []


def test_a_broken_note_is_rejected(tmp_path):
    (tmp_path / "fm-01.md").write_text("id: fm-01\ntitle: x\n\nbody\n")   # no keywords
    with pytest.raises(ValueError, match="keywords"):
        retrieval.load_notes(tmp_path)


def test_duplicate_ids_are_rejected(tmp_path):
    for name in ("fm-01.md", "fm-02.md"):
        (tmp_path / name).write_text("id: fm-01\ntitle: t\nkeywords: k\n\nsome body text\n")
    with pytest.raises(ValueError, match="duplicate"):
        retrieval.load_notes(tmp_path)


def test_quoting_a_note_does_not_trip_the_grounding_scanner():
    for n in retrieval.load_notes():
        quoted = f"{n['title']}. {n['text']} [{n['id']}]"
        assert find_unsupported_claims(quoted) == [], n["id"]
        assert find_unverifiable_component_like_tokens(quoted, {"phases": [["a"]]}) == [], n["id"]
def test_each_note_file_is_valid_and_its_id_matches_its_filename():
    problems = []
    for path in sorted(retrieval.NOTES_DIR.glob("fm-*.md")):
        try:
            note = retrieval._parse(path)
        except ValueError as err:
            problems.append(str(err))
            continue
        if note["id"] != path.stem:
            problems.append(f"{path.name}: the header says id {note['id']}, "
                            f"but the file is named {path.stem}")
    assert not problems, "\n".join(problems)
