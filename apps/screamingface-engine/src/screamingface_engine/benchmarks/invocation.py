"""Evaluate one complete Recipe into the shared Candidate Invocation envelope."""

from __future__ import annotations

from screamingface_engine.benchmarks.candidate_execution import (
    capture_candidate_executions,
    terminal_candidate_execution,
)
from screamingface_engine.benchmarks.contract import (
    CandidateInvocationStatus,
    CorrectiveExecution,
    OperationOutput,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.operation_outputs import attribute_operation_outputs
from screamingface_engine.model_outcomes import (
    ModelOutcome,
    capture_model_outcomes,
    model_outcome_from_error,
    terminal_model_outcome,
)
from screamingface_engine.operation_calls import capture_operation_calls
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node


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

    with capture_candidate_executions(isolated=isolated) as executions:
        with capture_model_outcomes(isolated=isolated) as outcomes:
            with capture_operation_calls(isolated=isolated or isolate_operation_calls) as calls:
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
                        terminal_candidate_execution(executions),
                        status="refused",
                        operations=attribute_operation_outputs(expression, calls),
                    )

    return _encode(
        result.text,
        terminal_model_outcome(outcomes),
        terminal_candidate_execution(executions),
        operations=attribute_operation_outputs(expression, calls),
    )


def _encode(
    output: str,
    outcome: ModelOutcome,
    execution: CorrectiveExecution | None,
    *,
    status: CandidateInvocationStatus | None = None,
    operations: list[OperationOutput] | None = None,
) -> str:
    try:
        return encode_candidate_invocation(
            output,
            outcome.finish_reason,
            outcome.refusal,
            execution,
            status=status,
            operations=operations,
        )
    except ValueError as exc:
        raise ResolutionError(
            str(exc),
            code="candidate_contract_error",
            permanent=True,
        ) from exc


__all__ = ["evaluate_candidate_recipe"]
