"""The residency tool and the --residency mode."""
import sys

import agent.orchestrator as orch

EU, US = "eu-west-1", "us-east-1"

TAGGED = [
    {"id": "db", "daily_cost": 1.0, "dependencies": [], "region": EU},
    {"id": "api", "daily_cost": 1.0, "dependencies": ["db"], "region": US},
    {"id": "web", "daily_cost": 1.0, "dependencies": ["api"]},
]


def _load_tagged(monkeypatch, allowed):
    monkeypatch.setattr(orch, "MOCK_MIGRATION_BLUEPRINT", TAGGED)
    monkeypatch.setattr(orch, "_active_optimizer", None, raising=False)
    monkeypatch.setattr(orch, "_active_blueprint", None, raising=False)
    orch._load_blueprint("mock")
    monkeypatch.setattr(orch, "_allowed_regions", allowed)


def test_tool_reports_the_engines_facts(monkeypatch):
    _load_tagged(monkeypatch, [EU])
    result = orch.check_data_residency()
    assert result["allowed_regions"] == [EU]
    assert result["out_of_policy"] == ["api"]
    assert result["cross_region_dependencies"] == [["db", "api"]]
    assert result["unassigned"] == ["web"]
    assert result["regions"] == {"api": US, "db": EU}
    assert "not a legal" in result["note"]


def test_tool_without_a_policy_flags_nothing_out_of_policy(monkeypatch):
    _load_tagged(monkeypatch, None)
    result = orch.check_data_residency()
    assert result["allowed_regions"] is None
    assert result["out_of_policy"] == []
    assert result["cross_region_dependencies"] == [["db", "api"]]


def test_tool_without_a_blueprint_returns_an_error(monkeypatch):
    monkeypatch.setattr(orch, "_active_optimizer", None)
    assert orch.check_data_residency() == {"error": "No blueprint loaded."}


def test_residency_mode_prints_facts_and_skips_the_model_without_a_key(monkeypatch, capsys):
    monkeypatch.setattr(orch, "MOCK_MIGRATION_BLUEPRINT", TAGGED)
    monkeypatch.setattr(orch, "_allowed_regions", None)
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)

    def no_model():
        raise AssertionError("the model must not be built without a key")

    monkeypatch.setattr(orch, "build_agent", no_model)
    orch.run_residency("mock", [EU])
    out = capsys.readouterr().out
    assert "Outside the allowed regions: ['api']" in out
    assert "No region annotation: ['web']" in out
    assert "Set NEBIUS_API_KEY" in out


def test_residency_mode_prints_the_models_explanation(monkeypatch, capsys):
    monkeypatch.setattr(orch, "MOCK_MIGRATION_BLUEPRINT", TAGGED)
    monkeypatch.setattr(orch, "_allowed_regions", None)
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    monkeypatch.setattr(orch, "build_agent", lambda: object())
    monkeypatch.setattr(orch, "_ask_agent",
                        lambda agent, prompt: "The api service runs outside the allowed regions.")
    orch.run_residency("mock", [EU])
    out = capsys.readouterr().out
    assert "The api service runs outside the allowed regions." in out


def test_main_splits_the_region_list(monkeypatch):
    seen = {}
    monkeypatch.setattr(orch, "run_residency",
                        lambda source, allowed: seen.update(source=source, allowed=allowed))
    monkeypatch.setattr(sys, "argv",
                        ["x", "--source", "mock", "--residency", " eu-west-1 , eu-central-1 "])
    orch.main()
    assert seen == {"source": "mock", "allowed": ["eu-west-1", "eu-central-1"]}


def test_the_prompt_tells_the_model_about_the_tool():
    assert "check_data_residency" in orch.SYSTEM_PROMPT
    assert "never call it compliant or non-compliant" in orch.SYSTEM_PROMPT
