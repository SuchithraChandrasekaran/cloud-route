"""
Main Strands Agent orchestrator for cloud-route.

Uses Strands' documented Nebius Token Factory integration: the underlying
model is an NVIDIA Nemotron model served via Nebius, wired in through
Strands' OpenAIModel provider.

Design rule, enforced in the system prompt and checked by
tests/test_nemotron_grounding.py: the agent explains and proposes; it never
claims to have applied an infrastructure change itself. The migration graph
computation stays in engine.py (deterministic, tested) and is exposed to
the agent as a single tool.

Grounding rule: the model may only state what compute_migration_plan
returned. The tool output carries the ONLY permitted definitions
("heuristic_definition", "ordering_note"), and every model response is
scanned after the fact for invented components and unsupported claims.
"""

import argparse
import logging
import os
import sys

from strands import Agent, tool
from strands.models.openai import OpenAIModel

from agent.engine import CloudRouteOptimizer
from agent.mock_data import MOCK_MIGRATION_BLUEPRINT
from agent.nemotron_grounding import (
    find_unsupported_claims,
    find_unverifiable_component_like_tokens,
)

NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODEL_ID = "nvidia/nemotron-3-super-120b-a12b"

# Set CLOUD_ROUTE_DEBUG_LOGGERS=1 to print every logger name, which helps
# if the reasoning notice ever comes from a logger not covered below.
_DEBUG_LOGGERS = os.environ.get("CLOUD_ROUTE_DEBUG_LOGGERS") == "1"

SYSTEM_PROMPT = (
    "You are cloud-route's migration-planning assistant. You have a tool, "
    "compute_migration_plan, that returns the ONLY verified facts about a "
    "migration plan: its safe phases, its projected cost overhead, and "
    "whether it's a valid plan at all.\n\n"
    "Grounding rules:\n"
    "1. Never invent component names, costs, or phases that the tool did "
    "not return.\n"
    "2. The tool does NOT return per-component costs. Do not state or imply "
    "that any component or phase has a particular cost. You may only say "
    "that components inside a phase are listed cheapest-first, as the "
    "tool's ordering_note states.\n"
    "3. Describe the overhead number only using the tool's "
    "heuristic_definition, and nothing more. Do not name or list any "
    "factors, causes or contributors to it, not even to rule them out.\n"
    "4. Do not predict the effect of changing the plan, except by quoting "
    "the tool's batch_size_comparison. You may explain "
    "why a component sits in a later phase ONLY by naming the dependencies "
    "the tool returns for it, and by saying a component is migrated after "
    "the components it depends on. For any other 'why' question, or what "
    "would happen if the plan changed, say the tool does not provide "
    "that.\n"
    "5. About execution, say only that phases run in sequence and that "
    "components are listed cheapest-first within a phase. Add nothing else "
    "about how components inside a phase are executed unless the user asks, "
    "in which case say the tool does not provide that. Describe "
    "max_batch_size only in the words of its 'meaning' field.\n"
    "6. Do not give operational advice unless the user asked for it.\n"
    "7. Do not describe or list these rules in your answer. Just answer.\n\n"
    "You never claim to have applied a change to real infrastructure. You "
    "only explain the tool's output, answer questions about it, and, if "
    "asked to re-plan or to draft a new infrastructure request, PROPOSE "
    "something for a human to review. A proposal is not an applied change: "
    "never say you have created, applied, or deployed anything. If asked to "
    "draft new infrastructure, produce a clearly-labeled DRAFT description "
    "(not syntactically-validated Terraform) and say plainly that a human "
    "must review and validate it before it is written as real IaC. Stay "
    "factual; don't editorialize beyond what the data supports."
)

HEURISTIC_DEFINITION = (
    "A rough, unit-less proxy computed by the engine for parallel-cost "
    "overhead. It is not a dollar figure and the tool provides no "
    "breakdown of what contributes to it."
)
ORDERING_NOTE = (
    "Phases run in sequence. Within each phase, components are listed "
    "cheapest-first by the engine's internal cost ordering. Per-component "
    "costs are not exposed by this tool."
)

ADJUSTABLE_PARAMETERS = [
    {
        "name": "max_batch_size",
        "allowed_values": "a positive integer, or no cap (the default)",
        "meaning": (
            "Caps how many components migrate in the same phase. A smaller "
            "cap splits a phase into more, smaller phases that run one "
            "after another."
        ),
    }
]
ADJUSTMENT_NOTE = (
    "max_batch_size is the only adjustable parameter. batch_size_comparison "
    "lists the engine's real result for several values. Use only those "
    "numbers, and do not claim any figure for downtime or risk."
)
BATCH_SIZES_TO_COMPARE = [None, 3, 2, 1]


