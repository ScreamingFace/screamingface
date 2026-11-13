"""The one stop path: stop a topic's run and purge its stream (spec §5 `DELETE /`).

Shared by `DELETE /` (`rest.routes`) and `DELETE /runs/{id}` (`rest.runs`, E5 P1 spec D12), so a
Run's cancel stops each Candidate exactly as its own client would.
"""

from __future__ import annotations

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.auth import ProblemException
from screamingface_engine.stopping import stop_topic as core_stop_topic
from url4.streaming.interfaces import EventConsumer, JobRunner

# WHY 5 and not the capacity path's constant 1: an unreachable broker is a reconnect or a
# failover in flight, which takes seconds — a client told to retry in 1 s spends its retries
# inside the outage. There is no drain estimate to derive a better value from.
# INVARIANT: every "broker down" 503 (unreadable queue tail, unavailable queue at schedule time)
# uses THIS value; the capacity 503 keeps its drain estimate.
QUEUE_UNAVAILABLE_RETRY_AFTER_S = 5


async def stop_topic(
    job_runner: JobRunner, stream: EventConsumer, topic: str, *, bound: bool = False
) -> None:
    """`stopping.stop_topic`, answering an unreadable queue tail with a retryable 503.

    `bound`: the topic is a Run's Candidate, which the runner must stop even before it has
    any record of the topic (`IdentityAwareJobRunner.stop_bound`).
    """
    try:
        await core_stop_topic(job_runner, stream, topic, bound=bound)
    except QueueReadError:
        # V-2: an unreadable tail used to make `stop()` a SILENT no-op, and this handler
        # fell through to deleting the stream of a possibly-live run while answering 204.
        # The raise keeps the state unchanged and the answer honest: 503, retryable, and
        # the stream deletion does not run.
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="the run queue could not be read; retry",
            headers={"Retry-After": str(QUEUE_UNAVAILABLE_RETRY_AFTER_S)},
        ) from None


__all__ = ["QUEUE_UNAVAILABLE_RETRY_AFTER_S", "stop_topic"]
