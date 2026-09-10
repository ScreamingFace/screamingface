"""The control-plane log lines that outlive a run's frame stream (OME-940).

FEATURE: a run's whole diagnostic record — the NATS frame stream — is deleted
`DEFAULT_STREAM_GRACE_S` (60 s) after it ends, and the pod that produced it is reclaimed soon
after. A failed deployed run was therefore not reconstructable after ~2 minutes. These two
lines put the essentials where `kubectl logs` keeps them for the pod-log window: what was
scheduled, under which trace, and how it ended.

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

from url4.streaming.interfaces import EventPublisher
from url4.streaming.protocol import OutboundFrame, TerminatedEvent
from url4.streaming.trace import format_traceparent, parse_traceparent, valid_traceparent

SCHEDULED = "run scheduled"
TERMINATED = "run terminated"
"""Stable prefixes. An operator greps these; renaming one breaks a runbook, not a test."""


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


__all__ = [
    "SCHEDULED",
    "TERMINATED",
    "adopt_or_mint_traceparent",
    "log_scheduled",
    "log_terminated",
    "TerminalWatch",
    "outcome_of",
    "trace_id_of",
]
