"""The right-sizing evaluation passes on the engine, and fails on wrong versions."""

from fractions import Fraction

import pytest

from agent import right_sizing as rs
from agent.evaluate_right_sizing import (
    CASES,
    CHECKS,
    expected,
    render_markdown,
    run_checks,
)


def _ceil(x: Fraction) -> int:
    return -(-x.numerator // x.denominator)


# wrong versions of the rule
def no_floor(u, h=rs.HEADROOM):
    return _ceil(Fraction(u) * h / 10) * 10


def rounds_down(u, h=rs.HEADROOM):
    return max(10, int(Fraction(u) * h / 10) * 10)


def no_headroom(u, h=rs.HEADROOM):
    return max(10, _ceil(Fraction(u) / 10) * 10)


def off_by_a_step(u, h=rs.HEADROOM):
    return rs.suggest_cpu_m(u, h) + 10


def test_the_engine_passes_every_check():
    for r in run_checks():
        assert r["passed"] == r["total"], r


def test_there_are_seven_checks_and_the_main_ones_use_1000_cases():
    assert len(CHECKS) == 7
    results = run_checks()
    assert results[0]["total"] == 2 * CASES


def test_the_independent_helper_agrees_with_hand_worked_answers():
    assert expected(Fraction(7), 3, 2, 10, 10) == 20
    assert expected(Fraction(20), 3, 2, 10, 10) == 30
    assert expected(Fraction(0), 3, 2, 10, 10) == 10
    assert expected(Fraction(10), 3, 2, 32, 16) == 32
    assert expected(Fraction(40), 3, 2, 32, 16) == 64


@pytest.mark.parametrize("wrong", [no_floor, rounds_down, no_headroom, off_by_a_step])
def test_wrong_versions_of_the_rule_are_caught(wrong):
    results = run_checks(cpu_fn=wrong, mem_fn=rs.suggest_mem_mi)
    assert any(r["passed"] < r["total"] for r in results)


def test_a_wrong_memory_rule_is_caught_too():
    results = run_checks(cpu_fn=rs.suggest_cpu_m, mem_fn=lambda u, h=rs.HEADROOM: rs.suggest_mem_mi(u, h) + 16)
    assert any(r["passed"] < r["total"] for r in results)


def test_a_wrong_parser_is_caught(monkeypatch):
    monkeypatch.setattr(rs, "parse_cpu_millicores", lambda t: Fraction(0))
    assert any(r["name"].startswith("Quantities") and r["passed"] < r["total"] for r in run_checks())


def test_the_report_states_its_limits():
    text = render_markdown(run_checks())
    assert "does not show the rule is a good one" in text
    assert "does not show that following a suggestion saves money" in text
    assert "not peak usage" in text
    assert "docs/right-sizing-live-check.md" in text
