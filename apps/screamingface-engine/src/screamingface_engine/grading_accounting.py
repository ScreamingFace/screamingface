"""Exact in-memory join from authored grading requests to retained Evidence."""

from __future__ import annotations

import contextvars
import json
import logging
from collections.abc import Iterator, Mapping, Sequence, Set
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from screamingface_engine.benchmarks.result_body import compact_json
from screamingface_engine.observations import RunObservations, current_observations
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
    # INVARIANT (review finding, 2026-09-24): the owner has NO candidate dimension,
    # so correctness rests on "one candidate per captured run" — the SDK dispatches
    # one Engine run per candidate and OperationCapturingExecutor builds a fresh
    # registry per execute(), so two candidates never share one. AIDEV-NOTE: any
    # future in-run multi-candidate grading (or a replayed url4 that grades one
    # benchmark twice in a single run) must add the candidate to this key first, or one
    # Case's evidence will combine both candidates' judge costs — and the
    # identical-answer case dodges the collision warning below (one owner, two keys).
    benchmark_id: str
    case_id: int | str
    check_id: str
    sequence: int


@dataclass(slots=True)
class _Registry:
    observation_owner: RunObservations | None = field(default_factory=current_observations)
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
def capture_grading_requests(registry: _Registry | None = None) -> Iterator[_Registry]:
    registry = _Registry() if registry is None else registry
    token = _registry.set(registry)
    try:
        yield registry
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


def grading_case_for_request(key: ModelRequestKey | None) -> int | str | None:
    """Read Engine-authored ownership for this exact request, never infer from payloads.

    INVARIANT: multiple owners cannot yield a guessed Case; nested observation runs
    cannot borrow the outer run's registry. No prompt or response enters activity.
    """
    registry = _registry.get()
    if key is None or registry is None or registry.observation_owner is not current_observations():
        return None
    owners = registry.owners_by_key.get(key, set())
    cases = {owner.case_id for owner in owners}
    return next(iter(cases)) if len(cases) == 1 else None


def accounting_for_grading_evidence(
    owner: GradingEvidenceOwner,
) -> OperationAccounting | None:
    registry = _registry.get()
    calls = current_request_accounting()
    if registry is None or calls is None:
        return None
    request_keys = _request_keys_for_owner(registry.keys_by_owner, registry.owners_by_key, owner)
    if not request_keys:
        return None
    _index_new_calls(registry, calls)
    return _accounting_for_keys(registry.calls_by_key, request_keys)


@dataclass(frozen=True, slots=True)
class GradingAccountingView:
    """A frozen copy of the run's grading join, taken once when marking ends.

    FEATURE memory fix 3 (OME-1835), unit 2: the final Evidence accounting of a Candidate Result
    is computed from this view, for the held result and for the parked body alike.
    WHY a copy: the parked body is written on a worker thread (``asyncio.to_thread``). The live
    registry and ledger belong to the run loop, where another grading stream may still index
    or register. The worker only reads this view, so it never changes shared state.
    INVARIANT: taken at the same point as today's reconcile (the complete Candidate Result), so
    every grading owner has registered and the two-owner revocation sees all of them.
    """

    keys_by_owner: Mapping[GradingEvidenceOwner, frozenset[ModelRequestKey]]
    owners_by_key: Mapping[ModelRequestKey, frozenset[GradingEvidenceOwner]]
    calls_by_key: Mapping[ModelRequestKey, tuple[RequestAccounting, ...]]

    def accounting_for(self, owner: GradingEvidenceOwner) -> OperationAccounting | None:
        """One Evidence item's final accounting (the rule of accounting_for_grading_evidence)."""

        request_keys = _request_keys_for_owner(self.keys_by_owner, self.owners_by_key, owner)
        if not request_keys:
            return None
        return _accounting_for_keys(self.calls_by_key, request_keys)


def grading_accounting_view() -> GradingAccountingView | None:
    """The run's grading join, frozen; None when no registry or no request ledger is bound.

    None is the only case in which reconcile changes nothing, so a caller that gets None
    writes every Evidence accounting as it is.
    """

    registry = _registry.get()
    calls = current_request_accounting()
    if registry is None or calls is None:
        return None
    _index_new_calls(registry, calls)
    return GradingAccountingView(
        keys_by_owner={owner: frozenset(keys) for owner, keys in registry.keys_by_owner.items()},
        owners_by_key={key: frozenset(owners) for key, owners in registry.owners_by_key.items()},
        calls_by_key={key: tuple(found) for key, found in registry.calls_by_key.items()},
    )


def reconcile_candidate_grading_accounting(result: CandidateResult) -> None:
    """Finalize Evidence accounting after every grading owner has registered."""

    view = grading_accounting_view()
    if view is None:
        return
    # INVARIANT: verdict routes may project before a later owner registers the same request key.
    # The complete Candidate Result is the first boundary that can revoke provisional attribution
    # for every affected Evidence item, so it is the authority that leaves the Engine.
    # INVARIANT: reconcile_case_accounting_text is the wire twin of this loop; change both.
    for case in result.cases:
        if case.grade is None:
            continue
        for check in case.grade.checks:
            for evidence in check.evidence:
                evidence.accounting = view.accounting_for(
                    GradingEvidenceOwner(
                        benchmark_id=result.benchmark_id,
                        case_id=case.case_id,
                        check_id=check.id,
                        sequence=evidence.sequence,
                    )
                )


def reconcile_case_accounting_text(
    text: str, *, benchmark_id: str, case_id: int | str, view: GradingAccountingView
) -> str:
    """One parked Case's wire JSON with each Evidence item's final accounting.

    FEATURE memory fix 3 (OME-1835), unit 2: the wire twin of
    ``reconcile_candidate_grading_accounting``, for one Case parked as compact JSON. Change both.
    INVARIANT: a Case whose accounting does not change is returned VERBATIM (the parked bytes);
    a changed Case is encoded again with ``compact_json``, so its key order stays the same.
    """

    record = json.loads(text)
    grade = record["grade"]
    if grade is None:
        return text
    changed = False
    for check in grade["checks"]:
        for evidence in check["evidence"]:
            accounting = view.accounting_for(
                GradingEvidenceOwner(
                    benchmark_id=benchmark_id,
                    case_id=case_id,
                    check_id=check["id"],
                    sequence=evidence["sequence"],
                )
            )
            wire = None if accounting is None else accounting.model_dump(by_alias=True)
            if compact_json(wire) != compact_json(evidence["accounting"]):
                evidence["accounting"] = wire
                changed = True
    return compact_json(record) if changed else text


def _request_keys_for_owner(
    keys_by_owner: Mapping[GradingEvidenceOwner, Set[ModelRequestKey]],
    owners_by_key: Mapping[ModelRequestKey, Set[GradingEvidenceOwner]],
    owner: GradingEvidenceOwner,
) -> tuple[ModelRequestKey, ...]:
    keys = keys_by_owner.get(owner, set())
    if not keys or any(owners_by_key.get(key) != {owner} for key in keys):
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
    "GradingAccountingView",
    "GradingEvidenceOwner",
    "accounting_for_grading_evidence",
    "capture_grading_requests",
    "grading_accounting_view",
    "grading_case_for_request",
    "reconcile_candidate_grading_accounting",
    "reconcile_case_accounting_text",
    "register_grading_request",
]
