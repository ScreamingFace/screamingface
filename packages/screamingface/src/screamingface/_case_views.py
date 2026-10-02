"""Derived views of a Case: Answers (and, later, the trace). Never serialized (OME-1289 gap).

INVARIANT: a view reads the Case and its bound operation graph; it never changes either.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from screamingface.answer import Answer

if TYPE_CHECKING:
    from screamingface.case_result import CaseOperation, CaseResult


def case_answers(case: CaseResult, operation_id: str | None) -> tuple[Answer, ...]:
    """Member Answers then the computed Answer of each combine operation, in operation order."""

    if case.operations is None:
        return ()
    if operation_id is not None and all(op.operation_id != operation_id for op in case.operations):
        raise ValueError(f"Case {case.case_id!r} has no operation {operation_id!r}")
    answers: list[Answer] = []
    for operation in case.operations:
        if operation.combine is not None and operation_id in (None, operation.operation_id):
            answers.extend(_operation_answers(case, operation))
    return tuple(answers)


def _operation_answers(case: CaseResult, operation: CaseOperation) -> list[Answer]:
    evidence = operation.combine
    assert evidence is not None
    producers = _producers(case, operation.operation_id)
    answers = [
        Answer(
            member_id=row.member_id,
            text=_output(case, producers[index] if index < len(producers) else None),
            raw=row.raw,
            value=row.value,
            status=row.status,
            reason=row.reason,
            signals=row.signals,
        )
        for index, row in enumerate(evidence.members)
    ]
    result = evidence.result
    answers.append(
        Answer(
            member_id=result.member_id,
            text=operation.output,
            raw=None,
            value=result.value,
            status=result.status,
            reason=result.reason,
            signals={},
        )
    )
    return answers


def _producers(case: CaseResult, operation_id: str) -> tuple[str, ...]:
    graph = case._operation_graph
    if graph is None or operation_id not in graph:
        return ()
    return graph[operation_id].depends_on


def _output(case: CaseResult, operation_id: str | None) -> str | None:
    """The output of that operation; None when unknown (an ambiguous attribution has None)."""

    if operation_id is None or case.operations is None:
        return None
    for operation in case.operations:
        if operation.operation_id == operation_id:
            return operation.output
    return None


__all__: list[str] = []
