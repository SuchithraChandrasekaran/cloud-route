"""Dependency and phase-count checks compare with what the tool returned."""
import pytest

from agent.grounding_checks import dependency_claims, find_extra_issues, phase_count_errors
from agent.grounding_seeded_faults import load_raw


@pytest.fixture(scope="module")
def raw():
    return load_raw()


@pytest.mark.parametrize("text", [
    "payment-processing depends on account-ledger.",
    "Loan-servicing depends on account-ledger and credit-scoring, which is why it is last.",
    "The dependencies show that payment-processing depends on account-ledger, and "
    "loan-servicing depends on account-ledger and credit-scoring, which is why they are later.",
    "Loan-servicing depends on credit-scoring (among others), meaning loan-servicing can only "
    "be migrated after credit-scoring has been migrated.",
    'Answer to: "What depends on auth?"',
    "If account-ledger fails, the components affected are those that depend on it:",
    "- payment-processing depends on account-ledger",
    "Loan-servicing cannot move before credit-scoring because loan-servicing depends on both "
    "account-ledger and credit-scoring.",
])
def test_true_dependency_statements_are_not_flagged(raw, text):
    assert dependency_claims(text, raw) == []


@pytest.mark.parametrize("text, expected", [
    ("payment-processing depends on notification.", ["payment-processing depends on notification"]),
    ("account-ledger depends on payment-processing.", ["account-ledger depends on payment-processing"]),
    ("Loan-servicing depends on auth and credit-scoring.", ["loan-servicing depends on auth"]),
    ("auth depends on fraud-detection.", ["auth depends on fraud-detection"]),
])
def test_wrong_or_invented_dependencies_are_flagged(raw, text, expected):
    assert dependency_claims(text, raw) == expected


def test_negated_dependency_sentences_are_skipped(raw):
    assert dependency_claims("payment-processing does not depend on auth.", raw) == []


def test_without_raw_every_statement_is_reported_as_before():
    assert dependency_claims("a depends on b.") == ["depends on"]


@pytest.mark.parametrize("text", [
    "- Max batch size 3: 3 phases, overhead 2095.0",
    "- max_batch_size=3 -> 3 phases, overhead 2095.0",
    "With a cap of 2 there are 4 phases.",
    "A cap of 1 gives 7 phases.",
    "There are 2 phases.",
])
def test_true_phase_counts_are_not_flagged(raw, text):
    assert phase_count_errors(text, raw) == []


@pytest.mark.parametrize("text", [
    "There are 5 phases in total.",
    "The plan has 3 phases.",
    "With a cap of 2 there are 5 phases.",
    "Phase 3 holds payment-processing.",
    "There are 9 phases.",
])
def test_wrong_phase_counts_are_flagged(raw, text):
    assert phase_count_errors(text, raw) != []


def test_find_extra_issues_no_longer_flags_a_true_dependency_sentence(raw):
    issues = find_extra_issues("payment-processing depends on account-ledger.", raw)
    assert not any(k.startswith("dependency claims") for k in issues)


def test_find_extra_issues_flags_a_wrong_one(raw):
    issues = find_extra_issues("payment-processing depends on notification.", raw)
    assert any(k.startswith("dependency claims") for k in issues)
