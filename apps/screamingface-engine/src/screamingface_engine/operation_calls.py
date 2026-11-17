"""Task-local capture of terminal model calls with their route identity (OME-843).

Sibling of :mod:`screamingface_engine.model_outcomes`, and split from it deliberately: an
outcome is status telemetry every scope wants, while a call's output text is
payload that only the Candidate invocation boundary may retain — so the two
recorders stay independently scoped.

Combine steps (OME-1289 E4a) are recorded too, by :func:`record_combine_call`: not a provider
round trip, but one per-operation record that carries its :class:`CombineEvidence`.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from screamingface_engine.combine.decision import GateDecision
from screamingface_engine.combine.evidence import CombineEvidence, GateRecord, PendingCombine
from screamingface_engine.operation_accounting import (
    OperationAccounting,
    ReplyLogprobs,
    SignalAccounting,
)
from screamingface_engine.request_identity import ModelRequestKey, model_request_key


@dataclass(frozen=True, slots=True)
class OperationCall:
    """One terminal provider round trip, or one combine step, plus the route identity that
    requested it.

    ``combine`` is set only by :func:`record_combine_call`: a combine step is not a provider
    round trip, so its ``accounting`` is None and its ``finish_reason`` is ``stop``.

    ``signal_accounting`` is the ORIGINAL call's cost, latency and tokens for combine signals
    (a cache hit keeps the numbers of the call it replays). In-process only: it is never part of
    ``accounting`` and never reaches the wire.

    ``reply_logprobs`` is the token log-probability numbers of the TERMINAL round, when the call
    asked for ``logprobs`` and the reply carried them (E4b part 3). In-process only, numbers only.

    ``decision`` is set only by :func:`record_gate_call` (E4c): a Gate's DECIDE or JOIN record,
    published under the JOIN fingerprint so the last call wins (JOIN's record when JOIN ran).

    ``pending`` is set only for a ``phase=decide`` combine call that took the fallback branch (E4c
    lazy fallback): its output is ``""`` and it has no evidence, so it is not a provider call; the
    accounting index and the budget fold skip it. Its ``record`` is the E4b gate record DECIDE
    reads, and its ``kept`` is the majority answer JOIN copies when the Budget refuses the fallback
    branch (budget BU-18).

    ``params`` is the request's parameter set sorted by name — the half of the
    OME-843 attribution fingerprint that distinguishes two members on the same
    model route (e.g. different temperatures).
    """

    path: str
    params: tuple[tuple[str, str], ...]
    output: str
    finish_reason: str | None
    accounting: OperationAccounting | None
    combine: CombineEvidence | None = None
    signal_accounting: SignalAccounting | None = None
    reply_logprobs: ReplyLogprobs | None = None
    decision: GateDecision | None = None
    pending: PendingCombine | None = None

    @property
    def is_provider(self) -> bool:
        """True for a provider round trip, not a combine step, a Gate record or a pending call."""
        return self.combine is None and self.decision is None and self.pending is None

    @property
    def gate_record(self) -> GateRecord | None:
        """The call's E4b gate record: a pending call's, or a complete combine call's evidence."""
        if self.pending is not None:
            return self.pending.record
        return None if self.combine is None else self.combine.gate


@dataclass(frozen=True, slots=True)
class RequestAccounting:
    """Payload-free accounting for one authored model request."""

    request_key: ModelRequestKey
    accounting: OperationAccounting | None


@dataclass(frozen=True, slots=True)
class _OperationCallIdentity:
    path: str
    params: tuple[tuple[str, str], ...]
    request_key: ModelRequestKey | None


type OperationCallRecorder = list[OperationCall]
type RequestAccountingRecorder = list[RequestAccounting]

_recorders: contextvars.ContextVar[tuple[OperationCallRecorder, ...]] = contextvars.ContextVar(
    "screamingface_engine_operation_call_recorders", default=()
)
_identity: contextvars.ContextVar[_OperationCallIdentity | None] = contextvars.ContextVar(
    "screamingface_engine_operation_call_identity", default=None
)
_accounting_recorders: contextvars.ContextVar[tuple[RequestAccountingRecorder, ...]] = (
    contextvars.ContextVar("screamingface_engine_request_accounting_recorders", default=())
)


@contextmanager
def capture_operation_calls(*, isolated: bool = False) -> Iterator[OperationCallRecorder]:
    """Capture terminal calls in this scope; nesting mirrors `capture_model_outcomes`."""

    recorder: OperationCallRecorder = []
    active = () if isolated else _recorders.get()
    token = _recorders.set((*active, recorder))
    try:
        yield recorder
    finally:
        _recorders.reset(token)


@contextmanager
def capture_request_accounting(
    recorder: RequestAccountingRecorder | None = None,
) -> Iterator[RequestAccountingRecorder]:
    """Capture payload-free request accounting for one complete Engine run."""

    recorder = [] if recorder is None else recorder
    token = _accounting_recorders.set((*_accounting_recorders.get(), recorder))
    try:
        yield recorder
    finally:
        _accounting_recorders.reset(token)


@contextmanager
def suspend_request_accounting() -> Iterator[None]:
    """Exclude one nested execution from every ambient run-accounting ledger."""

    token = _accounting_recorders.set(())
    try:
        yield
    finally:
        _accounting_recorders.reset(token)


@contextmanager
def operation_call_identity(
    path: str,
    params: Mapping[str, str],
    *,
    context: str | None = None,
    intent: str | None = None,
) -> Iterator[None]:
    """Bind the route identity of the call about to run, for its own task only.

    WHY: the connector's completion loop knows the terminal content and finish
    reason but not which url4 source asked for them; the endpoint entry knows the
    request's path and params but not the terminal fields. This contextvar carries
    the identity across that gap without widening the loop's signature.
    """

    token = _identity.set(
        _OperationCallIdentity(
            path=path,
            params=tuple(sorted(params.items())),
            request_key=(
                model_request_key(path=path, params=params, context=context, intent=intent)
                # INVARIANT: Candidate execution suspends the run ledger. Do not hash its complete
                # prompt merely to discard the key; only grading capture owns this identity.
                if _accounting_recorders.get() and (context is not None or intent is not None)
                else None
            ),
        )
    )
    try:
        yield
    finally:
        _identity.reset(token)


def record_operation_call(
    output: str,
    finish_reason: str | None,
    accounting: OperationAccounting | None = None,
    signal_accounting: SignalAccounting | None = None,
    reply_logprobs: ReplyLogprobs | None = None,
) -> None:
    """Publish one terminal call to every active scope, if an identity is bound."""

    identity = _identity.get()
    if identity is None:
        return
    # WHY two record shapes: Candidate projection needs the terminal output, while the run-wide
    # grading join must remain payload-free. One publication point feeds each active scope without
    # retaining prompts or judge outputs for the lifetime of the run.
    if _recorders.get():
        call = OperationCall(
            path=identity.path,
            params=identity.params,
            output=output,
            finish_reason=finish_reason,
            accounting=accounting,
            signal_accounting=signal_accounting,
            reply_logprobs=reply_logprobs,
        )
        _publish(call)
    if identity.request_key is not None:
        request_accounting = RequestAccounting(identity.request_key, accounting)
        for recorder in _accounting_recorders.get():
            recorder.append(request_accounting)


def _publish_internal(
    path: str,
    params: Mapping[str, str],
    output: str,
    *,
    combine: CombineEvidence | None = None,
    decision: GateDecision | None = None,
    pending: PendingCombine | None = None,
) -> None:
    """Publish one call with no provider accounting, and the fields that set its kind."""

    if not _recorders.get():
        return
    _publish(
        OperationCall(
            path=path,
            params=tuple(sorted(params.items())),
            output=output,
            finish_reason="stop",
            accounting=None,
            combine=combine,
            decision=decision,
            pending=pending,
        )
    )


def record_combine_call(
    path: str,
    params: Mapping[str, str],
    output: str,
    evidence: CombineEvidence,
) -> None:
    """Publish one combine step to every active capture scope.

    WHY no identity and no run ledger: a combine step is not a provider round trip, so it has
    no request key and no accounting; it only joins the Candidate's per-operation record.
    """

    _publish_internal(path, params, output, combine=evidence)


def record_gate_call(
    path: str,
    params: Mapping[str, str],
    output: str,
    decision: GateDecision,
) -> None:
    """Publish one Gate decision record to every active capture scope (E4c, branch-core D3).

    WHY the JOIN fingerprint for both DECIDE and JOIN: attribution keeps the last call of a
    fingerprint, so JOIN's completed record wins when JOIN ran and DECIDE's record stays when a
    body failed before JOIN.
    """

    _publish_internal(path, params, output, decision=decision)


def record_pending_combine_call(
    path: str,
    params: Mapping[str, str],
    gate_record: GateRecord,
    kept_output: str | None,
) -> None:
    """Publish a ``phase=decide`` combine call that took the fallback branch (E4c lazy fallback).

    Output ``""``, no evidence; ``gate_record`` is what DECIDE reads (branch-core D11).
    """

    _publish_internal(path, params, "", pending=PendingCombine(gate_record, kept_output))


def provider_calls_by_fingerprint(
    calls: Iterable[OperationCall],
) -> dict[tuple[str, tuple[tuple[str, str], ...]], list[OperationCall]]:
    """The provider calls among ``calls`` by fingerprint (path, params), in record order.

    E4c (BC-29, branch-core D7): a combine call, a pending combine call and a Gate record are not
    provider calls; the combine accounting index and the budget fold both read this one rule.
    """

    index: dict[tuple[str, tuple[tuple[str, str], ...]], list[OperationCall]] = {}
    for call in calls:
        if call.is_provider:
            index.setdefault((call.path, call.params), []).append(call)
    return index


def _publish(call: OperationCall) -> None:
    for recorder in _recorders.get():
        recorder.append(call)


def current_model_request_key() -> ModelRequestKey | None:
    """The exact authored request being executed, when run capture is enabled."""
    identity = _identity.get()
    return identity.request_key if identity is not None else None


def current_request_accounting() -> RequestAccountingRecorder | None:
    """The innermost payload-free run ledger, or None outside an owned scope."""

    active = _accounting_recorders.get()
    return active[-1] if active else None


def current_operation_calls() -> tuple[OperationCall, ...] | None:
    """A snapshot of the INNERMOST active capture scope's calls, or None outside every scope."""

    active = _recorders.get()
    return tuple(active[-1]) if active else None


def latest_operation_call(predicate: Callable[[OperationCall], bool]) -> OperationCall | None:
    """The newest call of the INNERMOST active capture scope that ``predicate`` accepts, or None.

    WHY no snapshot: the search reads the recorder in place and copies no call list.
    """

    active = _recorders.get()
    if not active:
        return None
    return next((call for call in reversed(active[-1]) if predicate(call)), None)


__all__ = [
    "OperationCall",
    "RequestAccounting",
    "capture_operation_calls",
    "capture_request_accounting",
    "current_operation_calls",
    "current_request_accounting",
    "current_model_request_key",
    "latest_operation_call",
    "operation_call_identity",
    "provider_calls_by_fingerprint",
    "record_combine_call",
    "record_gate_call",
    "record_operation_call",
    "record_pending_combine_call",
    "suspend_request_accounting",
]
