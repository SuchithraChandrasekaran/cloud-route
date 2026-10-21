"""The residency evaluation passes on the real engine and fails on broken ones."""
import pytest

from agent.engine import CloudRouteOptimizer
from agent.evaluate_residency import (
    REGION_POOL, expected_residency, format_report, run_checks, tag_dataset,
)
from agent.evaluation_dataset import EVALUATION_DATASET


def test_the_real_engine_passes_every_check():
    results = run_checks()
    assert results["dataset"]["problems"] == []
    assert results["random"]["failed"] == []


def test_dataset_tagging_rule():
    tagged = tag_dataset(EVALUATION_DATASET)
    assert len(tagged) == len(EVALUATION_DATASET)
    assert "region" not in tagged[0]
    assert tagged[1]["region"] == REGION_POOL[1]
    assert tagged[2]["region"] == REGION_POOL[2]
    assert tagged[3]["region"] == REGION_POOL[0]
    assert "region" not in tagged[7]
    assert all("region" not in c for c in EVALUATION_DATASET)  # original untouched


def test_expected_residency_on_a_hand_built_case():
    comps = [
        {"id": "a", "dependencies": [], "region": "eu-west-1"},
        {"id": "b", "dependencies": ["a"], "region": "us-east-1"},
        {"id": "c", "dependencies": ["b"]},
        {"id": "d", "dependencies": ["a"], "region": "eu-west-1"},
    ]
    assert expected_residency(comps, ["eu-west-1"]) == {
        "out_of_policy": ["b"],
        "cross_region_dependencies": [["a", "b"]],
        "unassigned": ["c"],
    }


def test_random_cases_are_not_trivial():
    rnd = run_checks()["random"]
    for key in ("with_out_of_policy", "with_cross", "with_unassigned",
                "no_policy", "empty_policy"):
        assert rnd[key] > 0, key


class UnassignedAsViolation(CloudRouteOptimizer):
    def check_residency(self, allowed_regions=None):
        r = super().check_residency(allowed_regions)
        r["out_of_policy"] = sorted(set(r["out_of_policy"]) | set(r["unassigned"]))
        return r


class IgnoresCrossRegion(CloudRouteOptimizer):
    def check_residency(self, allowed_regions=None):
        r = super().check_residency(allowed_regions)
        r["cross_region_dependencies"] = []
        return r


class FlagsSameRegionToo(CloudRouteOptimizer):
    def check_residency(self, allowed_regions=None):
        r = super().check_residency(allowed_regions)
        r["cross_region_dependencies"] = sorted([list(e) for e in self.graph.edges])
        return r


class IgnoresPolicy(CloudRouteOptimizer):
    def check_residency(self, allowed_regions=None):
        r = super().check_residency(allowed_regions)
        r["out_of_policy"] = []
        return r


class RegionChangesPlan(CloudRouteOptimizer):
    def calculate_cost_optimized_sequence(self, max_batch_size=None):
        phases, cost = super().calculate_cost_optimized_sequence(max_batch_size)
        if any(self.graph.nodes[n].get("region") for n in self.graph.nodes):
            phases = list(reversed(phases))
        return phases, cost


@pytest.mark.parametrize("broken", [
    UnassignedAsViolation, IgnoresCrossRegion, FlagsSameRegionToo,
    IgnoresPolicy, RegionChangesPlan,
])
def test_broken_engines_are_caught(broken):
    results = run_checks(broken)
    assert results["dataset"]["problems"] or results["random"]["failed"]


def test_report_text():
    text = format_report(run_checks(), "2026-01-01")
    assert "2026-01-01" in text
    assert "200/200" in text
    assert "declared labels" in text
