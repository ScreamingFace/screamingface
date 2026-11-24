"""The control-plane log lines that outlive a run's frames (OME-940).

FEATURE: a run's whole diagnostic record — its frames on the shared events stream — is purged
(the run's subject, keeping only its terminal frame) `DEFAULT_STREAM_GRACE_S` (60 s) after it
ends, and the pod that produced it is reclaimed soon after. A failed deployed run was therefore
not reconstructable after ~2 minutes. These two lines put the essentials where `kubectl logs`
keeps them for the pod-log window: what was scheduled, under which trace, and how it ended.

INVARIANT: both adapters emit the SAME fields in the SAME order. `InProcessJobRunner` (local)
and `QueueJobRunner` (deployed) are two renderings of one contract, and evidence that differed
between them would mean debugging a deployment with lines a developer has never seen.

WHY this is control-plane and not `runner/main.py`: that module's `_log_terminal` is reached
only from the Job entrypoint, so a local-mode run — which calls `lifecycle.run` directly from
the adapter — emitted nothing at all. The adapters are the one path both modes share.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from decimal import Decimal
from typing import Any, Protocol, cast

from screamingface_engine.candidate_outcomes import (
    OUTCOME_STATUSES,
    CandidateOutcome,
    OutcomeStatus,
    storable_error_code,
)
from screamingface_engine.candidate_record import RUN_SUMMARY_INVALID, CandidateRecordFold
from url4.streaming.interfaces import EventPublisher
from url4.streaming.protocol import (
    ErrorInfo,
    OutboundFrame,
    ResultEvent,
    TerminatedData,
    TerminatedEvent,
)
from url4.streaming.trace import format_traceparent, parse_traceparent, valid_traceparent

SCHEDULED = "run scheduled"
TERMINATED = "run terminated"
SUMMARY_REFUSED = "run summary refused"
"""Stable prefixes. An operator greps these; renaming one breaks a runbook, not a test."""

_logger = logging.getLogger(__name__)


def adopt_or_mint_traceparent(traceparent: str | None) -> str:
    """The traceparent this run will actually carry — the caller's, or a fresh one.

    WHY the control plane mints rather than letting `url4.streaming.lifecycle.run` do it: the
    lifecycle mints internally and AFTER the adapter has returned, so the control plane could
    not name the run it had just scheduled, and `job_env.TRACEPARENT` stayed unset — which left
    the runner's whole log context (`logs.run_scope`) with no trace id for exactly those runs.
    Deciding it here means one id, known from the first line onward, with no `pending` state.

    It is also what W3C describes: a service that receives no trace context starts the trace
    where the request arrives, not deep inside its own run loop.

    An INVALID inbound value is replaced, not propagated — the same restart rule
    `valid_traceparent` applies everywhere else. A malformed parent that was forwarded would
    correlate nothing while looking correct in every log it reached.
    """
    adopted = valid_traceparent(traceparent)
    if adopted is not None:
        return adopted
    return format_traceparent(secrets.token_hex(16), secrets.token_hex(8))


def trace_id_of(traceparent: str) -> str:
    """The 32-hex trace id inside a traceparent, or ``none`` if it holds none."""
    return parse_traceparent(traceparent) or "none"


def log_scheduled(logger: logging.Logger, *, topic: str, traceparent: str, job_name: str) -> None:
    """Record topic <-> trace_id <-> job name — a correspondence stored nowhere before this.

    Without it, an operator holding a trace id from a user's bug report has no way to reach the
    Job that ran it, and an operator holding a Job name cannot find the trace.
    """
    logger.info(
        "%s topic=%s trace_id=%s job_name=%s",
        SCHEDULED,
        topic,
        trace_id_of(traceparent),
        job_name,
    )


def log_terminated(
    logger: logging.Logger,
    *,
    topic: str,
    traceparent: str,
    outcome: str,
    error: str | None = None,
) -> None:
    """Record how the run ended, for EVERY outcome.

    INVARIANT: emitted for failures too. `runner/main.py::_log_terminal` returned early unless
    the outcome was `succeeded`, so the run whose evidence is actually needed — the failed one —
    carried no trace id anywhere. That is inverted from the point of durable evidence.

    The error is named by TYPE and message, never by traceback: this line is the durable record,
    and a multi-line traceback in it would be split across log entries by most collectors.
    """
    fields = [
        f"topic={topic}",
        f"trace_id={trace_id_of(traceparent)}",
        f"outcome={outcome}",
    ]
    if error is not None:
        fields.append(f"error={error}")
    logger.info("%s %s", TERMINATED, " ".join(fields))


class TerminalWatch(EventPublisher):
    """Wraps a publisher to remember how the run ended, without changing what is published.

    INVARIANT: the outcome comes from the run's own `Terminated` FRAME, never from the asyncio
    task. `lifecycle.run` CATCHES a failing run and publishes `Terminated(status="failed")` on
    the way out — it does not re-raise — so the task completes normally and
    `task.exception()` is `None` for a run that failed outright. Deriving the outcome from the
    task therefore reports `succeeded` for every failure, which is the one case this evidence
    exists to record. A test caught exactly that.

    A transparent proxy rather than a stream re-read: `_on_done` fires after the frames are
    gone from an in-memory publisher's perspective, and re-subscribing to read one field would
    race the 60 s reclamation this whole feature exists to outlive.
    """

    def __init__(self, inner: EventPublisher) -> None:
        self._inner = inner
        self.outcome: str | None = None
        self.error: str | None = None

    async def ensure_stream(self, topic: str) -> None:
        await self._inner.ensure_stream(topic)

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        if isinstance(event, TerminatedEvent):
            self.outcome = event.data.status
            detail = event.data.error
            if detail is not None:
                self.error = f"{detail.code}: {detail.message}"
        await self._inner.publish(topic, event)

    async def flush(self) -> None:
        await self._inner.flush()


def outcome_of(watch: TerminalWatch, task: asyncio.Task[object]) -> tuple[str, str | None]:
    """How the run ended: the terminal frame's verdict, with the task as a fallback.

    The fallback is not decoration. If the task was cancelled or raised *before*
    `lifecycle.run` could publish anything — a scheduling failure, a cancelled task, a broken
    publisher — there is no frame to read, and a run that vanished with no evidence line at all
    is precisely the hole being closed.
    """
    if watch.outcome is not None:
        return watch.outcome, watch.error
    return _outcome_without_a_frame(task)


def _outcome_without_a_frame(task: asyncio.Task[object]) -> tuple[str, str | None]:
    """The run ended before publishing a terminal frame — read the task instead.

    `unknown` is deliberate and is NOT folded into `failed`: a run that produced no terminal
    frame and no exception is a state the engine has no account of, and calling it `failed`
    would state an outcome nobody observed. Naming it is what makes it findable.
    """
    if task.cancelled():
        return "stopped", None
    error = task.exception()
    if error is None:
        return "unknown", "the run published no terminal frame"
    return "failed", f"{type(error).__name__}: {error}"


class TerminalPublisher(Protocol):
    """The slice of an events publisher a terminal writer needs."""

    async def publish(self, topic: str, event: OutboundFrame) -> None: ...


async def publish_landed(publisher: TerminalPublisher, topic: str, frame: TerminatedEvent) -> bool:
    """Publish a terminal frame from a writer that is not the run, and say whether it landed.

    FEATURE (OME-1785, E5 P1 spec R3): a writer publishes its Candidate's outcome only when its
    own terminal frame is the one on `url4-events`. The JetStream publisher's `publish_next`
    writes nothing after another terminal frame and says so; a publisher without it has no such
    rule, so its frame lands.
    """
    publish_next = getattr(publisher, "publish_next", None)
    if publish_next is None:
        await publisher.publish(topic, frame)
        return True
    return bool(await publish_next(topic, frame))


NO_TERMINAL_FRAME = "no_terminal_frame"
"""The error code of a Candidate whose run ended without a terminal frame (OME-1785)."""


class SettlementWatch(TerminalWatch):
    """A `TerminalWatch` that also keeps the terminal frame's error CODE, which a Candidate's
    outcome stores on its own (E5 P1 spec R3). `error` stays the evidence line's `code: message`.

    INVARIANT (spec R3): ``landed`` is the status of the last terminal frame the inner publisher
    ACCEPTED. A publish that raises leaves it unchanged, so a frame that never reached
    `url4-events` never becomes an outcome.

    ``record`` (E5 P2 spec §4.3) is given for a driver-started run only. It folds the frames the
    inner publisher accepted, so the record states what a follower could have seen. Its producer
    also binds it for the run's task (`binding_record`), where the executor reads its refusal.

    INVARIANT (OME-1988): once the record has refused the run's summary, the inner publisher
    gets no result frame, and the run's `succeeded` terminal frame as `failed` with
    `run_summary_invalid`, the error the `Url4Executor` fails such a run with. So the durable
    tail, a follower, an R7 settle, the evidence line (`outcome_of`), the runner's verdict and
    the outcome (`settlement_of`) all read the one refusal. Only an executor that does not read
    `bound_refusal` reaches this; the `Url4Executor` fails the run before its result.
    """

    def __init__(self, inner: EventPublisher, *, record: CandidateRecordFold | None = None) -> None:
        super().__init__(inner)
        self.error_code: str | None = None
        self.landed: str | None = None
        self._record = record
        # How many frames of the run this watch withheld from the inner publisher.
        self._withheld = 0

    def record(self) -> dict[str, Any] | None:
        """The run's record, cut to fit; None for a run nobody asked one of."""
        return None if self._record is None else self._record.record()

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        refusal = None if self._record is None else self._record.refusal
        if refusal is not None:
            # AIDEV-NOTE: the backstop (class docstring). The run's last log is folded before
            # its result frame (url4's lifecycle publishes every step before the result), so
            # the refusal is known by then. WHY withheld and not raised: a publish that raises
            # is a publisher failure to the run (`EventPublisher.publish`); the refusal is the
            # run's verdict, and its terminal frame carries it.
            if isinstance(event, ResultEvent):
                self._withheld += 1
                return
            event = self._as_refused(event, refusal)
        await super().publish(topic, event)
        if self._record is not None:
            known = self._record.malformed
            self._record.observe(event)
            malformed = self._record.malformed
            if known is None and malformed is not None:
                # FEATURE (OME-1988): the run fails `run_summary_invalid`; this names why. The
                # attribute's name only: a figure's value may carry a log's content.
                _logger.warning(
                    "%s topic=%s attribute=%r code=%s",
                    SUMMARY_REFUSED,
                    topic,
                    malformed,
                    RUN_SUMMARY_INVALID,
                )
        if not isinstance(event, TerminatedEvent):
            return
        # INVARIANT: the code and the evidence line's error are the last landed terminal frame's,
        # like `outcome`, so the two records of one run agree (spec R3).
        error = event.data.error
        self.error_code = None if error is None else error.code
        if error is None:
            self.error = None
        self.landed = event.data.status

    def _as_refused(self, event: OutboundFrame, refusal: str) -> OutboundFrame:
        """``event`` as the inner publisher gets it from a run its record refused: a success
        becomes the refusal, and a frame after a withheld one takes the number it left free.

        INVARIANT (`lifecycle._Sequencer`): a run's frames are numbered with no gap, and a
        follower cannot cross one. WHY the frame keeps its id, time and trace context: it is
        still the run's own frame, only its verdict and number change.
        """
        update: dict[str, object] = {}
        if self._withheld and event.sequence is not None:
            update["sequence"] = str(int(event.sequence) - self._withheld)
        if isinstance(event, TerminatedEvent) and event.data.status == "succeeded":
            # The `Url4Executor`'s refusal, as url4's `_error_info` writes it.
            error = ErrorInfo(code=RUN_SUMMARY_INVALID, message=refusal, permanent=True)
            update["data"] = TerminatedData(status="failed", error=error)
        return event.model_copy(update=update) if update else event


