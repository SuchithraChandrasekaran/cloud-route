"""The lookup tool is wired into the orchestrator and its citations are checked."""

from agent import orchestrator, retrieval


def setup_function(_):
    retrieval.RETURNED_IDS.clear()


def test_the_tool_returns_the_right_note():
    result = orchestrator.lookup_failure_modes("dns ttl cached address")
    assert result["passages"][0]["id"] == "fm-04"
    assert "not findings about this cluster" in result["label"].lower()


def test_the_prompt_says_notes_are_general_guidance_and_must_be_cited():
    p = orchestrator.SYSTEM_PROMPT
    assert "lookup_failure_modes" in p
    assert "not findings about this cluster" in p
    assert "Cite only ids the tool returned" in p


def test_a_citation_the_tool_did_not_return_is_flagged(capsys):
    raw = {"phases": [["a"]]}
    orchestrator._report_grounding("This can happen [fm-99].", raw)
    out = capsys.readouterr().out
    assert "grounding warning" in out and "fm-99" in out


def test_a_returned_citation_is_not_flagged(capsys):
    orchestrator.lookup_failure_modes("dns ttl cached address")
    orchestrator._report_grounding("Caching can delay a cutover [fm-04].", {"phases": [["a"]]})
    assert "fm-99" not in capsys.readouterr().out
    assert "did not return" not in capsys.readouterr().out
