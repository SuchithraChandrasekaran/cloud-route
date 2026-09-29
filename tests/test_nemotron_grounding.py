"""
Grounding tests for the Nemotron explain/re-plan layer.

These tests do NOT call the real Nebius API (no network access in CI, and
no reason to spend real tokens on a unit test). They test the grounding
CHECK logic itself against known-good and known-bad example text, so the
check can be trusted when it's later run against real model output.
"""

from agent.nemotron_grounding import (
    extract_referenced_components,
    find_unsupported_claims,
    find_unverifiable_component_like_tokens,
)

REAL_ENGINE_OUTPUT = {
    "phases": [["Auth-Service", "Core-Database"], ["API-Gateway"], ["Public-Ingress"]],
    "projected_parallel_overhead_heuristic": 1234.5,
}


def test_extract_referenced_components_finds_real_components():
    text = "Phase 1 moves Auth-Service first, then Core-Database."
    found = extract_referenced_components(text, REAL_ENGINE_OUTPUT)
    assert "Auth-Service" in found
    assert "Core-Database" in found


def test_extract_referenced_components_ignores_absent_components():
    text = "Phase 1 moves Auth-Service first."
    found = extract_referenced_components(text, REAL_ENGINE_OUTPUT)
    assert "API-Gateway" not in found


def test_flags_invented_component_name():
    # "Billing-Service" is not in REAL_ENGINE_OUTPUT — this simulates a
    # hallucinated component name an explanation should never contain.
    text = "Phase 1 moves Auth-Service, then the newly discovered Billing-Service."
    unverifiable = find_unverifiable_component_like_tokens(text, REAL_ENGINE_OUTPUT)
    assert "Billing-Service" in unverifiable


def test_does_not_flag_real_components_as_unverifiable():
    text = "Phase 1 moves Auth-Service, then Core-Database, then API-Gateway."
    unverifiable = find_unverifiable_component_like_tokens(text, REAL_ENGINE_OUTPUT)
    assert unverifiable == []


def test_empty_engine_output_flags_everything_component_like():
    text = "The plan moves Ghost-Component first."
    unverifiable = find_unverifiable_component_like_tokens(text, {"phases": []})
    assert "Ghost-Component" in unverifiable


# --- typographic hyphens -----------------------------------------------------

def test_typographic_hyphens_still_match_real_components():
    # The model emitted U+2011 non-breaking hyphens in a real run.
    text = "Phase 1: Auth\u2011Service \u2192 Core\u2011Database"
    found = extract_referenced_components(text, REAL_ENGINE_OUTPUT)
    assert "Auth-Service" in found
    assert "Core-Database" in found


def test_typographic_hyphens_do_not_cause_false_unverifiable_flags():
    text = "Phase 1: Auth\u2011Service then Core\u2011Database."
    assert find_unverifiable_component_like_tokens(text, REAL_ENGINE_OUTPUT) == []


# --- unsupported claims ------------------------------------------------------

def test_flags_drift_from_real_nemotron_output():
    text = (
        "They have the lowest combined cost and can run in parallel with "
        "minimal overhead. The heuristic estimates extra cost from resource "
        "contention, network traffic, or licensing spikes. You could lower it "
        "by splitting a phase."
    )
    hits = find_unsupported_claims(text)
    for expected in ("lowest combined cost", "minimal overhead", "contention",
                     "network traffic", "licensing", "lower it", "splitting a phase"):
        assert expected in hits


def test_grounded_explanation_is_not_flagged():
    text = (
        "The plan has three sequential phases. Within each phase components "
        "are listed cheapest-first. The overhead value, 1970, is a rough "
        "unit-less proxy, not a dollar figure."
    )
    assert find_unsupported_claims(text) == []


def test_unsupported_claim_check_is_case_insensitive_and_hyphen_tolerant():
    text = "Always validate any changes in a Staging\u2011Environment first."
    hits = find_unsupported_claims(text)
    assert "validate any changes" in hits


# --- names ending in digits (regression: Batch-Processor-2 was cut to
# --- "Batch-Processor" and falsely flagged) --------------------------------

MOCK_ENGINE_OUTPUT = {
    "phases": [
        ["Auth-Service", "Core-Database"],
        ["Batch-Processor-2", "API-Gateway", "Batch-Processor-1"],
        ["Public-Ingress"],
    ],
    "projected_parallel_overhead_heuristic": 1970.0,
}


