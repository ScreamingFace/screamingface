"""The engine observation seam: a passive, pure-data event stream.

The DAG executor emits one small closed set of dataclasses as it runs a graph
— span start/finish, usage, logs, run boundaries — to an injected
:class:`Observer`. This module defines only the *shape* of that stream: it is
a dependency-free leaf (standard library only) so the engine core never gains
a transport or tracing-backend dependency just because an embedder wants to
watch a run. Adapting these events onto any particular wire format or
downstream tracing product is deliberately kept out of this module.

``Observer.on_event`` is synchronous and non-blocking by contract — the
executor calls it inline from its own coroutines, never behind a task or a
queue, so a slow or blocking observer would slow the run itself. An observer
that raises propagates out of direct observation like any other node failure.
The opt-in ``current_log_sink`` convenience alone contains ordinary submission
failures; it never changes lifecycle or direct logging failure semantics.
"""

from __future__ import annotations

import contextlib
import contextvars
import math
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RunStarted:
    """Emitted once, at the very start of a top-level owned-context run."""

    trace_id: str  # 32-hex
    root_span_id: str  # 16-hex
    expression_hash: str


@dataclass(frozen=True, slots=True)
class NodeStarted:
    """Emitted once per node evaluation, right before ``resolve`` is awaited."""

    span_id: str  # 16-hex
    parent_span_id: str | None
    node_kind: str  # type(node).__name__
    detail: str  # best-effort route/url/text, "" if none


@dataclass(frozen=True, slots=True)
class NodeFinished:
    """Emitted once per node evaluation, after ``resolve`` settles."""

    span_id: str
    status: Literal["ok", "error", "cancelled"]
    engine_seq: int
    code: str | None = None
    permanent: bool | None = None


type LogScalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class Log:
    span_id: str | None
    severity: str
    body: str
    attributes: Mapping[str, LogScalar] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        # INVARIANT: observers and caller mutation cannot rewrite queued evidence.
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))


@dataclass(frozen=True, slots=True)
class Usage:
    span_id: str | None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    # WHY a SEPARATE field rather than overwriting `model`: the GenAI semantic conventions
    # distinguish `gen_ai.request.model` (what the caller asked for) from
    # `gen_ai.response.model` (what actually served it), and a gateway is free to resolve an
    # alias to a dated snapshot. `model` above stays the REQUESTED name.
    # INVARIANT: `None` means the provider did not say — never a copy of `model`. Reporting the
    # request as the response makes provider-side model drift undetectable, which is exactly
    # what this field exists to expose.
    response_model: str | None = None
    # FEATURE: per-run cost reporting (OME-849). The wire `TokenUsage` this feeds already carries
    # five token classes; these three close the gap so cache and reasoning evidence can reach an
    # embedder at all.
    # INVARIANT: `None` means the provider did not report the class — NEVER a synonym for 0. An
    # unknown class priced as zero is money invented from nothing, so the two must stay
    # distinguishable all the way to the consumer.
    # AIDEV-NOTE: `input_tokens` / `output_tokens` above stay non-optional `int` deliberately —
    # widening them breaks a live seam, and a producer with incomplete evidence signals that by
    # leaving `cost_usd` None rather than by nulling a token count.
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    reasoning_tokens: int | None = None
    # WHY money rides HERE and not on `ModelResponse`: this event IS the cost-accounting seam that
    # embedders derive cost frames from, so a provider-authored amount belongs on it — unlike a
    # finish reason, which is why that lives next door.
    # INVARIANT: already USD. Unit conversion belongs to the adapter that understands the provider's
    # contract; `url4` performs no arithmetic on this value and never coerces it through float.
    # `None` means "not priced", which is a different claim from `Decimal("0")` ("was free").
    cost_usd: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """Emitted once per model round trip, carrying HOW that call ended.

    Deliberately separate from :class:`Usage` rather than fields on it: `Usage`
    is token accounting, and embedders derive cost frames from it, so a finish
    reason there would put a non-cost fact into cost accounting. A node may emit
    several of these — a tool-calling turn is several round trips against one
    span — so consumers keep the sequence rather than overwriting.

    ``finish_reason`` is the provider's own value, normalized upstream to the
    OpenAI vocabulary (``stop`` | ``length`` | ``content_filter`` |
    ``tool_calls``); ``refusal`` is the provider's refusal text when it sends
    one. Both are optional because not every provider reports either.

    ``cache_status`` / ``cache_reason`` say whether the gateway that answered
    served this round trip from its response cache, and — when it did not —
    its own word for why. They ride HERE rather than on a seam of their own
    because the fact is per-round-trip exactly as ``finish_reason`` is, and an
    adapter reads both off the same response. WHY it must be reported at all: a
    hit costs nothing upstream, so a run that cannot report one bills it as a
    fresh call — an error that HIDES savings and is therefore never noticed.
    ``cache_reason`` is the reporting cache's vocabulary VERBATIM; normalizing
    it here would erase the distinction that makes "I asked for no caching and
    something still cached" an answerable question.
    """

    span_id: str | None
    finish_reason: str | None
    refusal: str | None
    # AIDEV-NOTE: this literal is spelled again on `url4.streaming.protocol.SpanData`, which is
    # where it reaches the wire. Deliberately duplicated rather than shared: this module is the
    # engine's dependency-free observation leaf and the protocol package is the wire contract,
    # and coupling the two to save three tokens would be the worse trade. Change both together.
    cache_status: Literal["hit", "miss", "bypass"] | None = None
    cache_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RunFinished:
    """Emitted once, after the top-level run settles (success or failure)."""

    status: Literal["ok", "error", "cancelled"]
    engine_seq: int


