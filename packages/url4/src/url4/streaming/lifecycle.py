import asyncio
import contextlib
import secrets
from datetime import UTC, datetime
from typing import Literal, TypedDict
from uuid import uuid4

from url4.streaming.interfaces import (
    Completed,
    EventPublisher,
    Executor,
    SpanRef,
    Telemetry,
    TraceContext,
    Traced,
)
from url4.streaming.protocol import (
    CostUsageEvent,
    ErrorInfo,
    LogData,
    LogEvent,
    OutboundFrame,
    ResultEvent,
    SpanData,
    SpanEvent,
    StartedData,
    StartedEvent,
    TerminatedData,
    TerminatedEvent,
    source_for,
)
from url4.streaming.trace import format_parent_tracestate, format_traceparent, parse_traceparent


class _Envelope(TypedDict):
    id: str
    source: str
    subject: str
    time: datetime
    sequence: str
    sequencetype: Literal["Integer"]
    traceparent: str
    tracestate: str | None


class _IncompleteExecution(Exception):
    pass


class _Sequencer:
    def __init__(self, topic: str, node: str) -> None:
        self._source = source_for(topic, node)
        self._subject = topic
        self._n = 0

    def next(self, traceparent: str, tracestate: str | None = None) -> _Envelope:
        self._n += 1
        return _Envelope(
            id=uuid4().hex,
            source=self._source,
            subject=self._subject,
            time=datetime.now(UTC),
            sequence=str(self._n),
            sequencetype="Integer",
            traceparent=traceparent,
            tracestate=tracestate,
        )


def _wrap_telemetry(env: _Envelope, data: Telemetry) -> OutboundFrame:
    if isinstance(data, LogData):
        return LogEvent(**env, data=data)
    if isinstance(data, SpanData):
        return SpanEvent(**env, data=data)
    return CostUsageEvent(**env, data=data)


def _error_info(exc: BaseException) -> ErrorInfo:
    code = getattr(exc, "code", None)
    permanent = getattr(exc, "permanent", None)
    return ErrorInfo(
        code=code if isinstance(code, str) else "internal_error",
        message=str(exc) or exc.__class__.__name__,
        permanent=permanent if isinstance(permanent, bool) else True,
    )


async def _terminate(
    stream: EventPublisher,
    topic: str,
    seq: _Sequencer,
    root_tp: str,
    status: Literal["succeeded", "failed", "stopped", "timed_out"],
    error: ErrorInfo | None = None,
) -> None:
    """Publish the run's single terminal frame.

    INVARIANT: every exit path from :func:`run` goes through here, so a subscriber is guaranteed a
    terminal frame no matter how the run ended. The frame carries the run's OWN ``root_tp`` and the
    next sequence number, which is why termination cannot be bolted on by a caller wrapping
    ``run`` — neither value is visible from outside.
    """
    await stream.publish(
        topic,
        TerminatedEvent(**seq.next(root_tp), data=TerminatedData(status=status, error=error)),
    )
    # The terminal frame is the one frame a subscriber is guaranteed, so `run` must not
    # return while it is still only queued. Each arm in `run` keeps its own policy for a
    # raise from here — the cancellation arm suppresses it, exactly as it already did for a
    # failing publish.
    await stream.flush()


def _trace_fields(
    payload: Telemetry, span_ref: SpanRef | None, root_ctx: TraceContext, root_tp: str
) -> tuple[str, str | None]:
    """Resolve the ``traceparent``/``tracestate`` a frame is published under.

    INVARIANT: attribution follows the SPAN, not the payload type. Any frame the executor tagged
    with a :class:`SpanRef` — a span, a per-node ``cost.usage``, a log line — is published under
    that span's traceparent; only genuinely run-level frames fall back to ``root_tp``.

    This used to test ``isinstance(payload, SpanData)`` as well, which silently discarded the
    span on every other frame type. The effect was that all `scope="self"` cost frames in a run
    were published under one identical traceparent, so a consumer could not tell WHICH node spent
    the tokens and could not reconcile per-node cost against the subtree total — defeating the
    per-node accounting the engine goes to trouble to produce (`ctx.report_usage` and `ctx.log`
    both attribute to the current span id). Log lines lost their node the same way.
    """
    if span_ref is not None:
        traceparent = format_traceparent(root_ctx.trace_id, span_ref.span_id)
        parent = span_ref.parent_span_id
        if parent is None or parent == root_ctx.root_span_id:
            return traceparent, None
        return traceparent, format_parent_tracestate(parent)
    return root_tp, None


