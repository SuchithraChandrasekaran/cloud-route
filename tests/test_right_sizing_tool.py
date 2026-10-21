"""The right-sizing facts are wired into the agent, and printed from code."""

import pytest

from agent import orchestrator, right_sizing
from agent.nemotron_grounding import find_unsupported_claims

ROWS = [
    {"name": "deployment/a", "request_cpu_m": 50, "request_mem_mi": 64,
     "usage_cpu_m": 0.017645, "usage_mem_mi": 10.9766},
    {"name": "deployment/b", "request_cpu_m": 50, "request_mem_mi": 64,
     "usage_cpu_m": None, "usage_mem_mi": None},
]


def test_the_tool_returns_the_engines_rows_rounded(monkeypatch):
    monkeypatch.setattr(right_sizing, "workloads_from_cluster", lambda *a, **k: [dict(r) for r in ROWS])
    facts = orchestrator.get_right_sizing()
    assert facts["definition"] == right_sizing.DEFINITION
    assert facts["policy"]["headroom"] == 1.5
    first = facts["workloads"][0]
    assert first["usage_cpu_m"] == 0.02 and first["usage_mem_mi"] == 10.98
    assert first["suggested_cpu_m"] == 10 and first["suggested_mem_mi"] == 32
    assert facts["workloads"][1]["cpu_status"] == "no usage reading"
    assert facts["summary"]["workloads"] == 2


def test_the_tool_reports_an_error_instead_of_raising(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Metrics API not available")
    monkeypatch.setattr(right_sizing, "workloads_from_cluster", boom)
    assert "Metrics API not available" in orchestrator.get_right_sizing()["error"]


def test_the_prompt_limits_what_the_model_may_say():
    p = orchestrator.SYSTEM_PROMPT
    assert "get_right_sizing" in p
    assert "State only numbers the tool returned" in p
    assert "one snapshot" in p


def test_the_mode_prints_the_report_from_code(monkeypatch, capsys):
    monkeypatch.setattr(right_sizing, "workloads_from_cluster", lambda *a, **k: [dict(r) for r in ROWS])
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    orchestrator.run_right_sizing("k3s")
    out = capsys.readouterr().out
    assert "deployment/a: cpu 50m requested, 0.02m measured, 10m suggested" in out
    assert "deployment/b: no usage reading" in out
    assert "Set NEBIUS_API_KEY" in out


def test_the_mode_needs_the_live_cluster(capsys):
    orchestrator.run_right_sizing("mock")
    assert "use --source k3s" in capsys.readouterr().out


@pytest.mark.parametrize("text", [
    "Lowering the requests would give savings.",
    "These requests are wasted.",
    "A smaller request is cheaper and would improve performance.",
])
def test_claims_about_savings_or_waste_are_flagged(text):
    assert find_unsupported_claims(text) != []


def test_the_reports_own_wording_is_not_flagged():
    text = right_sizing.format_report(right_sizing.analyze([
        {"name": "deployment/a", "request_cpu_m": 50, "request_mem_mi": 64,
         "usage_cpu_m": 1, "usage_mem_mi": 10}]))
    assert find_unsupported_claims(text) == []
