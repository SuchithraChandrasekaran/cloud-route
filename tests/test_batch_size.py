"""
Tests for max_batch_size, the engine's one real adjustable parameter.

It caps how many components migrate in the same phase. The key properties:
no cap behaves exactly as before, a cap never breaks dependency order,
and no cap ever scores below the uncapped plan (see test_batch_size_properties.py).
"""

import pytest

from agent.engine import CloudRouteOptimizer


def _components():
    return [
        {"id": "db", "daily_cost": 10.0, "dependencies": []},
        {"id": "auth", "daily_cost": 4.0, "dependencies": []},
        {"id": "cache", "daily_cost": 6.0, "dependencies": []},
        {"id": "api", "daily_cost": 8.0, "dependencies": ["db", "auth"]},
        {"id": "worker", "daily_cost": 2.0, "dependencies": ["db", "cache"]},
        {"id": "ingress", "daily_cost": 3.0, "dependencies": ["api", "worker"]},
    ]


def _optimizer():
    optimizer = CloudRouteOptimizer()
    optimizer.load_blueprint(_components())
    return optimizer


def test_no_cap_matches_the_default_plan():
    optimizer = _optimizer()
    assert optimizer.calculate_cost_optimized_sequence(None) == \
        optimizer.calculate_cost_optimized_sequence()


def test_no_cap_keeps_cheapest_first_generations():
    phases, overhead = _optimizer().calculate_cost_optimized_sequence()
    assert phases == [["auth", "cache", "db"], ["worker", "api"], ["ingress"]]
    # (4+6+10)*3 + (2+8)*2 + 3*1
    assert overhead == 83.0


def test_cap_of_one_gives_one_component_per_phase_in_the_same_order():
    phases, _ = _optimizer().calculate_cost_optimized_sequence(1)
    assert all(len(p) == 1 for p in phases)
    flattened = [c for p in phases for c in p]
    assert flattened == ["auth", "cache", "db", "worker", "api", "ingress"]


def test_cap_of_two_splits_only_the_phase_that_is_too_big():
    phases, _ = _optimizer().calculate_cost_optimized_sequence(2)
    assert phases == [["auth", "cache"], ["db"], ["worker", "api"], ["ingress"]]


def test_cap_larger_than_every_phase_changes_nothing():
    optimizer = _optimizer()
    assert optimizer.calculate_cost_optimized_sequence(10) == \
        optimizer.calculate_cost_optimized_sequence(None)


@pytest.mark.parametrize("cap", [None, 1, 2, 3])
def test_cap_never_breaks_dependency_order(cap):
    optimizer = _optimizer()
    phases, _ = optimizer.calculate_cost_optimized_sequence(cap)
    position = {c: i for i, p in enumerate(phases) for c in p}
    for dependency, dependent in optimizer.graph.edges:
        assert position[dependency] < position[dependent]


def test_capped_plans_never_score_below_the_uncapped_plan():
    optimizer = _optimizer()
    base = optimizer.calculate_cost_optimized_sequence()[1]
    for cap in (5, 3, 2, 1):
        assert optimizer.calculate_cost_optimized_sequence(cap)[1] >= base
    assert optimizer.calculate_cost_optimized_sequence(1)[1] > base   # a real trade-off


@pytest.mark.parametrize("bad", [0, -1, 1.5, "2", True])
def test_invalid_caps_are_rejected(bad):
    with pytest.raises(ValueError):
        _optimizer().calculate_cost_optimized_sequence(bad)


def test_cycle_is_still_reported_as_unsafe_with_a_cap():
    optimizer = CloudRouteOptimizer()
    optimizer.load_blueprint([
        {"id": "a", "daily_cost": 1.0, "dependencies": ["b"]},
        {"id": "b", "daily_cost": 1.0, "dependencies": ["a"]},
    ])
    assert optimizer.calculate_cost_optimized_sequence(2) == ([], 0.0)