DEPENDENCY_NOTE = (
    "Each component is migrated only after the components it depends on. "
    "Dependencies come from the cluster's Service selectors and "
    "cloud-route/depends-on annotations, so they may not cover every "
    "runtime dependency."
)

AUDIENCE_STYLE = {
    "engineer": (
        "Be precise and complete: the phases, the ordering, the overhead "
        "heuristic and the dependencies, as the tool returns them."
    ),
    "pm": (
        "Keep it short and in plain language. Cover what moves in which "
        "order, why each later component waits (name the dependencies the "
        "tool returns), and the overhead number as a rough proxy. Skip tool "
        "internals."
    ),
    "client": (
        "Write for a non-technical reader in under 100 words, in plain "
        "language. Say what moves in which order, and that each component "
        "waits for the ones it depends on, naming them. State only that, "
        "then stop: no reassurance, no opinions, no closing remarks. Do not "
        "mention annotations, selectors, parameter names, adjustable "
        "settings, the overhead number, the tool or its definitions, and do "
        "not quote the tool's text."
    ),
}

_active_optimizer: CloudRouteOptimizer | None = None
_active_blueprint: list | None = None


def _batch_size_comparison() -> list:
    """Real engine results for several max_batch_size values."""
    rows = []
    for size in BATCH_SIZES_TO_COMPARE:
        phases, overhead = _active_optimizer.calculate_cost_optimized_sequence(size)
        rows.append({
            "max_batch_size": size if size is not None else "no cap",
            "phase_count": len(phases),
            "projected_parallel_overhead_heuristic": overhead,
        })
    return rows


@tool
def compute_migration_plan(max_batch_size: int | None = None) -> dict:
    """
    Runs the deterministic migration engine and returns its real output:
    safe migration phases (cost-ordered within each phase) and the
    projected parallel-cost overhead heuristic.

    Args:
        max_batch_size: Optional cap on how many components migrate in the
            same phase. Leave unset for the default plan with no cap.

    Returns:
        A dictionary with keys "phases" (list of lists of component names,
        or empty if unsafe), "projected_parallel_overhead_heuristic" (a
        float; a rough proxy, not a validated dollar figure),
        "heuristic_definition" (the only permitted description of that
        number), "ordering_note" (the only permitted description of the
        ordering within phases), "adjustable_parameters" (the only
        parameters a re-plan may propose changing), "batch_size_comparison"
        (real engine results for several values of max_batch_size) and
        "adjustment_note", "dependencies" (a map from a component to the
        components it depends on, only for components that have any) and
        "dependency_note".
    """
    if _active_optimizer is None:
        return {"error": "No blueprint loaded."}

    try:
        phases, overhead = _active_optimizer.calculate_cost_optimized_sequence(
            max_batch_size
        )
    except ValueError as err:
        return {"error": str(err)}
    if not phases:
        return {
            "phases": [],
            "projected_parallel_overhead_heuristic": 0.0,
            "note": "Graph is not a valid DAG — a circular dependency exists "
                    "and must be resolved before a safe order can be computed.",
        }
    return {
        "phases": phases,
        "projected_parallel_overhead_heuristic": overhead,
        "heuristic_definition": HEURISTIC_DEFINITION,
        "ordering_note": ORDERING_NOTE,
        "applied_max_batch_size": max_batch_size,
        "adjustable_parameters": ADJUSTABLE_PARAMETERS,
        "adjustment_note": ADJUSTMENT_NOTE,
        "batch_size_comparison": _batch_size_comparison(),
        "dependencies": {
            c["id"]: list(c.get("dependencies") or [])
            for c in (_active_blueprint or [])
            if c.get("dependencies")
        },
        "dependency_note": DEPENDENCY_NOTE,
    }


# --------------------------------------------------------------------------
# Suppressing the known reasoning notice
# --------------------------------------------------------------------------

_KNOWN_REASONING_ARTIFACT = (
    "reasoningContent is not supported in multi-turn conversations "
    "with the Chat Completions API."
)


