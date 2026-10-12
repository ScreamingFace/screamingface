import asyncio
import secrets
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from functools import partial
from typing import Literal, TypedDict
from uuid import uuid4

from url4.streaming.interfaces import (
    Completed,
    EventPublisher,
    ExecStep,
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

# How long the terminal flush may wait for the broker to acknowledge frames it already accepted.
# A healthy broker acks in milliseconds; this only has to turn a stalled one into a prompt raise
# instead of a run that hangs until the worker backstop kills it. It MUST stay below the engine's
# `DEADLINE_MARGIN_S` (30 s, screamingface_engine/worker/supervisor.py): past `deadline_s` plus
# the stream grace, that margin is all the time a child has to exit before the worker declares
# it hung, and a terminal flush that outlives it is cut off without the run's own exit.
_TERMINAL_FLUSH_TIMEOUT_S = 10.0


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
    """Numbers a run's frames, and records whether its terminal frame is out.

    INVARIANT: the published sequence numbers are strictly monotonic and gap-free. A consumer
    finds missing frames by these numbers, so a hole is unrecoverable — on JetStream the client
    cannot accept a terminal frame behind one. A number is therefore only CONSUMED by a publish
    that returned: :meth:`peek` proposes it, :meth:`commit` consumes it after the publish, and a
    publish that raised leaves it for the next frame (``EventPublisher.publish``: a publish that
    raises wrote nothing).

    Trade-off (``model_lifecycle_fix3_commit.py``): an adapter that writes the frame and THEN
    raises (a lost response) breaks that port rule, and the reused number collides with the
    written frame — Nats-Msg-Id dedup then drops the later frame. Burning the number instead
    would leave a hole that every adapter pays for, so the port rule carries this case.
    """

    def __init__(self, topic: str, node: str) -> None:
        self._source = source_for(topic, node)
        self._subject = topic
        self._n = 0
        self.terminal_sent = False

    def peek(self, traceparent: str, tracestate: str | None = None) -> _Envelope:
        """The envelope for the next frame. Consumes nothing until :meth:`commit`."""
        return _Envelope(
            id=uuid4().hex,
            source=self._source,
            subject=self._subject,
            time=datetime.now(UTC),
            sequence=str(self._n + 1),
            sequencetype="Integer",
            traceparent=traceparent,
            tracestate=tracestate,
        )

    def commit(self, env: _Envelope) -> None:
        """Consume ``env``'s number, once its publish returned.

        Raises rather than asserts: ``-O`` strips an assert, and a hole or a reused number must
        stay a loud producer-side failure, not a silent defect in the stream.
        """
        if env["sequence"] != str(self._n + 1):
            got = env["sequence"]
            raise RuntimeError(f"sequence out of order: committing {got} after {self._n}")
        self._n += 1


async def _publish(
    stream: EventPublisher,
    topic: str,
    seq: _Sequencer,
    frame: Callable[[_Envelope], OutboundFrame],
    traceparent: str,
    tracestate: str | None = None,
) -> None:
    """Publish one frame under the next sequence number, consumed only if the publish returns."""
    env = seq.peek(traceparent, tracestate)
    await stream.publish(topic, frame(env))
    seq.commit(env)


async def _aclose(steps: AsyncIterator[ExecStep]) -> None:
    """Close the executor's step stream in THIS task.

    WHY: ``_publish_execution`` stops reading at ``Completed``. Left open, the generator is
    finalized later by the event loop's asyncgen hook in ANOTHER task, so the executor's cleanup
    (closing its world) races the rest of the run and its errors reach the loop's exception
    handler instead of ``run``. The port promises only ``AsyncIterator``, so an iterator with no
    ``aclose`` has nothing to close.
    """
    aclose = getattr(steps, "aclose", None)
    if aclose is not None:
        await aclose()


async def _aclose_keeping(steps: AsyncIterator[ExecStep], exit_exc: BaseException) -> None:
    """Close the step stream while ``exit_exc`` is already leaving ``run``.

    The run's own exit wins (a cancellation must stay a cancellation); a teardown failure is kept
    on it as a note instead of being lost.
    """
    try:
        await _aclose(steps)
    except Exception as teardown:
        exit_exc.add_note(f"executor teardown also failed: {teardown!r}")


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
        # "internal_error" deliberately mirrors ErrorCode.INTERNAL_ERROR as a bare
        # literal: url4.streaming is a concepts-only wire contract and must not
        # import url4.core (see test_import_isolation).
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

    INVARIANT: every exit path from :func:`run` after the stream exists goes through here, so a
    subscriber is guaranteed a terminal frame no matter how the run ended. The frame carries the
    run's OWN ``root_tp`` and the next sequence number, which is why termination cannot be bolted
    on by a caller wrapping ``run`` — neither value is visible from outside.

    INVARIANT: at most ONE terminal frame. ``seq.terminal_sent`` is set the moment the publish
    returns; from then on every arm in ``run`` re-raises instead of terminating again, so a flush
    failure or a cancel that lands during the flush below cannot add a second, contradicting
    frame (``4:succeeded 5:failed``).

    A flush failure here RAISES, whatever the outcome: the terminal frame may not be durable, and
    only a run that exits non-zero triggers the worker backstop. ``EventPublisher.flush`` discards
    failures it already reported, so this is always a NEW failure, about the terminal frame.
    """
    data = TerminatedData(status=status, error=error)
    await _publish(stream, topic, seq, lambda env: TerminatedEvent(**env, data=data), root_tp)
    seq.terminal_sent = True
    # The terminal frame is the one frame a subscriber is guaranteed, so `run` must not return
    # while it is still only queued. WHY bounded: the run's deadline no longer applies here (the
    # outcome is decided), and a broker's ack future may have no timeout of its own — nats-py's
    # has none — so an unbounded flush hangs the run until the worker backstop kills it.
    bound = asyncio.timeout(_TERMINAL_FLUSH_TIMEOUT_S)
    try:
        async with bound:
            await stream.flush()
    except TimeoutError as exc:
        if not bound.expired():  # the adapter's own timeout, not this bound
            raise
        raise TimeoutError(f"terminal flush exceeded {_TERMINAL_FLUSH_TIMEOUT_S:g}s") from exc


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


async def _publish_telemetry(
    stream: EventPublisher,
    steps: AsyncIterator[ExecStep],
    topic: str,
    seq: _Sequencer,
    root_ctx: TraceContext,
    root_tp: str,
) -> Completed | None:
    """Publish the executor's telemetry up to its ``Completed`` outcome, and return that."""
    async for step in steps:
        if isinstance(step, Completed):
            return step
        if isinstance(step, Traced):
            payload, span_ref = step.payload, step.span
        else:
            payload, span_ref = step, None
        tp, ts = _trace_fields(payload, span_ref, root_ctx, root_tp)
        await _publish(stream, topic, seq, partial(_wrap_telemetry, data=payload), tp, ts)
    return None


async def _publish_execution(
    stream: EventPublisher,
    steps: AsyncIterator[ExecStep],
    topic: str,
    url4: str,
    seq: _Sequencer,
    root_ctx: TraceContext,
    root_tp: str,
) -> None:
    """Publish everything a SUCCESSFUL run emits: Started, its telemetry, then cost and result.

    Split out of :func:`_drive` so that function reads as what it is — the run's outcome policy,
    which picks the terminal status from the exception that reaches it. Raising out of here is how
    a failed, timed-out or stopped outcome is selected, so nothing is caught in this function.
    """
    started = StartedData(url4=url4)
    await _publish(stream, topic, seq, lambda env: StartedEvent(**env, data=started), root_tp)
    completed = await _publish_telemetry(stream, steps, topic, seq, root_ctx, root_tp)
    if completed is None:
        raise _IncompleteExecution("executor produced no Completed outcome")
    subtree = completed.subtree_cost.model_copy(update={"scope": "subtree"})
    await _publish(stream, topic, seq, lambda env: CostUsageEvent(**env, data=subtree), root_tp)
    result = completed.result
    await _publish(stream, topic, seq, lambda env: ResultEvent(**env, data=result), root_tp)
    # INVARIANT: durability is settled BEFORE the outcome is. A publisher may defer its
    # acknowledgements (see `EventPublisher.publish`), so without this barrier `run` could
    # publish `succeeded` over a stream that silently lost a span frame — and a consumer
    # cannot tell that from a complete one.
    #
    # WHY here rather than in `run`: this function raises to select `run`'s outcome arm, so
    # a deferred failure reported here reaches the `failed` arm with no new control flow.
    await stream.flush()


async def _drive(
    stream: EventPublisher,
    steps: AsyncIterator[ExecStep],
    topic: str,
    url4: str,
    seq: _Sequencer,
    root_ctx: TraceContext,
    root_tp: str,
    deadline_s: float | None,
) -> None:
    """The run's outcome policy: produce the outcome, then publish its ONE terminal frame."""
    # WHY the context manager is bound to a name: `expired()` is the only way to tell OUR deadline
    # firing apart from a TimeoutError raised by the run's own code (an httpx read timeout, say).
    # Without it a slow upstream would be misreported as the run exceeding its deadline.
    deadline = asyncio.timeout(deadline_s)
    try:
        async with deadline:
            await _publish_execution(stream, steps, topic, url4, seq, root_ctx, root_tp)
        # WHY outside the `async with`: the result is already computed by here, so terminating
        # must not be subject to the deadline that bounded producing it.
        await _terminate(stream, topic, seq, root_tp, "succeeded")
    except asyncio.CancelledError as cancel:
        if seq.terminal_sent:  # cancelled during the terminal flush: the outcome is already out
            raise
        # WHY terminate before re-raising: cancellation is how an in-process runner implements
        # `stop`, and a cancelled task that published nothing would leave every subscriber waiting
        # forever — a sync GET holding to `sync_max_wait_s`, a WS client seeing only heartbeats.
        # `CancelledError` is a BaseException, so the `except Exception` arm below never saw it.
        try:
            await _terminate(stream, topic, seq, root_tp, "stopped")
        except Exception as failure:
            # The cancellation wins, so a broken publish or flush cannot mask the stop itself;
            # the failure stays on the chain.
            raise cancel from failure
        raise
    except Exception as exc:
        if seq.terminal_sent:  # the terminal flush failed: never publish a second outcome
            raise
        # WHY `expired()` and not the exception type: an adapter may convert the deadline's
        # cancellation into its own error (nats-py raises `TooManyStalledMsgsError` from a publish
        # waiting on its in-flight window), and a run's own code may raise a `TimeoutError` that is
        # not ours. Only the deadline's own state says whether the run exceeded it.
        status = "timed_out" if deadline.expired() else "failed"
        await _terminate(stream, topic, seq, root_tp, status, _error_info(exc))


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

    Publishes AT MOST one terminal frame on every path, and exactly one when the termination path
    is reliable (the terminal publish itself succeeds) and ``deadline_s`` is not ``None`` — an
    unbounded run that never ends never terminates.

    RETURNS when the outcome — ``succeeded``, ``failed`` or ``timed_out`` — is published and
    durable. RAISES when that is not known: the terminal publish failed, or its flush failed or
    outlived its bound (on EVERY outcome, since the frame may not be durable), or the executor's
    teardown failed after the terminal frame stood. WHY raise: a non-zero exit is what triggers
    the worker backstop, and the backstop's tail check publishes its own frame only when ours is
    missing, so raising can never duplicate the terminal frame. A ``stopped`` run re-raises its
    ``CancelledError``; a terminal failure on that path is chained to it, never raised instead.

    The executor's step stream is closed in this task AFTER the terminal frame is published and
    outside the deadline, so a slow teardown neither delays the outcome nor turns a finished run
    into ``timed_out``.

    ``ensure_stream`` is OUTSIDE the termination guarantee: when it raises there is no stream to
    publish a terminal frame to, so ``run`` raises with nothing published and the caller (the job
    runner, whose backstop names the outcome) owns that failure.
    """
    await stream.ensure_stream(topic)
    seq = _Sequencer(topic, node)
    inbound_trace_id = parse_traceparent(traceparent)
    root_ctx = TraceContext(
        trace_id=inbound_trace_id if inbound_trace_id is not None else secrets.token_hex(16),
        root_span_id=secrets.token_hex(8),
    )
    root_tp = format_traceparent(root_ctx.trace_id, root_ctx.root_span_id)
    steps = executor.execute(url4, trace=root_ctx)
    try:
        await _drive(stream, steps, topic, url4, seq, root_ctx, root_tp, deadline_s)
    except BaseException as exc:
        await _aclose_keeping(steps, exc)
        raise
    await _aclose(steps)
