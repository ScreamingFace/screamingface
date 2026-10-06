"""Which finished runs keep their frames past the reclaim grace (OME-946).

FEATURE: post-mortem of a failed deployed run. Both reclaim paths — the worker's detached
`_schedule_reclaim` (RECLAIM_OWNER=worker) and the runner's own `run_and_reclaim` (no pool) —
purge a finished run's subject `STREAM_GRACE_S` (60 s) after it ends. For a FAILED run that
purge destroyed the only diagnostic record, so a run that failed was unreconstructable within
a minute. A subject whose terminal frame says `failed` or `timed_out` is now skipped, and the
shared `url4-events` stream's `max_age` (24 h, `adapters.jetstream.EventsStream`) reaps it.

WHY by the subject's TAIL and not by how the process ended: `lifecycle.run` publishes
`Terminated(failed)` and RETURNS normally, so a child that failed its run still exits 0 and a
runner's `run_once` does not raise. The terminal frame is the one account both paths share.

CAPPED (OME-1462, owner decision 2026-10-02): a retained subject is trimmed to its newest
`retained_max_msgs` frames and `retained_max_bytes` of payload, terminal frame always kept
(`adapters.jetstream._JetStreamConnection.trim_retained`), so a failure storm costs at most
the cap per failed run instead of filling the shared stream.

AIDEV-NOTE: retention here is best-effort, not a guarantee. The events stream is `discard=OLD`
with a 1 GiB `max_bytes`: under load JetStream drops the OLDEST frames of any subject, so a
retained failed run can still be evicted well before 24 h. That is deliberate — retention must
never push the store into refusing LIVE runs' frames. Durable evidence is the Phase 2 OTLP
exporter's job; this is the stopgap.

INVARIANT: only {failed, timed_out} are retained. A successful run's frames carry full prompt
and response bodies, so extending their life is a cost AND an exposure; `stopped` (an owner's
cancel, a drain) is not a failure to investigate.

This module is a shared leaf (see `.claude/scripts/check_layering.py`): the worker and the run
mode both import it, and it imports neither.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from screamingface_engine.adapters.jetstream import QueueReadError
from url4.streaming.protocol import OutboundFrame, TerminatedEvent

logger = logging.getLogger(__name__)

RETAINED_STATUSES: frozenset[str] = frozenset({"failed", "timed_out"})
"""Terminal statuses whose subject skips the grace purge and waits for `max_age`."""


def retains_evidence(frame: OutboundFrame | None) -> bool:
    """Whether a subject ending in ``frame`` keeps its frames past the reclaim grace."""
    return isinstance(frame, TerminatedEvent) and frame.data.status in RETAINED_STATUSES


async def subject_retained(
    last_frame: Callable[[str], Awaitable[OutboundFrame | None]], topic: str
) -> bool:
    """Read ``topic``'s tail and apply `retains_evidence`.

    WHY an unreadable tail purges: an unknown ending must not extend a possibly SUCCESSFUL
    run's prompt-bearing frames — it gets the pre-OME-946 behaviour. A broker blip that breaks
    this read usually breaks the purge after it too, which leaves the frames to `max_age`.
    """
    try:
        frame = await last_frame(topic)
    except QueueReadError:
        logger.warning("tail of %s unreadable; reclaiming without the failure check", topic)
        return False
    except Exception:
        # WHY broad (OME-1462): the rule above is about an UNKNOWN ending, whatever made it
        # unknown. Only `QueueReadError` reached it before; a connect failing with `OSError`
        # (or anything else) escaped to the caller's teardown guard, which skips the purge —
        # so a possibly successful run's frames sat for `max_age`. `CancelledError` is a
        # `BaseException` and still unwinds a stopping worker.
        logger.warning(
            "tail of %s unreadable; reclaiming without the failure check", topic, exc_info=True
        )
        return False
    return retains_evidence(frame)
