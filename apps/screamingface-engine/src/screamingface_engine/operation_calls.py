"""Task-local capture of terminal model calls with their route identity (OME-843).

Sibling of :mod:`screamingface_engine.model_outcomes`, and split from it deliberately: an
outcome is status telemetry every scope wants, while a call's output text is
payload that only the Candidate invocation boundary may retain — so the two
recorders stay independently scoped.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from screamingface_engine.operation_accounting import OperationAccounting
from screamingface_engine.request_identity import ModelRequestKey, model_request_key


@dataclass(frozen=True, slots=True)
class OperationCall:
    """One terminal provider round trip plus the route identity that requested it.

    ``params`` is the request's parameter set sorted by name — the half of the
    OME-843 attribution fingerprint that distinguishes two members on the same
    model route (e.g. different temperatures).
    """

    path: str
    params: tuple[tuple[str, str], ...]
    output: str
    finish_reason: str | None
    accounting: OperationAccounting | None


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
def capture_request_accounting() -> Iterator[RequestAccountingRecorder]:
    """Capture payload-free request accounting for one complete Engine run."""

    recorder: RequestAccountingRecorder = []
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
                if context is not None or intent is not None
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
) -> None:
    """Publish one terminal call to every active scope, if an identity is bound."""

    identity = _identity.get()
    if identity is None:
        return
    if _recorders.get():
        call = OperationCall(
            path=identity.path,
            params=identity.params,
            output=output,
            finish_reason=finish_reason,
            accounting=accounting,
        )
        for recorder in _recorders.get():
            recorder.append(call)
    if identity.request_key is not None:
        request_accounting = RequestAccounting(identity.request_key, accounting)
        for recorder in _accounting_recorders.get():
            recorder.append(request_accounting)


def current_operation_calls() -> OperationCallRecorder | None:
    """The innermost active recorder, or None outside an owned capture scope."""

    active = _recorders.get()
    return active[-1] if active else None


def current_request_accounting() -> RequestAccountingRecorder | None:
    """The innermost payload-free run ledger, or None outside an owned scope."""

    active = _accounting_recorders.get()
    return active[-1] if active else None


__all__ = [
    "OperationCall",
    "RequestAccounting",
    "capture_operation_calls",
    "capture_request_accounting",
    "current_operation_calls",
    "current_request_accounting",
    "operation_call_identity",
    "record_operation_call",
    "suspend_request_accounting",
]