def settlement_of(
    watch: SettlementWatch,
    task: asyncio.Task[object],
    *,
    cost_usd: Decimal | None = None,
) -> CandidateOutcome:
    """The Candidate's outcome, from the same verdict as the evidence line.

    INVARIANT (spec R3): one classifier. A landed terminal frame decides it; without one, the
    task decides it, as `outcome_of` does. A run whose record refused its run summary
    (OME-1988) lands a terminal frame that says `failed` with `run_summary_invalid`, whether its
    executor failed it or `SettlementWatch` published its success so, and an R7 settle from it
    agrees.
    """
    if watch.landed is not None:
        return CandidateOutcome(
            _status(watch.landed),
            storable_error_code(watch.error_code),
            cost_usd,
            record=watch.record(),
        )
    status, _ = _outcome_without_a_frame(task)
    if status == "stopped":
        return CandidateOutcome("stopped", cost_usd=cost_usd)
    # WHY `failed` for `unknown` too: a Candidate has no `unknown` state, and nobody saw this run
    # succeed. The code says there was no frame, so the case stays findable.
    return CandidateOutcome("failed", NO_TERMINAL_FRAME, cost_usd)


def _status(value: str) -> OutcomeStatus:
    if value in OUTCOME_STATUSES:
        return cast(OutcomeStatus, value)
    raise ValueError(f"not a terminal frame status: {value!r}")


__all__ = [
    "NO_TERMINAL_FRAME",
    "SCHEDULED",
    "SUMMARY_REFUSED",
    "TERMINATED",
    "adopt_or_mint_traceparent",
    "log_scheduled",
    "log_terminated",
    "SettlementWatch",
    "TerminalWatch",
    "outcome_of",
    "settlement_of",
    "trace_id_of",
]
