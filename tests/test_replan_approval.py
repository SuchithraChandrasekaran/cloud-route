"""Approving a replan recomputes the capped plan; anything unreadable is refused."""
import pytest

import agent.orchestrator as orch
from agent.orchestrator import _parse_proposed_cap


# ---- reading the model's proposal ----------------------------------------

def test_reads_a_positive_integer():
    resp = '{"parameter": "max_batch_size", "proposed_value": 2, "rationale": "x"}'
    assert _parse_proposed_cap(resp) == (True, 2)


def test_reads_no_cap():
    resp = '{"parameter": "max_batch_size", "proposed_value": "no cap", "rationale": "x"}'
    assert _parse_proposed_cap(resp) == (True, None)


def test_reads_json_wrapped_in_text_and_code_fences():
    resp = 'Here you go:\n```json\n{"parameter": "max_batch_size", "proposed_value": 3}\n```\nDone.'
    assert _parse_proposed_cap(resp) == (True, 3)


@pytest.mark.parametrize("resp", [
    '{"parameter": null, "proposed_value": null, "rationale": "x"}',
    '{"parameter": "max_batch_size", "proposed_value": 0}',
    '{"parameter": "max_batch_size", "proposed_value": -2}',
    '{"parameter": "max_batch_size", "proposed_value": 2.5}',
    '{"parameter": "max_batch_size", "proposed_value": true}',
    '{"parameter": "max_batch_size", "proposed_value": "3"}',
    '{"parameter": "max_batch_size"}',
    '{"parameter": "replicas", "proposed_value": 2}',
    '{"parameter": "max_batch_size", "proposed_value": ',
    'no json at all',
    '',
])
def test_refuses_anything_it_cannot_read_safely(resp):
    assert _parse_proposed_cap(resp) == (False, None)


# ---- the approval prompt, with the model and the keyboard faked ----------

PROPOSAL = '{"parameter": "max_batch_size", "proposed_value": 2, "rationale": "x"}'


def _run_replan(monkeypatch, response, typed):
    monkeypatch.setattr(orch, "build_agent", lambda: object())
    monkeypatch.setattr(orch, "_ask_agent", lambda agent, prompt: response)
    monkeypatch.setattr("builtins.input", lambda prompt="": typed)
    orch.run(source="mock", explain_audience=None,
             replan_priority="fewer components at once")


def test_yes_recomputes_the_capped_plan(monkeypatch, capsys):
    _run_replan(monkeypatch, PROPOSAL, "y")
    out = capsys.readouterr().out
    assert "Recomputed plan with max_batch_size = 2" in out
    assert "Nothing in the cluster has been changed" in out
    recomputed = out.split("Recomputed plan with")[1]
    original = out.split("Recomputed plan with")[0]
    assert recomputed.count("  Phase ") > original.count("  Phase ")


def test_no_changes_nothing(monkeypatch, capsys):
    _run_replan(monkeypatch, PROPOSAL, "n")
    out = capsys.readouterr().out
    assert "Not applied. No changes made." in out
    assert "Recomputed plan" not in out


def test_an_unreadable_proposal_never_reaches_the_prompt(monkeypatch, capsys):
    monkeypatch.setattr(orch, "build_agent", lambda: object())
    monkeypatch.setattr(orch, "_ask_agent",
                        lambda agent, prompt: '{"parameter": "max_batch_size", "proposed_value": -4}')

    def fail_if_asked(prompt=""):
        raise AssertionError("the user should not be asked to approve this")

    monkeypatch.setattr("builtins.input", fail_if_asked)
    orch.run(source="mock", explain_audience=None,
             replan_priority="fewer components at once")
    out = capsys.readouterr().out
    assert "could not be read safely" in out
    assert "Recomputed plan" not in out
