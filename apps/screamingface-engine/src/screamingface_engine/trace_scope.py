"""The run's W3C trace, bound for the duration of one run so outbound calls can carry it.

FEATURE (OME-1119): rung 2 of the correlation ladder. The engine adopted a caller's
traceparent and told nobody — the header set aigateway received carried `X-User-Email` and
`X-Profile` but no `traceparent`, so a user quoting the `trace_id` from their `Report` could
see the engine's half of a run and nothing about the model calls, which is where the
interesting failures are.

WHY a ContextVar rather than a field on the world: `Url4Executor._resolve_world` caches
`self._io`, so `build_aigateway_world` runs ONCE per executor while serve mode drives many
runs through it. A per-run value parked on that shared object is one run reading another's —
the defect `build_aigateway_world`'s own docstring warns about for `cache`. A ContextVar is
read at request time rather than build time, so the world stays cacheable and the value cannot
outlive its run. This is also the idiom the same call site already uses:
`current_retrieval_policy()` and `operation_call_identity()` sit beside it in
`runner/connector.py`.

INVARIANT: the id here is the one `url4.streaming.lifecycle.run` resolved and handed to
`Executor.execute`, NOT `logs.RunContext.trace_id`. `runner/main.py` binds the log context from
`parse_traceparent(env)`, which is `None` when the caller sent none — and url4 then MINTS one
that never reaches it. Reading the log context would propagate for client-originated runs
(passing rung 2) and silently propagate nothing for every other run.
"""

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

from url4.streaming.interfaces import TraceContext
from url4.streaming.trace import format_traceparent

_trace: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "screamingface_engine_run_trace", default=None
)


@contextmanager
def run_trace_scope(trace: TraceContext | None) -> Iterator[None]:
    """Bind one run's trace for the duration of a scope; restore on exit.

    ``None`` is a real argument, not a degenerate one: `Executor.execute` declares
    ``trace: TraceContext | None`` and callers outside `lifecycle.run` pass nothing. Binding it
    explicitly is what stops an inner run without a trace from inheriting an outer run's.
    """

    token = _trace.set(trace)
    try:
        yield
    finally:
        _trace.reset(token)


def current_traceparent() -> str | None:
    """This run's ``traceparent`` header value, or ``None`` outside any run.

    ``None`` means the header is OMITTED, never sent empty or all-zero. A well-formed header
    carrying a zero id would parse everywhere, join nothing, and look correct in every log it
    reached — which is worse than its absence, because absence is diagnosable.

    WHY `root_span_id` rather than a fresh span per call: W3C wants the caller's CURRENT span,
    and OTel's HTTP instrumentation mints a client span per request. Doing that here would name
    a span no exporter publishes, so once `OME-1130` makes spans real the gateway's parent
    pointer would dangle. The root span is one `lifecycle` genuinely emits (`StartedEvent` rides
    it). Attaching the per-node span — which `lifecycle._trace_fields` already resolves for
    frames — is Phase 2 work.
    """

    trace = _trace.get()
    if trace is None:
        return None
    return format_traceparent(trace.trace_id, trace.root_span_id)


__all__ = ["current_traceparent", "run_trace_scope"]
