"""
The tool says components are LISTED cheapest-first and that phases run in
sequence. It does not say components EXECUTE in that order, or at the same
time. These check that the grounding scan catches that drift but leaves the
tool's own wording alone.
"""

from agent.nemotron_grounding import find_unsupported_claims


def test_flags_components_execute_in_the_order_shown():
    text = "Within each phase, components execute in the order shown."
    assert "execute in the order" in find_unsupported_claims(text)


def test_flags_at_the_same_time():
    text = "The cap controls how many components move at the same time."
    assert "at the same time" in find_unsupported_claims(text)


def test_flags_simultaneously_in_a_batch_size_description():
    text = "max_batch_size controls how many components can migrate simultaneously."
    assert "simultaneous" in find_unsupported_claims(text)


def test_tools_own_wording_is_not_flagged():
    text = (
        "Phases run in sequence. Within each phase, components are listed "
        "cheapest-first. max_batch_size caps how many components migrate in "
        "the same phase."
    )
    assert find_unsupported_claims(text) == []


def test_disclaimer_about_execution_order_is_not_flagged():
    text = "The tool does not say whether components execute in the order shown."
    assert find_unsupported_claims(text) == []