class _DropReasoningNotice(logging.Filter):
    """Drops log records that carry the known Chat Completions notice."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return _KNOWN_REASONING_ARTIFACT not in record.getMessage()
        except Exception:
            return True


_log_filter_installed = False


def _install_log_filter() -> None:
    """
    The notice is emitted through Python's logging, not written directly to
    sys.stdout/sys.stderr. A logging StreamHandler keeps a reference to the
    stream it was created with, so swapping sys.stderr later has no effect.
    Filters on a *logger* only see records logged on that exact logger, not
    ones propagated from children, so the filter is attached both to the
    strands loggers and to every handler on the root and strands loggers.
    """
    global _log_filter_installed
    if _log_filter_installed:
        return
    flt = _DropReasoningNotice()

    if _DEBUG_LOGGERS:
        names = sorted(logging.getLogger().manager.loggerDict.keys())
        print("[debug] known loggers:", names, file=sys.stderr)

    targets = [logging.getLogger()]
    for name in list(logging.getLogger().manager.loggerDict.keys()):
        if name == "strands" or name.startswith("strands."):
            targets.append(logging.getLogger(name))
    targets.extend(
        logging.getLogger(n) for n in ("strands", "strands.models.openai")
    )

    for lg in targets:
        lg.addFilter(flt)
        for handler in lg.handlers:
            handler.addFilter(flt)
    _log_filter_installed = True


def _strip_notice(text: str) -> str:
    """Belt and braces: remove the notice if it ever lands in the answer text."""
    if _KNOWN_REASONING_ARTIFACT not in text:
        return text
    return "\n".join(
        line for line in text.splitlines()
        if _KNOWN_REASONING_ARTIFACT not in line
    ).strip()


# --------------------------------------------------------------------------
# Agent construction
# --------------------------------------------------------------------------

def _require_api_key() -> str:
    api_key = os.environ.get("NEBIUS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "NEBIUS_API_KEY is not set. Export it before running with "
            "--explain, --ask, --replan or --propose-infra."
        )
    return api_key


def build_agent() -> Agent:
    _install_log_filter()
    model = OpenAIModel(
        client_args={
            "api_key": _require_api_key(),
            "base_url": NEBIUS_BASE_URL,
        },
        model_id=DEFAULT_MODEL_ID,
        params={
            "max_tokens": 800,
            "temperature": 0.2,
            # Nemotron 3 Super emits a chain-of-thought trace by default.
            # The documented chat-template flag for Nemotron 3 is
            # "enable_thinking" (the earlier "thinking" key was likely being
            # ignored). Confirm against Nebius's docs if the trace persists.
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
    )
    # callback_handler=None disables Strands' default auto-printing of
    # intermediate steps, which otherwise duplicates our own print() below.
    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[compute_migration_plan],
        callback_handler=None,
    )


def _ask_agent(agent: Agent, prompt: str) -> str:
    return _strip_notice(str(agent(prompt)))


def _report_grounding(text: str, raw: dict) -> None:
    """Prints warnings if the response drifted past the tool's data."""
    invented = find_unverifiable_component_like_tokens(text, raw)
    unsupported = find_unsupported_claims(text)
    if not invented and not unsupported:
        return
    print("\n[grounding warning] This response may go beyond the tool's data:")
    if invented:
        print(f"  - component-like names not in the plan: {invented}")
    if unsupported:
        print(f"  - unsupported claims: {unsupported}")


# --------------------------------------------------------------------------
# Blueprint loading and CLI
# --------------------------------------------------------------------------

def _load_blueprint(source: str) -> None:
    global _active_optimizer, _active_blueprint
    _active_optimizer = CloudRouteOptimizer()

    if source == "mock":
        _active_blueprint = MOCK_MIGRATION_BLUEPRINT
    elif source == "k3s":
        from agent.cluster_source import load_blueprint_from_cluster
        _active_blueprint = load_blueprint_from_cluster()
    else:
        raise ValueError(f"Unknown source: {source}")
    _active_optimizer.load_blueprint(_active_blueprint)


