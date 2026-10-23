from agent.grounding_checks import (dependency_claims, find_extra_issues, phase_count_errors,
                                    unknown_lowercase_names, unknown_numbers)

RAW = {"phases": [["notification", "auth", "fraud-detection"], ["payment-processing", "loan-servicing"]],
       "projected_parallel_overhead_heuristic": 1930.0,
       "ordering_note": "Within each phase, components are listed cheapest-first.",
       "batch_size_comparison": [{"max_batch_size": 3, "phases": 2, "overhead": 2050.5}]}


def test_lowercase_name():
    assert unknown_lowercase_names("The billing-service must move.", RAW) == ["billing-service"]
    assert unknown_lowercase_names("Move `ledger-sync` too.", RAW) == ["ledger-sync"]
    assert unknown_lowercase_names("payment-processing and cheapest-first, a cost-ordered plan.", RAW) == []
    assert unknown_lowercase_names("a step-by-step, well-known approach", RAW) == []


def test_numbers():
    assert unknown_numbers("It costs 500 per day.", RAW) == ["500"]
    assert unknown_numbers("Overhead is 1,930 or 1930.0; see fm-07; Phase 2 has 2 services.", RAW) == []
    assert unknown_numbers("With cap 3 the overhead is 2050.5 (about 2051).", RAW) == []
    assert unknown_numbers("Region eu-west-1, v2-beta.", RAW) == []


def test_phase_count():
    assert phase_count_errors("There are 3 phases in total.", RAW) == ["3 phases"]
    assert phase_count_errors("Phase 3 comes last.", RAW) == ["Phase 3"]
    assert phase_count_errors("There are two phases.", RAW) == []
    assert phase_count_errors("There are 1 phase in total.", RAW) != []
    assert phase_count_errors("Phase 1 then Phase 2.", RAW) == []
    assert phase_count_errors("the first 2 phases", RAW) == []


def test_dependency():
    assert dependency_claims("The loan-servicing service also depends on auth.") == ["depends on"]
    assert dependency_claims("The tool does not say what it depends on.") == []
    assert dependency_claims("payment-processing waits for auth.") == []


def test_find_extra_issues_clean_and_dirty():
    assert find_extra_issues("Phase 1 covers notification and auth.", RAW) == {}
    dirty = ("The billing-service costs 500. "
             "Payment-processing depends on notification. 3 phases in total.")
    assert len(find_extra_issues(dirty, RAW)) == 4


def test_dependency_checked_against_edges():
    raw = {**RAW, "dependencies": {"payment-processing": ["auth"]}}
    assert dependency_claims("Payment-processing depends on auth.", raw) == []
    assert dependency_claims("Auth depends on payment-processing.", raw) != []
    assert dependency_claims("Payment-processing depends on notification.", raw) != []
