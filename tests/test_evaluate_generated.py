"""
Tests for the generated test set: 550 graphs, 11 shapes x 50 seeds.

The engine must pass all of them, and the set must be able to FAIL: each
deliberately broken engine below must be caught.
"""

import pytest

from agent.engine import CloudRouteOptimizer
from agent.evaluate import has_cycle, validate_input
from agent.evaluate_generated import (
    SEEDS_PER_SHAPE,
    SHAPES,
    generate_case,
    render_markdown,
    run_generated,
)


def test_there_are_eleven_shapes_and_550_cases():
    assert len(SHAPES) == 11
    assert len(SHAPES) * SEEDS_PER_SHAPE == 550


@pytest.mark.parametrize("shape", list(SHAPES))
def test_every_generated_graph_is_well_formed(shape):
    for seed in range(1000, 1050):
        comps = generate_case(shape, seed)
        validate_input(comps)          # unique ids, known dependencies, no cycle
        assert not has_cycle(comps)
        assert 5 <= len(comps)


def test_a_case_is_fixed_by_shape_and_seed():
    assert generate_case("layered", 1003) == generate_case("layered", 1003)
    assert generate_case("layered", 1003) != generate_case("layered", 1004)


def test_the_shapes_really_differ():
    chain = generate_case("chain", 1000)
    isolated = generate_case("isolated", 1000)
    assert sum(len(c["dependencies"]) for c in isolated) == 0
    assert sum(len(c["dependencies"]) for c in chain) == len(chain) - 1


@pytest.fixture(scope="module")
def rows():
    return run_generated()


def test_the_engine_passes_every_generated_case(rows):
    assert sum(r["total"] for r in rows) == 550
    for r in rows:
        assert r["passed"] == r["total"], r


def test_the_report_states_its_limits(rows):
    text = render_markdown(rows)
    assert "550/550" in text
    assert "synthetic" in text
    assert "Found while building this set" in text


# --- mutants: broken engines the set must catch ---------------------------

class ReversedPhases(CloudRouteOptimizer):
    def calculate_cost_optimized_sequence(self, max_batch_size=None):
        phases, overhead = super().calculate_cost_optimized_sequence(max_batch_size)
        return list(reversed(phases)), overhead


class DropsAComponent(CloudRouteOptimizer):
    def calculate_cost_optimized_sequence(self, max_batch_size=None):
        phases, overhead = super().calculate_cost_optimized_sequence(max_batch_size)
        if phases and phases[-1]:
            phases[-1] = phases[-1][:-1]
        return phases, overhead


class AcceptsCycles(CloudRouteOptimizer):
    def calculate_cost_optimized_sequence(self, max_batch_size=None):
        phases, overhead = super().calculate_cost_optimized_sequence(max_batch_size)
        if not phases:
            return [list(self.graph.nodes)], 1.0
        return phases, overhead


class RollbackIgnoresDependents(CloudRouteOptimizer):
    def compute_blast_radius_rollback(self, failed_component):
        return [failed_component] if failed_component in self.graph else []


@pytest.mark.parametrize("mutant", [ReversedPhases, DropsAComponent, AcceptsCycles,
                                    RollbackIgnoresDependents])
def test_broken_engines_are_caught(mutant):
    rows = run_generated(mutant, seeds=3)
    assert sum(r["passed"] for r in rows) < sum(r["total"] for r in rows)
