"""The request-scoped correlation context every aigateway log line is stamped with.

FEATURE (OME-938): before this, `gateway_call_id` reached exactly ONE log line
(`plugins/taxonomy/session.py`), so an operator holding an id from a response body could find
the line announcing it and nothing about what the call actually did — dispatch, cache, retry
and concurrency lines were all anonymous.

The mechanism is a ContextVar bound per request by `middleware.call_id`, plus a log-record
factory that stamps the bound id onto every record created inside that scope. A factory rather
than a per-call argument, because the lines that most need attributing are the ones nobody will
go back and edit: LiteLLM's, a library's, an exception handler's.

INVARIANT: `install_call_context_injection` WRAPS whatever factory it finds; it never replaces
one. `core.auth.log_filter.install_provisioning_token_redaction` owns the same single
`logging.setLogRecordFactory` slot, and replacing it would silently stop scrubbing provisioning
tokens — a security regression hiding inside an observability change, invisible to every
observability assertion. Both install orders are covered by tests.
"""

from __future__ import annotations

import contextvars
import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager

from aigateway.core.auth.log_filter import factory_chain_has

_INSTALLED = "_aigw_call_context_injection"
"""Marks the factory THIS module installed, so a second install is a no-op."""

_TRACE_RECORD_ATTR = "trace_id"
"""The attribute the injector stamps for the caller's trace, and the field name in output.

Same name the Engine uses in its own `run_context` (`screamingface_engine/logs.py`), so one
grep finds the id in both services' logs — which is the whole of Phase 1.
"""

_RECORD_ATTR = "gateway_call_id"
"""The attribute name the injector stamps on each record, and the field name in the output.

One constant, because the renderer (`logs.CallContextFilter`) and every reader must agree with
the writer. A drift here is silent: records carry the id, nothing renders it.
"""


def record_trace_id(record: logging.LogRecord) -> str | None:
    """The caller's trace id stamped on `record`, or None outside a request."""

    value = getattr(record, _TRACE_RECORD_ATTR, None)
    return value if isinstance(value, str) else None


def record_call_id(record: logging.LogRecord) -> str | None:
    """The call id stamped on `record`, or None if it was created outside a request.

    A typed accessor rather than `getattr(record, "gateway_call_id", None)` at each site:
    `LogRecord` has no such attribute in its type, so every direct read is a pyright error, and
    the string would be repeated in the renderer, the tests and any future consumer.
    """

    value = getattr(record, _RECORD_ATTR, None)
    return value if isinstance(value, str) else None


_call_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aigateway_gateway_call_id", default=None
)

_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aigateway_trace_id", default=None
)
"""FEATURE (OME-1120): the CALLER's trace id, joined from the inbound `traceparent`.

Separate from `_call_id` and not merged into one dataclass: they have different origins and
different trust. The call id is ours and always exists; the trace id comes from a header a
caller controls and may be absent. Binding them separately keeps "we could not read a trace"
distinguishable from "this request has no id at all".
"""


def new_gateway_call_id() -> str:
    """A fresh id in the shape the public contract already fixes.

    `call_<32 hex>` is pinned by `plugins/taxonomy/usage_accounting.schema.json` and appears in
    response bodies, so it is not free to change here.
    """

    return f"call_{secrets.token_hex(16)}"


@contextmanager
def call_scope(call_id: str, *, trace_id: str | None = None) -> Iterator[str]:
    """Bind one request's correlation ids for the duration of a scope; restore on exit.

    `trace_id` is keyword-only and optional so every existing caller and test keeps working
    unchanged (OME-1120): a scope with no trace is a legitimate state, not a degenerate one.
    """

    call_token = _call_id.set(call_id)
    trace_token = _trace_id.set(trace_id)
    try:
        yield call_id
    finally:
        _trace_id.reset(trace_token)
        _call_id.reset(call_token)


def current_trace_id() -> str | None:
    """The caller's bound trace id, or None outside a request or when none was readable."""

    return _trace_id.get()


def current_call_id() -> str | None:
    """The bound request's id, or None outside any request.

    None means the record carries NO id — boot, shutdown and test lines stay byte-identical
    rather than gaining an empty field.
    """

    return _call_id.get()


def install_call_context_injection() -> None:
    """Stamp the bound call id onto every log record created from now on.

    Idempotent, and composes with the redaction factory in either install order — see the
    module INVARIANT.
    """

    current_factory = logging.getLogRecordFactory()
    if factory_chain_has(current_factory, _INSTALLED):
        return

    def call_context_factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = current_factory(*args, **kwargs)  # type: ignore[arg-type]
        # `setattr`, not `record.gateway_call_id = ...`: `LogRecord` has no such attribute in
        # its type, and this is the ordinary way to carry an extra on one. Read it back through
        # `record_call_id` rather than a bare `getattr` at each call site.
        setattr(record, _RECORD_ATTR, current_call_id())
        setattr(record, _TRACE_RECORD_ATTR, current_trace_id())
        return record

    setattr(call_context_factory, _INSTALLED, True)
    # `__wrapped__` is what makes the chain walkable — see `factory_chain_has`.
    setattr(call_context_factory, "__wrapped__", current_factory)
    logging.setLogRecordFactory(call_context_factory)


__all__ = [
    "call_scope",
    "record_call_id",
    "current_trace_id",
    "record_trace_id",
    "current_call_id",
    "install_call_context_injection",
    "new_gateway_call_id",
]
