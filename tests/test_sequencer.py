import pytest
from agent.engine import CloudRouteOptimizer
from agent.mock_data import MOCK_MIGRATION_BLUEPRINT


def test_cost_optimized_sequencing_orders_cheapest_first_within_a_generation():
    optimizer = CloudRouteOptimizer()
    optimizer.load_blueprint(MOCK_MIGRATION_BLUEPRINT)

    phases, total_projected = optimizer.calculate_cost_optimized_sequence()

    assert len(phases) == 2
    # Phase 1 has no dependencies, so it is ordered purely by cost.
    assert phases[0] == [
        "notification", "auth", "fraud-detection", "credit-scoring", "account-ledger",
    ]
    # Phase 2 needs account-ledger (and credit-scoring) to move first.
    assert phases[1] == ["payment-processing", "loan-servicing"]


def test_returns_empty_on_cyclic_graph():
    optimizer = CloudRouteOptimizer()
    optimizer.load_blueprint([
        {"id": "A", "daily_cost": 10, "dependencies": ["B"]},
        {"id": "B", "daily_cost": 10, "dependencies": ["A"]},
    ])
    phases, overhead = optimizer.calculate_cost_optimized_sequence()
    assert phases == []
    assert overhead == 0.0


def test_selective_blast_radius_rollback_isolates_only_downstream_components():
    optimizer = CloudRouteOptimizer()
    optimizer.load_blueprint(MOCK_MIGRATION_BLUEPRINT)

    # If credit-scoring fails, only loan-servicing (which depends on it) is
    # affected. Its siblings and the ledger must stay.
    rollback_plan = optimizer.compute_blast_radius_rollback("credit-scoring")

    assert "credit-scoring" in rollback_plan
    assert "loan-servicing" in rollback_plan
    assert "account-ledger" not in rollback_plan
    assert "payment-processing" not in rollback_plan
    assert "auth" not in rollback_plan


def test_blast_radius_on_unknown_component_returns_empty():
    optimizer = CloudRouteOptimizer()
    optimizer.load_blueprint(MOCK_MIGRATION_BLUEPRINT)
    assert optimizer.compute_blast_radius_rollback("Nonexistent") == []