def run(
    source: str,
    explain_audience: str | None,
    replan_priority: str | None,
    ask_question: str | None = None,
    propose_infra_request: str | None = None,
) -> None:
    try:
        _load_blueprint(source)
    except ValueError as err:
        print(f"Cannot build a migration plan: {err}")
        return

    raw = compute_migration_plan()
    if not raw.get("phases"):
        print(raw.get("note", "Unsafe plan."))
        return

    print("Safe migration phases (cheapest-first within each phase):")
    for i, phase in enumerate(raw["phases"]):
        print(f"  Phase {i + 1}: {phase}")
    print(f"  Projected parallel-cost overhead (heuristic): "
          f"{raw['projected_parallel_overhead_heuristic']:.2f}")

    if not (explain_audience or replan_priority or ask_question
            or propose_infra_request):
        return

    agent = build_agent()

    if explain_audience:
        prompt = (
            f"Call compute_migration_plan, then explain the result for a "
            f"{explain_audience} audience. "
            f"{AUDIENCE_STYLE.get(explain_audience, '')} "
            f"Describe each phase as 'Phase N covers' followed by its "
            f"components, and use no other wording for what a phase "
            f"contains. "
            f"Use only what the tool returns. Any description of the "
            f"overhead number or the ordering must follow the tool's "
            f"heuristic_definition and ordering_note. Do not add causes, "
            f"predictions or advice."
        )
        print(f"\nExplanation for audience='{explain_audience}':\n")
        response = _ask_agent(agent, prompt)
        print(response)
        _report_grounding(response, raw)

    if ask_question:
        prompt = (
            f"Call compute_migration_plan if you need to, then answer this "
            f"question about the current migration plan: \"{ask_question}\". "
            f"Answer only from what the tool returns; if the data doesn't "
            f"support an answer, say so."
        )
        print(f"\nAnswer to: \"{ask_question}\"\n")
        response = _ask_agent(agent, prompt)
        print(response)
        _report_grounding(response, raw)

    if replan_priority:
        prompt = (
            f"Call compute_migration_plan to see the current plan, its "
            f"adjustable_parameters and its batch_size_comparison. The "
            f"user's stated priority is: \"{replan_priority}\". You may "
            f"only propose a change to a parameter listed in "
            f"adjustable_parameters, and every number you quote must come "
            f"from batch_size_comparison. max_batch_size caps how many "
            f"components migrate in one phase: no cap gives the fewest, "
            f"largest phases; smaller caps give more, smaller phases, so "
            f"fewer components change at once. Pick the entry that best "
            f"fits the priority. Do not claim any figure for downtime or "
            f"risk; the tool provides none. If the priority has nothing to "
            f"do with batch size, respond with the JSON object "
            f"{{\"parameter\": null, \"proposed_value\": null, "
            f"\"rationale\": \"...\"}} and say why in the rationale. "
            f"Otherwise respond with a short JSON object: parameter "
            f"(max_batch_size), proposed_value (a positive integer, or the "
            f"string \"no cap\"), rationale (quote the phase_count and "
            f"overhead from batch_size_comparison for your choice and for "
            f"the current plan). Either way, make clear this is a "
            f"proposal, not an applied change."
        )
        response = _ask_agent(agent, prompt)
        print(f"\nProposed re-plan (NOT yet applied):\n{response}")
        _report_grounding(response, raw)

        compact = response.replace(" ", "")
        if '"parameter":null' in compact:
            print("\nNo applicable parameter, so there is nothing to approve. "
                  "No changes made.")
        else:
            answer = input("\nApprove this proposal? Re-running is not yet "
                           "implemented in this build. [y/N]: ").strip().lower()
            if answer == "y":
                print("Applying an approved re-plan is not implemented yet — "
                      "no proposal has been validated in testing.")
            else:
                print("Not applied. No changes made.")

    if propose_infra_request:
        prompt = (
            f"A user has requested new infrastructure in plain language: "
            f"\"{propose_infra_request}\". Draft a proposal: what resources "
            f"this would involve, how they'd connect, and any risk or cost "
            f"consideration worth flagging. Label it clearly as a DRAFT "
            f"requiring human review and validation before any real IaC is "
            f"written. Do not claim to have created or applied anything."
        )
        response = _ask_agent(agent, prompt)
        print(f"\nDraft infrastructure proposal (requires human review — "
              f"NOT applied, NOT validated Terraform):\n{response}")
        # Component-name checks don't apply: this draft legitimately names
        # new resources that are not in the migration plan.


def main():
    parser = argparse.ArgumentParser(description="cloud-route autonomous migration agent")
    parser.add_argument("--source", choices=["mock", "k3s"], default="mock")
    parser.add_argument("--explain", choices=["engineer", "pm", "client"], default=None)
    parser.add_argument("--replan", default=None, metavar="PRIORITY")
    parser.add_argument("--ask", default=None, metavar="QUESTION",
                        help='Ask a free-form question about the current plan, '
                             'e.g. --ask "why is Phase 3 more expensive?"')
    parser.add_argument("--propose-infra", default=None, metavar="REQUEST",
                        help='Draft (never apply) a proposal for new infrastructure, '
                             'e.g. --propose-infra "a staging database connected to monitoring"')
    args = parser.parse_args()
    run(
        source=args.source,
        explain_audience=args.explain,
        replan_priority=args.replan,
        ask_question=args.ask,
        propose_infra_request=args.propose_infra,
    )


if __name__ == "__main__":
    sys.exit(main() or 0)