def test_digit_suffixed_component_names_are_not_flagged():
    text = "Phase 2: Batch-Processor-2, API-Gateway, Batch-Processor-1"
    assert find_unverifiable_component_like_tokens(text, MOCK_ENGINE_OUTPUT) == []


def test_invented_digit_suffixed_name_is_still_flagged():
    text = "Phase 2 also includes Batch-Processor-3."
    assert "Batch-Processor-3" in find_unverifiable_component_like_tokens(
        text, MOCK_ENGINE_OUTPUT
    )


# --- title-cased phrases from the tool's own prose (regression: "Parallel-Cost")

ENGINE_OUTPUT_WITH_PROSE = {
    **MOCK_ENGINE_OUTPUT,
    "heuristic_definition": (
        "A rough, unit-less proxy computed by the engine for parallel-cost "
        "overhead. It is not a dollar figure."
    ),
    "ordering_note": "Within each phase, components are listed cheapest-first.",
}


def test_title_cased_phrase_from_tool_prose_is_not_flagged():
    text = "**Projected Parallel\u2011Cost Overhead Heuristic:** 1970.0"
    assert find_unverifiable_component_like_tokens(text, ENGINE_OUTPUT_WITH_PROSE) == []


def test_benign_project_vocabulary_is_not_flagged_even_without_tool_prose():
    text = "Parallel-Cost overhead, listed Cheapest-First."
    assert find_unverifiable_component_like_tokens(text, REAL_ENGINE_OUTPUT) == []


def test_invented_component_still_flagged_when_tool_prose_present():
    text = "Phase 2 also moves Billing-Service and Parallel-Cost tracking."
    assert find_unverifiable_component_like_tokens(
        text, ENGINE_OUTPUT_WITH_PROSE
    ) == ["Billing-Service"]


# --- concurrency claims (regression: real run said "executed together" and
# --- "runs ... concurrently" though the tool never states that) -------------

def test_flags_concurrency_claims_from_real_run():
    text = (
        "Phase 1 includes Auth-Service and Core-Database, executed together. "
        "Phase 2 runs Batch-Processor-2, API-Gateway, and Batch-Processor-1 "
        "concurrently."
    )
    hits = find_unsupported_claims(text)
    assert "executed together" in hits
    assert "concurrent" in hits


def test_parallel_cost_heuristic_name_is_not_a_concurrency_claim():
    text = "The projected parallel-cost overhead heuristic is 1970.0, a rough proxy."
    assert find_unsupported_claims(text) == []


# --- disclaimers are not claims (regression: "the tool does not specify
# --- whether they run together, concurrently, or in parallel" was flagged) ---

def test_disclaimer_about_concurrency_is_not_flagged():
    text = (
        "Components within a phase are ordered cheapest-first, but the tool "
        "does not specify whether they run together, concurrently, or in "
        "parallel."
    )
    assert find_unsupported_claims(text) == []


def test_curly_apostrophe_disclaimer_is_not_flagged():
    text = "The tool doesn\u2019t say whether components run concurrently."
    assert find_unsupported_claims(text) == []


def test_assertion_in_another_sentence_is_still_flagged():
    text = (
        "The tool does not specify execution timing. "
        "Phase 2 runs Batch-Processor-2 and API-Gateway concurrently."
    )
    assert find_unsupported_claims(text) == ["concurrent"]


def test_negation_after_the_phrase_does_not_exempt_it():
    text = "The components run concurrently, which the tool does not confirm."
    assert "concurrent" in find_unsupported_claims(text)


def test_bare_is_not_does_not_exempt_a_cause():
    text = "It is not a dollar figure, and it reflects resource contention."
    assert "contention" in find_unsupported_claims(text)


# --- "should not be interpreted as measuring ..." is a disclaimer ------------

def test_should_not_be_interpreted_disclaimer_is_not_flagged():
    text = (
        "The heuristic value should not be interpreted as measuring specific "
        "factors like resource contention, network traffic, or licensing."
    )
    assert find_unsupported_claims(text) == []


def test_asserted_cause_after_should_sentence_is_still_flagged():
    text = (
        "The value should be treated as a rough proxy. "
        "It is driven by resource contention."
    )
    assert find_unsupported_claims(text) == ["contention"]
