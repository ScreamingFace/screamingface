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

# FEATURE (OME-1185): the span of the node currently resolving, bound per node by the
# executor's observer. Separate from `_trace` because the two have different lifetimes: the
# run's trace is bound once around the whole driving task, while this changes per node, in
# each node's own `asyncio.Task`.
_node_span: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "screamingface_engine_node_span", default=None
)


@contextmanager
def run_trace_scope(trace: TraceContext | None) -> Iterator[None]:
    """Bind one run's trace for the duration of a scope; restore on exit.

    ``None`` is a real argument, not a degenerate one: `Executor.execute` declares
    ``trace: TraceContext | None`` and callers outside `lifecycle.run` pass nothing. Binding it
    explicitly is what stops an inner run without a trace from inheriting an outer run's.
    """

    token = _trace.set(trace)
    # INVARIANT: a new run starts at its own root, never inside a node of the run around it.
    # Without this clear, a nested or sequential run in the same context would attribute its
    # gateway calls to the OUTER run's last node — a plausible-looking id belonging to another
    # span, which is exactly the class of error a trace cannot be used to detect.
    span_token = _node_span.set(None)
    try:
        yield
    finally:
        _node_span.reset(span_token)
        _trace.reset(token)


def bind_node_span(span_id: str) -> None:
    """Bind the currently-resolving node's span, so outbound calls name IT as their parent.

    FEATURE (OME-1185): `OME-1119` sent the run's ``root_span_id`` on every call, because
    nothing emitted a root span yet and a per-node parent would have dangled. `OME-1130` made
    per-node spans real, so that choice now only makes the trace FLAT — every aigateway server
    span hangs off the run instead of off the node that issued the call, and a run's eleven
    provider calls cannot be told apart.

    WHY nothing is ever unbound: the executor's observer calls this from the node's own
    :class:`asyncio.Task`, whose context dies with the node, so each sibling and each child
    sees its own binding and there is nothing to clean up. Resetting a token here would be
    actively wrong — a token created in one Task and reset in another raises ``ValueError:
    Token was created in a different Context``, the defect
    ``test_a_cancelled_run_does_not_raise_from_the_trace_scope`` pins. Run scoping is
    `run_trace_scope`'s job, and it clears this on entry.
    """

    _node_span.set(span_id)


def current_traceparent() -> str | None:
    """This run's ``traceparent`` header value, or ``None`` outside any run.

    ``None`` means the header is OMITTED, never sent empty or all-zero. A well-formed header
    carrying a zero id would parse everywhere, join nothing, and look correct in every log it
    reached — which is worse than its absence, because absence is diagnosable.

    The span named is the CALLING NODE's when one is bound (OME-1185) and the run's
    ``root_span_id`` otherwise — which is not a fallback but the correct answer: outside any
    node, the run's root IS the current span, and it is a span `lifecycle` genuinely emits
    (`StartedEvent` rides it).

    WHY never a fresh span per call: W3C wants the caller's CURRENT span, and OTel's HTTP
    instrumentation mints a client span per request. Minting one here would name a span no
    exporter publishes, so the gateway's parent pointer would dangle — which renders as a gap.
    Both ids this function can return are exported by the run itself.
    """

    trace = _trace.get()
    if trace is None:
        return None
    return format_traceparent(trace.trace_id, _node_span.get() or trace.root_span_id)


__all__ = ["bind_node_span", "current_traceparent", "run_trace_scope"]
