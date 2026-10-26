"""Evaluate one complete Recipe into the shared Candidate Invocation envelope."""

from __future__ import annotations

import functools
import math
from collections.abc import Iterator
from contextlib import nullcontext

from screamingface_engine.benchmarks.contract import (
    CandidateInvocationStatus,
    CorrectiveLoopOutcome,
    OperationOutput,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.failure_classes import benchmark_definition_error
from screamingface_engine.benchmarks.loop_outcomes import (
    capture_loop_outcomes,
    terminal_loop_outcome,
)
from screamingface_engine.benchmarks.operation_outputs import (
    attribute_operation_outputs,
    final_operation_abstained,
    parsed_iterate_body,
)
from screamingface_engine.budget import Budget, case_budgets
from screamingface_engine.model_outcomes import (
    ModelOutcome,
    capture_model_outcomes,
    model_outcome_from_error,
    terminal_model_outcome,
)
from screamingface_engine.operation_calls import (
    capture_operation_calls,
    suspend_request_accounting,
)
from url4.core.errors import ParseError, ResolutionError
from url4.core.nodes import Expression, Iteration, Source, walk
from url4.core.parser import build
from url4.peer.server import Url4Node

# E4c (OME-1291, budget BU-1): the one source that carries a candidate's Budget.
BUDGET_SOURCE = "_sf_budget"
_BUDGET_UNITS = ("usd", "tokens")


async def evaluate_candidate_recipe(
    node: Url4Node,
    expression: str,
    input_text: str,
    *,
    isolated: bool = False,
    isolate_operation_calls: bool = False,
    input_binding: str = "input",
) -> str:
    """Evaluate a Recipe while preserving its exact terminal outcome."""

    budgets = () if isolated else candidate_budgets(expression)
    with case_budgets(budgets), capture_loop_outcomes(isolated=isolated) as executions:
        with capture_model_outcomes(isolated=isolated) as outcomes:
            with capture_operation_calls(isolated=isolated or isolate_operation_calls) as calls:
                accounting_scope = (
                    suspend_request_accounting() if isolate_operation_calls else nullcontext()
                )
                with accounting_scope:
                    try:
                        result = await node.evaluate(expression, env={input_binding: input_text})
                    except ResolutionError as exc:
                        if exc.code != "provider_refusal":
                            raise
                        outcome = model_outcome_from_error(exc)
                        if outcome is None:
                            raise ResolutionError(
                                "provider refusal carried no terminal outcome",
                                code="candidate_contract_error",
                                permanent=True,
                            ) from exc
                        # WHY: members that DID answer before a sibling refused are still
                        # evidence worth retaining — attribution runs on both exits.
                        return _encode(
                            "",
                            outcome,
                            terminal_loop_outcome(executions),
                            status="refused",
                            operations=attribute_operation_outputs(expression, calls),
                        )

    operations = attribute_operation_outputs(expression, calls)
    abstained = final_operation_abstained(expression, operations)
    return _encode(
        # WHY "" (E4b fix, 2026-10-14): an abstained Rank or Filter hands on the empty selection
        # envelope; as the last step, the Case still abstains with the empty answer.
        "" if abstained else result.text,
        terminal_model_outcome(outcomes),
        terminal_loop_outcome(executions),
        operations=operations,
        abstained=abstained,
    )


# WHY cached: every Case and Attempt of one candidate parses the same expression text.
@functools.lru_cache(maxsize=32)
def candidate_budgets(expression: str) -> tuple[Budget, ...]:
    """The Budgets on the candidate's ``_sf_budget`` source, before any call (BU-1, BU-15).

    A budget on any other source, a key other than ``usd`` or ``tokens``, or a cap that is not a
    finite number above zero (a whole number for tokens) is the permanent
    ``benchmark_definition_error`` that names the key, never a value.
    """
    try:
        root = build(expression)
    except ParseError:
        return ()  # the evaluation reports the parse error itself
    if not isinstance(root, Expression):
        return ()
    budgets: tuple[Budget, ...] = ()
    for node in _nodes(root):
        if not isinstance(node, Source) or not node.budgets:
            continue
        if node.name != BUDGET_SOURCE or not any(node is source for source in root.sources):
            raise benchmark_definition_error(
                "a candidate budget sits only on the candidate's _sf_budget source"
            )
        if budgets:
            raise benchmark_definition_error("a candidate has one _sf_budget source")
        budgets = tuple(_budget(key, value) for key, value in node.budgets)
    return budgets


def _nodes(root: Expression) -> Iterator[object]:
    """Every node of ``root`` and of each iterate body in it: a Gate branch body is an iterate
    template, so a budget on a source inside it is stray too (BU-15)."""

    for node in walk(root):
        yield node
        if isinstance(node, Iteration) and (body := parsed_iterate_body(node)) is not None:
            yield from _nodes(body)


def _budget(key: str, value: object) -> Budget:
    if key not in _BUDGET_UNITS:
        raise benchmark_definition_error(f"a candidate budget has an unknown key {key!r}")
    try:
        cap = float(str(value))
    except ValueError as exc:
        raise benchmark_definition_error(f"the candidate budget {key} is not a number") from exc
    if not math.isfinite(cap) or cap <= 0 or (key == "tokens" and not cap.is_integer()):
        raise benchmark_definition_error(f"the candidate budget {key} is not a valid cap")
    return Budget(unit="usd" if key == "usd" else "tokens", cap=cap)


def _encode(
    output: str,
    outcome: ModelOutcome,
    execution: CorrectiveLoopOutcome | None,
    *,
    status: CandidateInvocationStatus | None = None,
    operations: list[OperationOutput] | None = None,
    abstained: bool = False,
) -> str:
    try:
        return encode_candidate_invocation(
            output,
            outcome.finish_reason,
            outcome.refusal,
            execution,
            status=status,
            operations=operations,
            abstained=abstained,
        )
    except ValueError as exc:
        raise ResolutionError(
            str(exc),
            code="candidate_contract_error",
            permanent=True,
        ) from exc


__all__ = ["evaluate_candidate_recipe"]
