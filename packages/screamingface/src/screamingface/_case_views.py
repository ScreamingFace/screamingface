"""Derived views of a Case: Answers and the trace. Never serialized (OME-1289 gap).

INVARIANT: a view reads the Case and its bound operation graph; it never changes either.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING

from screamingface._signals import JUDGE_SIGNAL
from screamingface.answer import Answer
from screamingface.report_trace import TraceEntry

if TYPE_CHECKING:
    from screamingface.case_result import CaseOperation, CaseResult
    from screamingface.combine_evidence import CombineEvidence
    from screamingface.operation import OperationInfo
    from screamingface.operation_accounting import OperationAccounting, OperationCache


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


# --- the trace -----------------------------------------------------------------------------------

_EMPTY_FIELDS = ("provider", "model", "cost_usd", "latency_ms", "tokens_in", "tokens_out")
_UNTRACED_KINDS = frozenset({"judge", "writer"})  # not members: never part of a member's closure
_REDUCE_MODES = MappingProxyType(
    {
        "vote": "select",
        "judge": "select",
        "pick": "select",
        "rank": "select",
        "filter": "select",
        "merge": "compute",
        "project": "compute",
        "concat": "compute",
    }
)


def case_trace(
    case: CaseResult, graph: Mapping[str, OperationInfo] | None
) -> tuple[TraceEntry, ...]:
    """What every block did for this Case, in operation order; () without operations."""

    if case.operations is None:
        return ()
    member_of = _member_ids(case.operations, graph)
    entries: list[TraceEntry] = []
    for operation in case.operations:
        entries.extend(_operation_entries(operation, graph, member_of, case.operations))
    return tuple(entries)


def _operation_entries(
    operation: CaseOperation,
    graph: Mapping[str, OperationInfo] | None,
    member_of: Mapping[str, str],
    operations: Sequence[CaseOperation],
) -> list[TraceEntry]:
    if operation.combine is not None:
        link = _judge_link(operation.operation_id, operation.combine, graph, operations)
        return _combine_entries(operation.operation_id, operation.combine, link)
    node = None if graph is None else graph.get(operation.operation_id)
    if node is not None and node.kind == "combine":
        return []  # a combine step of a pre-E4a Engine: no evidence, and it makes no model call
    return [_model_call(operation, member_of.get(operation.operation_id))]


def _combine_entries(
    operation_id: str, evidence: CombineEvidence, judge_link: Mapping[str, str | None]
) -> list[TraceEntry]:
    rule = list(evidence.operators[:-2])
    entries = [
        TraceEntry(
            "extract",
            {
                "operation_id": operation_id,
                "member_id": row.member_id,
                "rule": rule,
                "raw": row.raw,
                "value": row.value,
                "status": row.status,
                "reason": row.reason,
            },
        )
        for row in evidence.members
    ]
    entries.append(TraceEntry("reduce", _reduce_data(operation_id, evidence, judge_link)))
    return entries


def _reduce_data(
    operation_id: str, evidence: CombineEvidence, judge_link: Mapping[str, str | None]
) -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "op": evidence.reducer,
        "rule": list(evidence.operators[-2:]),
        "mode": _reduce_mode(evidence),
        "tally": None if evidence.tally is None else [row.to_dict() for row in evidence.tally],
        "chosen": list(evidence.chosen),
        "signal": _signal_data(evidence),
        "result": evidence.result.to_dict(),
        "dropped": evidence.dropped,
        "judge_operation_id": judge_link["judge_operation_id"],
        "judge_model": judge_link["judge_model"],
    }


def _reduce_mode(evidence: CombineEvidence) -> str:
    if evidence.reducer in ("median", "mean"):
        return "compute" if evidence.operators[-1].split("@")[0] == "value" else "select"
    # WHY: a Pick with output= returns a field of the winner, a new value with no member id
    # (AR-3), so it computes. `output_missing` is the abstain only that Pick has (E4b PO-E1).
    if evidence.reducer == "pick" and (
        evidence.built or evidence.result.reason == "output_missing"
    ):
        return "compute"
    return _REDUCE_MODES[evidence.reducer]


def _reads_judge(evidence: CombineEvidence) -> bool:
    """Rule J1-J3 (judge-model PRD, P9): the evidence shows that the step read a judge.

    J1 the judge reducer; J2 scores@1 with a judge reading (source="values" writes none);
    J3 a signal read of score:judge (Vote, Filter or Pick by the judge score).
    """

    return (
        evidence.reducer == "judge"
        or ("scores@1" in evidence.operators and evidence.judge is not None)
        or (evidence.signal is not None and evidence.signal.key == JUDGE_SIGNAL)
    )


def _judge_link(
    operation_id: str,
    evidence: CombineEvidence,
    graph: Mapping[str, OperationInfo] | None,
    operations: Sequence[CaseOperation],
) -> dict[str, str | None]:
    """The judge operation of a combine step and its request model (P8); null, never a guess.

    WHY a view and not a wire key (ans:Q4): the judge's own operation record already holds the
    model, so the combine spec, the evidence and every url4 keep their bytes.
    """

    node = None if graph is None else graph.get(operation_id)
    if graph is None or node is None or not _reads_judge(evidence):
        return {"judge_operation_id": None, "judge_model": None}
    judges = [item for item in node.depends_on if item in graph and graph[item].kind == "judge"]
    if len(judges) != 1:
        return {"judge_operation_id": None, "judge_model": None}
    accounting = next((op.accounting for op in operations if op.operation_id == judges[0]), None)
    model = None if accounting is None else accounting.request_model
    return {"judge_operation_id": judges[0], "judge_model": model}


def _signal_data(evidence: CombineEvidence) -> dict[str, object] | None:
    signal = evidence.signal
    if signal is None:
        return None
    values = {row.member_id: row.signals.get(signal.key) for row in evidence.members}
    return {"key": signal.key, "order": signal.order, "values": values}


def _model_call(operation: CaseOperation, member_id: str | None) -> TraceEntry:
    data: dict[str, object] = {"operation_id": operation.operation_id, "member_id": member_id}
    data.update(_accounting_data(operation.accounting))
    data["status"] = "completed" if operation.output is not None else "unattributed"
    return TraceEntry("model_call", data)


def _accounting_data(accounting: OperationAccounting | None) -> dict[str, object]:
    if accounting is None:
        unknown = {name: None for name in _EMPTY_FIELDS}
        return {**unknown, "cache": "unknown"}
    usage = accounting.usage
    return {
        "provider": accounting.provider,
        "model": accounting.request_model,
        "cache": _cache_label(accounting.cache),
        "cost_usd": usage.to_dict()["cost_usd"],
        "latency_ms": accounting.provider_latency_ms,
        "tokens_in": usage.input_tokens,
        "tokens_out": usage.output_tokens,
    }


def _cache_label(cache: OperationCache) -> str:
    """erd s8: hit = hits with no miss or bypass; miss = any miss; bypass = any bypass with no
    miss; otherwise unknown. Unknown counts never change the label."""

    if cache.hits > 0 and cache.misses == 0 and cache.bypasses == 0:
        return "hit"
    if cache.misses > 0:
        return "miss"
    return "bypass" if cache.bypasses > 0 else "unknown"


def _member_ids(
    operations: Sequence[CaseOperation], graph: Mapping[str, OperationInfo] | None
) -> dict[str, str]:
    """Operation id -> 'member_k' for the operations that belong to exactly one member (F8)."""

    member_of: dict[str, str] = {}
    if graph is None:
        return member_of
    for operation in operations:
        node = graph.get(operation.operation_id)
        if operation.combine is not None and node is not None:
            producers = node.depends_on[: len(operation.combine.members)]
            _label_members(graph, producers, member_of)
    return member_of


def _label_members(
    graph: Mapping[str, OperationInfo], producers: Sequence[str], member_of: dict[str, str]
) -> None:
    closures = [_closure(graph, producer) for producer in producers]
    counts = Counter(operation_id for closure in closures for operation_id in closure)
    for index, (producer, closure) in enumerate(zip(producers, closures, strict=True), start=1):
        own = {producer} if len(producers) == 1 else {item for item in closure if counts[item] == 1}
        for operation_id in sorted(own):
            # the first combine in operation order wins: an inner combine beats an outer one
            member_of.setdefault(operation_id, f"member_{index}")


def _closure(graph: Mapping[str, OperationInfo], producer: str) -> set[str]:
    """The producer plus its ancestors; judge and writer operations are never entered."""

    seen = {producer}
    pending = [producer]
    while pending:
        node = graph.get(pending.pop())
        for parent in () if node is None else node.depends_on:
            if parent not in seen and parent in graph and graph[parent].kind not in _UNTRACED_KINDS:
                seen.add(parent)
                pending.append(parent)
    return seen


__all__: list[str] = []
