"""Exact in-memory join from authored grading requests to retained Evidence."""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from screamingface_engine.operation_accounting import (
    OperationAccounting,
    combine_operation_accounting,
)
from screamingface_engine.operation_calls import RequestAccounting, current_request_accounting
from screamingface_engine.request_identity import ModelRequestKey, model_request_key

if TYPE_CHECKING:
    from screamingface_engine.benchmarks.contract import CandidateResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GradingEvidenceOwner:
    benchmark_id: str
    case_id: int | str
    check_id: str
    sequence: int


@dataclass(slots=True)
class _Registry:
    keys_by_owner: dict[GradingEvidenceOwner, set[ModelRequestKey]] = field(default_factory=dict)
    owners_by_key: dict[ModelRequestKey, set[GradingEvidenceOwner]] = field(default_factory=dict)
    calls_by_key: dict[ModelRequestKey, list[RequestAccounting]] = field(default_factory=dict)
    indexed_calls: Sequence[RequestAccounting] | None = None
    indexed_count: int = 0
    collision_warned: bool = False


_registry: contextvars.ContextVar[_Registry | None] = contextvars.ContextVar(
    "screamingface_engine_grading_request_registry", default=None
)


@contextmanager
def capture_grading_requests() -> Iterator[None]:
    token = _registry.set(_Registry())
    try:
        yield
    finally:
        _registry.reset(token)


def register_grading_request(
    owner: GradingEvidenceOwner,
    *,
    path: str,
    params: Mapping[str, str],
    context: str | None,
    intent: str | None,
) -> None:
    registry = _registry.get()
    if registry is None:
        return
    request_key = model_request_key(
        path=path,
        params=params,
        context=context,
        intent=intent,
    )
    registry.keys_by_owner.setdefault(owner, set()).add(request_key)
    owners = registry.owners_by_key.setdefault(request_key, set())
    owners.add(owner)
    if len(owners) > 1 and not registry.collision_warned:
        registry.collision_warned = True
        logger.warning("grading accounting request key has multiple owners; attribution disabled")


def accounting_for_grading_evidence(
    owner: GradingEvidenceOwner,
) -> OperationAccounting | None:
    registry = _registry.get()
    calls = current_request_accounting()
    if registry is None or calls is None:
        return None
    request_keys = _request_keys_for_owner(registry, owner)
    if not request_keys:
        return None
    _index_new_calls(registry, calls)
    return _accounting_for_keys(registry.calls_by_key, request_keys)


def reconcile_candidate_grading_accounting(result: CandidateResult) -> None:
    """Finalize Evidence accounting after every grading owner has registered."""

    registry = _registry.get()
    calls = current_request_accounting()
    if registry is None or calls is None:
        return
    _index_new_calls(registry, calls)
    # INVARIANT: verdict routes may project before a later owner registers the same request key.
    # The complete Candidate Result is the first boundary that can revoke provisional attribution
    # for every affected Evidence item, so it is the authority that leaves the Engine.
    for case in result.cases:
        if case.grade is None:
            continue
        for check in case.grade.checks:
            for evidence in check.evidence:
                evidence.accounting = accounting_for_grading_evidence(
                    GradingEvidenceOwner(
                        benchmark_id=result.benchmark_id,
                        case_id=case.case_id,
                        check_id=check.id,
                        sequence=evidence.sequence,
                    )
                )


def _request_keys_for_owner(
    registry: _Registry,
    owner: GradingEvidenceOwner,
) -> tuple[ModelRequestKey, ...]:
    keys = registry.keys_by_owner.get(owner, set())
    if not keys or any(registry.owners_by_key.get(key) != {owner} for key in keys):
        return ()
    return tuple(sorted(keys))


def _index_new_calls(registry: _Registry, calls: Sequence[RequestAccounting]) -> None:
    # INVARIANT: one run ledger grows append-only. Identity or length rollback means a new ledger,
    # so the derived index resets before appending only the unseen suffix.
    if registry.indexed_calls is not calls or registry.indexed_count > len(calls):
        registry.calls_by_key.clear()
        registry.indexed_calls = calls
        registry.indexed_count = 0
    for call in calls[registry.indexed_count :]:
        if call.request_key is not None:
            registry.calls_by_key.setdefault(call.request_key, []).append(call)
    registry.indexed_count = len(calls)


def _accounting_for_keys(
    calls_by_key: Mapping[ModelRequestKey, Sequence[RequestAccounting]],
    request_keys: Sequence[ModelRequestKey],
) -> OperationAccounting | None:
    matched = [call for request_key in request_keys for call in calls_by_key.get(request_key, ())]
    if not matched or any(call.accounting is None for call in matched):
        return None
    return combine_operation_accounting([call.accounting for call in matched if call.accounting])


__all__ = [
    "GradingEvidenceOwner",
    "accounting_for_grading_evidence",
    "capture_grading_requests",
    "reconcile_candidate_grading_accounting",
    "register_grading_request",
]