async def _publish_execution(
    stream: EventPublisher,
    executor: Executor,
    topic: str,
    url4: str,
    seq: _Sequencer,
    root_ctx: TraceContext,
    root_tp: str,
) -> None:
    """Publish everything a SUCCESSFUL run emits: Started, its telemetry, then cost and result.

    Split out of :func:`run` so that function reads as what it is — the run's outcome policy,
    one ``except`` arm per way a run can end. Raising out of here is how each of those arms is
    reached, so nothing is caught in this function.
    """
    await stream.publish(topic, StartedEvent(**seq.next(root_tp), data=StartedData(url4=url4)))
    completed: Completed | None = None
    async for step in executor.execute(url4, trace=root_ctx):
        if isinstance(step, Completed):
            completed = step
            break
        if isinstance(step, Traced):
            payload, span_ref = step.payload, step.span
        else:
            payload, span_ref = step, None
        tp, ts = _trace_fields(payload, span_ref, root_ctx, root_tp)
        await stream.publish(topic, _wrap_telemetry(seq.next(tp, ts), payload))
    if completed is None:
        raise _IncompleteExecution("executor produced no Completed outcome")
    subtree = completed.subtree_cost.model_copy(update={"scope": "subtree"})
    await stream.publish(topic, CostUsageEvent(**seq.next(root_tp), data=subtree))
    await stream.publish(topic, ResultEvent(**seq.next(root_tp), data=completed.result))
    # INVARIANT: durability is settled BEFORE the outcome is. A publisher may defer its
    # acknowledgements (see `EventPublisher.publish`), so without this barrier `run` could
    # publish `succeeded` over a stream that silently lost a span frame — and a consumer
    # cannot tell that from a complete one.
    #
    # WHY here rather than in `run`: this function raises to select `run`'s outcome arm, so
    # a deferred failure reported here reaches the `failed` arm with no new control flow.
    await stream.flush()


async def run(
    stream: EventPublisher,
    executor: Executor,
    topic: str,
    url4: str,
    *,
    node: str = "root",
    traceparent: str | None = None,
    deadline_s: float | None = None,
) -> None:
    """Drive one run to completion, publishing its whole CloudEvents lifecycle to ``stream``.

    ``deadline_s`` bounds the run; ``None`` leaves it unbounded. Exceeding it terminates the run
    as ``timed_out`` rather than letting the substrate kill the process, which would leave the
    stream with no terminal frame at all.
    """
    await stream.ensure_stream(topic)
    seq = _Sequencer(topic, node)
    inbound_trace_id = parse_traceparent(traceparent)
    root_ctx = TraceContext(
        trace_id=inbound_trace_id if inbound_trace_id is not None else secrets.token_hex(16),
        root_span_id=secrets.token_hex(8),
    )
    root_tp = format_traceparent(root_ctx.trace_id, root_ctx.root_span_id)
    # WHY the context manager is bound to a name: `expired()` is the only way to tell OUR deadline
    # firing apart from a TimeoutError raised by the run's own code (an httpx read timeout, say).
    # Without it a slow upstream would be misreported as the run exceeding its deadline.
    deadline = asyncio.timeout(deadline_s)
    try:
        async with deadline:
            await _publish_execution(stream, executor, topic, url4, seq, root_ctx, root_tp)
        # WHY outside the `async with`: the result is already computed by here, so terminating
        # must not be subject to the deadline that bounded producing it.
        await _terminate(stream, topic, seq, root_tp, "succeeded")
    except TimeoutError as exc:
        status = "timed_out" if deadline.expired() else "failed"
        await _terminate(stream, topic, seq, root_tp, status, _error_info(exc))
    except asyncio.CancelledError:
        # WHY terminate before re-raising: cancellation is how an in-process runner implements
        # `stop`, and a cancelled task that published nothing would leave every subscriber waiting
        # forever — a sync GET holding to `sync_max_wait_s`, a WS client seeing only heartbeats.
        # `CancelledError` is a BaseException, so the `except Exception` arm below never saw it.
        # Suppressing a failure here keeps a broken publish from masking the cancellation itself.
        with contextlib.suppress(Exception):
            await _terminate(stream, topic, seq, root_tp, "stopped")
        raise
    except Exception as exc:
        await _terminate(stream, topic, seq, root_tp, "failed", _error_info(exc))
