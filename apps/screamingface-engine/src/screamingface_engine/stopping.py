"""Stopping a topic's run and deleting its stream: what `DELETE /`, `DELETE /runs/{id}` and the
Engine's driver all do (E5 P1 spec D12; E5 P2 spec R9).

FEATURE: a detached Run (OME-1837). The driver stops a Candidate with no Request in hand, so the
stop lives here. It raises `QueueReadError` when the queue's tail cannot be read; the routes map
that to a retryable 503, and the driver leaves the stop owed for its next tick.

LAYERING: control plane (`.claude/scripts/check_layering.py`).
"""

from __future__ import annotations

from screamingface_engine.ports import IdentityAwareJobRunner
from url4.streaming.interfaces import EventConsumer, JobRunner


async def stop_topic(
    job_runner: JobRunner, stream: EventConsumer, topic: str, *, bound: bool = False
) -> None:
    """`bound`: the topic is a Run's Candidate, which the runner must stop even before it has
    any record of the topic (`IdentityAwareJobRunner.stop_bound`).

    Raises:
        QueueReadError: the queue's tail could not be read, so nothing was stopped or deleted.
    """
    if bound and isinstance(job_runner, IdentityAwareJobRunner):
        await job_runner.stop_bound(topic)
    else:
        await job_runner.stop(topic)
    # WHY delete_stream and not purge: this is the run's terminal teardown, and `delete_stream`
    # purges the subject on the shared events stream while KEEPING the terminal frame — the
    # evidence a run ended (the queue's dedupe gate, the runner's own admission bookkeeping, and
    # a repeated `DELETE /` all read that frame). Plain `purge` drops it too, and an empty
    # subject reads exactly like a run still queued — there is no per-run stream object left to
    # tell the two apart in a shared stream (erd.md §5).
    await stream.delete_stream(topic)


__all__ = ["stop_topic"]
