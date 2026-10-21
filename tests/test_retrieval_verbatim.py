"""When the failure-mode tool is used, the user sees the notes word for word."""

import pytest

from agent import orchestrator, retrieval


@pytest.fixture(autouse=True)
def _clean():
    retrieval.reset_last()
    retrieval.RETURNED_IDS.clear()
    yield
    retrieval.reset_last()
    retrieval.RETURNED_IDS.clear()


def test_a_match_is_rendered_verbatim_with_the_label_and_id():
    result = retrieval.lookup("dns ttl cached address")
    out = retrieval.render_answer(retrieval.LAST_RESULTS)
    assert out.startswith(retrieval.ANSWER_LABEL)
    passage = result["passages"][0]
    assert passage["text"] in out
    assert f"[{passage['id']}]" in out


def test_no_match_is_the_fixed_sentence_and_nothing_else():
    retrieval.lookup("pizza recipe")
    assert retrieval.render_answer(retrieval.LAST_RESULTS) == "The tool has no note on that topic."


def test_a_repeated_note_is_shown_once():
    retrieval.lookup("dns ttl cached address")
    retrieval.lookup("dns cache ttl")
    assert retrieval.render_answer(retrieval.LAST_RESULTS).count("[fm-04]") == 1


def test_reset_clears_the_record():
    retrieval.lookup("dns ttl cached address")
    retrieval.reset_last()
    assert retrieval.LAST_RESULTS == []


class _FakeAgent:
    pass


def _run_ask(monkeypatch, topic, model_text):
    """Runs the real ask path with a fake model that calls the tool, then rambles."""
    monkeypatch.setattr(orchestrator, "build_agent", lambda: _FakeAgent())

    def fake_ask(agent, prompt):
        if topic is not None:
            retrieval.lookup(topic)
        return model_text

    monkeypatch.setattr(orchestrator, "_ask_agent", fake_ask)
    orchestrator.run("mock", None, None, ask_question="what can go wrong?")


def test_the_models_wording_is_replaced_when_the_tool_was_used(monkeypatch, capsys):
    _run_ask(monkeypatch, "dns ttl cached address", "MODEL PARAPHRASE THAT DRIFTS")
    out = capsys.readouterr().out
    assert "MODEL PARAPHRASE THAT DRIFTS" not in out
    assert "General guidance, not a finding about this cluster:" in out
    assert "[fm-04]" in out
    assert "grounding warning" not in out


def test_no_match_prints_the_fixed_sentence_not_the_models_paragraph(monkeypatch, capsys):
    _run_ask(monkeypatch, "pizza recipe", "A long paragraph about pizza.")
    out = capsys.readouterr().out
    assert "A long paragraph about pizza." not in out
    assert "The tool has no note on that topic." in out


def test_when_the_tool_was_not_used_the_models_answer_is_shown(monkeypatch, capsys):
    _run_ask(monkeypatch, None, "An answer about the plan.")
    assert "An answer about the plan." in capsys.readouterr().out


def test_the_printed_answer_is_clean_for_every_note():
    from agent.nemotron_grounding import (
        find_unsupported_claims,
        find_unverifiable_component_like_tokens,
    )
    for note in retrieval.load_notes():
        result = {"passages": [{"id": note["id"], "title": note["title"], "text": note["text"]}]}
        retrieval.RETURNED_IDS.add(note["id"])
        out = retrieval.render_answer([result])
        assert find_unsupported_claims(out) == [], note["id"]
        assert find_unverifiable_component_like_tokens(out, {"phases": [["a"]]}) == [], note["id"]
        assert retrieval.find_unreturned_citations(out) == [], note["id"]


def test_several_notes_are_shown_in_the_order_they_were_retrieved():
    # a rollback question about a database must surface the rollback note first
    assert retrieval.search("rollback of a database", retrieval.load_notes())[0]["note"]["id"] == "fm-09"

    result = retrieval.lookup("rollback database shared dependency")
    ids = [p["id"] for p in result["passages"]]
    assert ids[0] == "fm-10" and len(ids) >= 2
    out = retrieval.render_answer(retrieval.LAST_RESULTS)
    positions = [out.index(f"[{i}]") for i in ids]
    assert positions == sorted(positions)
