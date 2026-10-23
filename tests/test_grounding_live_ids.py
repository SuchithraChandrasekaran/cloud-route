"""The extra grounding checks work with live-cluster ids (kind/name), not only bare names."""
import pytest

from agent.grounding_checks import (
    dependency_claims, find_extra_issues, phase_number_errors, unknown_lowercase_names,
)
from agent.grounding_seeded_faults import load_raw


@pytest.fixture(scope="module")
def mock_raw():
    return load_raw()


@pytest.fixture(scope="module")
def live(mock_raw):
    raw = dict(mock_raw)
    raw["phases"] = [
        ["service/account-ledger", "service/auth", "service/credit-scoring",
         "service/fraud-detection", "service/loan-servicing", "service/notification",
         "service/payment-processing"],
        ["deployment/account-ledger", "deployment/auth", "deployment/credit-scoring",
         "deployment/fraud-detection", "deployment/notification"],
        ["deployment/payment-processing", "deployment/loan-servicing"],
    ]
    raw["dependencies"] = {
        "deployment/payment-processing": ["service/payment-processing", "deployment/account-ledger"],
        "deployment/loan-servicing": ["service/loan-servicing", "deployment/account-ledger",
                                      "deployment/credit-scoring"],
    }
    raw["batch_size_comparison"] = [
        {"max_batch_size": "no cap", "phase_count": 3,
         "projected_parallel_overhead_heuristic": 15.72}]
    return raw


REAL_ANSWER = (
    "Loan-servicing appears twice: service/loan-servicing is in phase 0, "
    "deployment/loan-servicing is in phase 2.\n"
    'For deployment/loan-servicing, the dependencies returned are: ["service/loan-servicing", '
    '"deployment/account-ledger", "deployment/credit-scoring"].\n'
    "Therefore, deployment/loan-servicing is in the last phase because it must wait for "
    "service/loan-servicing, deployment/account-ledger, and deployment/credit-scoring to "
    "migrate first. No further explanation is provided by the tool."
)


def test_bare_names_inside_live_ids_are_not_unknown(live):
    assert unknown_lowercase_names(REAL_ANSWER, live) == []
    assert unknown_lowercase_names("account-ledger moves first.", live) == []


def test_an_invented_lowercase_name_is_still_flagged_on_live_ids(live):
    assert unknown_lowercase_names("The billing-service runs in the last phase.", live) == ["billing-service"]


def test_the_real_answer_is_flagged_for_its_phase_numbers_only(live):
    errs = phase_number_errors(REAL_ANSWER, live)
    assert "phase 0" in errs
    assert "deployment/loan-servicing in phase 2" in errs
    issues = find_extra_issues(REAL_ANSWER, live)
    assert "unknown lowercase names" not in issues
    assert "phase-number errors" in issues


def test_correct_phase_numbers_are_not_flagged(live):
    text = "service/loan-servicing is in phase 1, deployment/loan-servicing is in phase 3."
    assert phase_number_errors(text, live) == []


def test_a_bare_name_with_two_kinds_accepts_either_phase_but_not_another(live):
    assert phase_number_errors("loan-servicing is in phase 3.", live) == []
    assert phase_number_errors("loan-servicing is in phase 2.", live) == ["loan-servicing in phase 2"]


def test_batch_cap_and_multi_component_clauses_are_not_judged(live):
    assert phase_number_errors("With batch cap 2, auth is in phase 2.", live) == []
    assert phase_number_errors("Phase 1 covers auth and account-ledger.", live) == []


def test_phase_numbers_on_the_mock_plan(mock_raw):
    assert phase_number_errors("payment-processing is in phase 2.", mock_raw) == []
    assert phase_number_errors("payment-processing is in phase 1.", mock_raw) == ["payment-processing in phase 1"]
    assert phase_number_errors("Phase 2 covers payment-processing and loan-servicing.", mock_raw) == []


def test_dependency_check_with_live_ids(live):
    assert dependency_claims("deployment/loan-servicing depends on account-ledger.", live) == []
    assert dependency_claims("deployment/loan-servicing depends on auth.", live) == [
        "deployment/loan-servicing depends on auth"]
