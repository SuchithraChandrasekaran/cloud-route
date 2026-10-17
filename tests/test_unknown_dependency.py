"""
A dependency on a component that doesn't exist must be a clear error, not a
KeyError crash deep inside the sequencer. For a tool that decides migration
order, silently dropping the dependency would be worse, so it raises.
"""

import pytest

from agent.engine import CloudRouteOptimizer


def _components():
    return [
        {"id": "deployment/loan", "type": "Deployment", "daily_cost": 5.0,
         "dependencies": ["deployment/credit-scorng"]},  # typo on purpose
        {"id": "deployment/credit-scoring", "type": "Deployment",
         "daily_cost": 3.0, "dependencies": []},
    ]


def test_unknown_dependency_raises_value_error():
    optimizer = CloudRouteOptimizer()
    with pytest.raises(ValueError):
        optimizer.load_blueprint(_components())


def test_error_names_both_components():
    optimizer = CloudRouteOptimizer()
    with pytest.raises(ValueError) as excinfo:
        optimizer.load_blueprint(_components())
    message = str(excinfo.value)
    assert "deployment/loan" in message
    assert "deployment/credit-scorng" in message


def test_valid_dependency_still_sequences_correctly():
    components = _components()
    components[0]["dependencies"] = ["deployment/credit-scoring"]
    optimizer = CloudRouteOptimizer()
    optimizer.load_blueprint(components)
    phases, _ = optimizer.calculate_cost_optimized_sequence()
    assert phases == [["deployment/credit-scoring"], ["deployment/loan"]]