ObservationEvent = (
    RunStarted | NodeStarted | NodeFinished | Log | Usage | ModelResponse | RunFinished
)


@runtime_checkable
class Observer(Protocol):
    """The observation port. Concrete tracing/logging adapters live outside url4."""

    def on_event(self, event: ObservationEvent) -> None:
        """Handle one event. Must be synchronous and non-blocking; may raise."""
        ...


class NullObserver:
    """The no-op observer — never installed by default, available for callers
    that want an explicit ``Observer`` without writing their own no-op."""

    __slots__ = ()

    def on_event(self, event: ObservationEvent) -> None:
        return None


UsageSink = Callable[..., None]  # matches ExecutionContext.report_usage's kwargs:
# (*, provider: str, model: str, input_tokens: int, output_tokens: int,
#  response_model: str | None = None, cache_read_tokens: int | None = None,
#  cache_creation_tokens: int | None = None, reasoning_tokens: int | None = None,
#  cost_usd: Decimal | None = None) -> None
# INVARIANT: every kwarg after `output_tokens` is OPTIONAL. This is a live seam with callers already
# written against it, so an adapter that learns nothing about caching or cost must be able to say
# nothing rather than be forced to invent a zero.

_usage_sink: contextvars.ContextVar[UsageSink | None] = contextvars.ContextVar(
    "url4_usage_sink", default=None
)


def current_usage_sink() -> UsageSink | None:
    """The usage sink bound to the currently-resolving node's span, or ``None``
    when no observer is attached / outside a node resolve.

    World adapters (e.g. an AI-gateway connector) call this to report model
    token usage without holding an :class:`~url4.dag.node.ExecutionContext` —
    the executor binds it around each node's ``resolve`` (see
    :meth:`~url4.dag.executor.Executor._eval`), scoped to that node's own
    :class:`asyncio.Task` so concurrent siblings never cross-talk.
    """
    return _usage_sink.get()


ResponseSink = Callable[..., None]  # matches ExecutionContext.report_response's kwargs:
# (*, finish_reason: str | None, refusal: str | None,
#     cache_status: Literal["hit", "miss", "bypass"] | None = None,
#     cache_reason: str | None = None) -> None
# INVARIANT: the two cache kwargs are OPTIONAL. This is a live seam with callers already written
# against it, and an adapter that learns no cache outcome must be able to say nothing rather
# than be forced to invent one.

_response_sink: contextvars.ContextVar[ResponseSink | None] = contextvars.ContextVar(
    "url4_response_sink", default=None
)


def current_response_sink() -> ResponseSink | None:
    """The response sink bound to the currently-resolving node's span, or
    ``None`` when no observer is attached / outside a node resolve.

    The :class:`ModelResponse` counterpart of :func:`current_usage_sink`, bound
    by the same executor hook with the same per-:class:`asyncio.Task` scoping.
    WHY a second sink rather than widening the usage one: a world adapter learns
    a call's finish reason even when the provider reports no usage at all, and
    the two facts have different lifetimes on the wire.
    """
    return _response_sink.get()


