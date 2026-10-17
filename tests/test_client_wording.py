"""
Real drift from a client-audience run: sentences the tool never supports.
The tool only says components share a phase, not that they move together or
at once, and it never says anything about smoothness or doing things one at
a time.
"""

from agent.nemotron_grounding import find_unsupported_claims


def test_flags_moving_together():
    text = "First we move Auth-Service and Core-Database together."
    assert "together" in find_unsupported_claims(text)


def test_flags_reassurance():
    text = "This order keeps things running smoothly while updating pieces step by step."
    assert "smoothly" in find_unsupported_claims(text)


def test_flags_invented_comparison_with_one_at_a_time():
    text = "The parallel work adds extra effort compared to doing everything one at a time."
    assert "one at a time" in find_unsupported_claims(text)


def test_flags_self_certification():
    text = "All statements come directly from the engine's output."
    assert "come directly from" in find_unsupported_claims(text)


def test_flags_batch_size_described_as_at_once():
    text = "Changing how many items move at once would change the step count."
    assert "at once" in find_unsupported_claims(text)


def test_grounded_client_sentences_are_not_flagged():
    text = (
        "Auth-Service and Core-Database move first, because nothing else "
        "has to happen before them. Batch-Processor-2, API-Gateway and "
        "Batch-Processor-1 follow once Core-Database is done, and API-Gateway "
        "also waits for Auth-Service. Public-Ingress moves last, after API-Gateway."
    )
    assert find_unsupported_claims(text) == []
