import pytest
from agent.engine import CloudRouteOptimizer
from agent.mock_data import MOCK_MIGRATION_BLUEPRINT


def test_cost_optimized_sequencing_orders_cheapest_first_within_a_generation():
    optimizer = CloudRouteOptimizer()
    optimizer.load_blueprint(MOCK_MIGRATION_BLUEPRINT)

    phases, total_projected = optimizer.calculate_cost_optimized_sequence()

    assert len(phases) > 0
    # Generation 0 has no dependencies: Core-Database ($450) and Auth-Service
    # ($45). Auth-Service should sequence first to reduce its overlap time.
    assert phases[0][0] == "Auth-Service"
    assert phases[0][1] == "Core-Database"


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

    # If API-Gateway fails, only Public-Ingress (which depends on it) should
    # be affected. Core-Database and Auth-Service are upstream and must stay.
    rollback_plan = optimizer.compute_blast_radius_rollback("API-Gateway")

    assert "API-Gateway" in rollback_plan
    assert "Public-Ingress" in rollback_plan
    assert "Core-Database" not in rollback_plan
    assert "Auth-Service" not in rollback_plan


def test_blast_radius_on_unknown_component_returns_empty():
    optimizer = CloudRouteOptimizer()
    optimizer.load_blueprint(MOCK_MIGRATION_BLUEPRINT)
    assert optimizer.compute_blast_radius_rollback("Nonexistent") == []