class LogSink(Protocol):
    """Best-effort structured emission for the active node, on its loop thread.

    No I/O or tasks are created. Invalid, expired and off-thread submissions
    silently drop. Attributes are flat scalars; this is not content redaction.
    Producer schemas must separately bound record size and emission rate.
    """

    def __call__(
        self,
        body: str,
        attributes: Mapping[str, LogScalar] | None = None,
        *,
        severity: str = "INFO",
    ) -> None: ...


class _LogEmitter(Protocol):
    def __call__(
        self,
        severity: str,
        body: str,
        *,
        attributes: Mapping[str, LogScalar] | None = None,
    ) -> None: ...


def _log_attributes(attributes: Mapping[str, LogScalar] | None) -> dict[str, LogScalar]:
    if attributes is None:
        return {}
    if not isinstance(attributes, Mapping):
        raise ValueError("invalid attributes")
    snapshot = dict(attributes)
    for key, value in snapshot.items():
        if type(key) is not str or type(value) not in (str, int, float, bool, type(None)):
            raise ValueError("invalid scalar")
        if type(value) is float and not math.isfinite(value):
            raise ValueError("nonfinite scalar")
    return snapshot


class _NodeLogSink:
    def __init__(self, emit: _LogEmitter) -> None:
        self._emit = emit
        self._thread = threading.get_ident()
        self.active = True

    def __call__(
        self,
        body: str,
        attributes: Mapping[str, LogScalar] | None = None,
        *,
        severity: str = "INFO",
    ) -> None:
        if not self.active or threading.get_ident() != self._thread:
            return
        try:
            if type(body) is not str or not body or type(severity) is not str:
                return
            normalized = severity.strip().upper()
            if normalized not in ("DEBUG", "INFO", "WARN", "ERROR"):
                return
            self._emit(normalized, body, attributes=_log_attributes(attributes))
        except Exception:
            # WHY: only this opt-in emission path is fail-open. No diagnostic
            # logging here: it could recurse, leak payload or fail through a handler.
            # BaseException (cancellation/process control) deliberately propagates.
            pass


_log_sink: contextvars.ContextVar[_NodeLogSink | None] = contextvars.ContextVar(
    "url4_log_sink", default=None
)


def current_log_sink() -> LogSink | None:
    """Return the active node's sink, or None outside/after its resolve.

    Child tasks inherit the binding. Observed nested runs bind their own;
    unobserved nested runs inherit an active outer without creating a span.
    Retained callables silently drop after expiry, including in copied contexts.
    """
    sink = _log_sink.get()
    return sink if sink is not None and sink.active else None


@contextlib.contextmanager
def _bind_node_sinks(
    usage: UsageSink, response: ResponseSink, log: _LogEmitter | None = None
) -> Iterator[None]:
    """Bind ctx-less sinks to the currently-resolving node, for the duration
    of its own ``resolve`` only.

    Lives here rather than in the executor because the ContextVars are this
    module's private state — the executor should not have to reach into them to
    scope a binding it does not own. Takes explicit bound callables rather than an
    ``ExecutionContext`` so this module stays the dependency-free leaf its
    docstring promises (``url4.dag.node`` imports *this*, never the reverse).

    INVARIANT: no cross-talk between concurrent siblings. ContextVar values are
    copied into each :class:`asyncio.Task`'s context at creation, so every
    sibling node sees its own binding, never another's.

    INVARIANT: bindings are restored when the node resolve exits on
    the success path and the failure path alike.
    """
    sink = _NodeLogSink(log) if log is not None else None
    log_token = _log_sink.set(sink)
    usage_token = _usage_sink.set(usage)
    response_token = _response_sink.set(response)
    try:
        yield
    finally:
        # INVARIANT: resetting ContextVars alone cannot revoke copied child contexts.
        if sink is not None:
            sink.active = False
        _log_sink.reset(log_token)
        _usage_sink.reset(usage_token)
        _response_sink.reset(response_token)


__all__ = [
    "Log",
    "LogScalar",
    "LogSink",
    "ModelResponse",
    "NodeFinished",
    "NodeStarted",
    "NullObserver",
    "ObservationEvent",
    "Observer",
    "ResponseSink",
    "RunFinished",
    "RunStarted",
    "Usage",
    "UsageSink",
    "current_log_sink",
    "current_response_sink",
    "current_usage_sink",
]
