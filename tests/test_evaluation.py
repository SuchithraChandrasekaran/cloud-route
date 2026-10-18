"""
Tests for the evaluation itself.

Two things matter: the engine passes every check on the dataset, and the
checks can actually FAIL. The second part uses deliberately broken engines
(a "mutant" each) to prove the evaluation would notice.
"""

import pytest

from agent.engine import CloudRouteOptimizer
from agent.evaluate import (
    check_blast_radius,
    check_completeness,
    check_cycle_detection,
    check_dependency_order,
    check_phase_placement,
    describe,
    expected_blast_radius,
    expected_levels,
    has_cycle,
    run_checks,
    validate_input,
)
from agent.evaluation_dataset import EVALUATION_DATASET


def test_dataset_has_seventy_components_seven_deployed():
    info = describe(EVALUATION_DATASET)
    assert info["components"] == 70
    assert info["sources"] == {"deployed": 7, "modeled": 63}


def test_dataset_is_well_formed():
    validate_input(EVALUATION_DATASET)   # unique ids, known dependencies, no cycle


def test_deployed_components_match_the_live_cluster_dependencies():
    deployed = {c["id"]: c["dependencies"] for c in EVALUATION_DATASET
                if c["source"] == "deployed"}
    assert deployed["loan-servicing"] == ["account-ledger", "credit-scoring"]
    assert deployed["payment-processing"] == ["account-ledger"]
    for name in ("auth", "account-ledger", "credit-scoring", "fraud-detection",
                 "notification"):
        assert deployed[name] == []


def test_engine_passes_every_check_on_the_dataset():
    for result in run_checks(EVALUATION_DATASET):
        assert result["passed"] == result["total"], result


def test_independent_helpers_agree_with_hand_worked_answers():
    comps = [
        {"id": "a", "daily_cost": 1, "dependencies": []},
        {"id": "b", "daily_cost": 1, "dependencies": ["a"]},
        {"id": "c", "daily_cost": 1, "dependencies": ["a", "b"]},
    ]
    assert expected_levels(comps) == {"a": 0, "b": 1, "c": 2}
    assert expected_blast_radius(comps, "a") == {"a", "b", "c"}
    assert expected_blast_radius(comps, "c") == {"c"}
    assert not has_cycle(comps)
    comps[0]["dependencies"] = ["c"]
    assert has_cycle(comps)


# --- mutants: broken engines the evaluation must catch ---------------------

class ReversedPhases(CloudRouteOptimizer):
    def calculate_cost_optimized_sequence(self, max_batch_size=None):
        phases, overhead = super().calculate_cost_optimized_sequence(max_batch_size)
        return list(reversed(phases)), overhead


class DropsAComponent(CloudRouteOptimizer):
    def calculate_cost_optimized_sequence(self, max_batch_size=None):
        phases, overhead = super().calculate_cost_optimized_sequence(max_batch_size)
        phases = [list(p) for p in phases]
        phases[-1] = phases[-1][1:] if len(phases[-1]) > 1 else phases[-1]
        phases[0] = phases[0][1:]
        return phases, overhead


class MissesDescendants(CloudRouteOptimizer):
    def compute_blast_radius_rollback(self, failed_component):
        return super().compute_blast_radius_rollback(failed_component)[:1]


class IgnoresCycles(CloudRouteOptimizer):
    def calculate_cost_optimized_sequence(self, max_batch_size=None):
        if not self_is_acyclic(self):
            return [[n for n in self.graph.nodes]], 1.0
        return super().calculate_cost_optimized_sequence(max_batch_size)


def self_is_acyclic(optimizer):
    import networkx as nx
    return nx.is_directed_acyclic_graph(optimizer.graph)


def _failed(result):
    return result["passed"] < result["total"]


def test_reversed_phases_are_caught():
    assert _failed(check_dependency_order(EVALUATION_DATASET, ReversedPhases))
    assert _failed(check_phase_placement(EVALUATION_DATASET, ReversedPhases))


def test_a_dropped_component_is_caught():
    assert _failed(check_completeness(EVALUATION_DATASET, DropsAComponent))


def test_an_incomplete_rollback_set_is_caught():
    assert _failed(check_blast_radius(EVALUATION_DATASET, MissesDescendants))


def test_accepting_a_cycle_is_caught():
    assert _failed(check_cycle_detection(EVALUATION_DATASET, IgnoresCycles))


def test_a_malformed_input_graph_is_refused():
    with pytest.raises(ValueError):
        validate_input([{"id": "a", "dependencies": ["missing"]}])
    with pytest.raises(ValueError):
        validate_input([{"id": "a", "dependencies": ["b"]},
                        {"id": "b", "dependencies": ["a"]}])
