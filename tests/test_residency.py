"""Data-residency checks on the engine."""
import pytest

from agent.engine import CloudRouteOptimizer

EU = "eu-west-1"
US = "us-east-1"


def _opt(components):
    o = CloudRouteOptimizer()
    o.load_blueprint(components)
    return o


def _c(cid, region=None, deps=(), cost=1.0):
    comp = {"id": cid, "daily_cost": cost, "dependencies": list(deps)}
    if region is not None:
        comp["region"] = region
    return comp


def test_flags_components_outside_the_allowed_regions():
    o = _opt([_c("a", EU), _c("b", US), _c("c", EU)])
    result = o.check_residency([EU])
    assert result["out_of_policy"] == ["b"]


def test_cross_region_dependency_is_flagged():
    o = _opt([_c("db", EU), _c("api", US, deps=["db"])])
    result = o.check_residency([EU, US])
    assert result["cross_region_dependencies"] == [["db", "api"]]
    assert result["out_of_policy"] == []


def test_same_region_dependency_is_not_flagged():
    o = _opt([_c("db", EU), _c("api", EU, deps=["db"])])
    assert o.check_residency([EU])["cross_region_dependencies"] == []


def test_unassigned_components_are_reported_not_flagged():
    o = _opt([_c("db", EU), _c("api", deps=["db"])])
    result = o.check_residency([EU])
    assert result["unassigned"] == ["api"]
    assert result["out_of_policy"] == []
    assert result["cross_region_dependencies"] == []


def test_no_policy_still_reports_cross_region_dependencies():
    o = _opt([_c("db", EU), _c("api", US, deps=["db"])])
    result = o.check_residency(None)
    assert result["out_of_policy"] == []
    assert result["cross_region_dependencies"] == [["db", "api"]]


def test_empty_allowed_list_flags_every_assigned_component():
    o = _opt([_c("a", EU), _c("b", US), _c("c")])
    result = o.check_residency([])
    assert result["out_of_policy"] == ["a", "b"]
    assert result["unassigned"] == ["c"]


def test_a_bare_string_policy_is_rejected():
    o = _opt([_c("a", EU)])
    with pytest.raises(ValueError):
        o.check_residency("eu-west-1")


def test_region_does_not_change_the_plan():
    plain = [_c("db"), _c("api", deps=["db"]), _c("web", deps=["api"])]
    tagged = [_c("db", EU), _c("api", US, deps=["db"]), _c("web", EU, deps=["api"])]
    assert (_opt(plain).calculate_cost_optimized_sequence()
            == _opt(tagged).calculate_cost_optimized_sequence())
