"""NATS subject and JetStream stream naming, built from one prefix so subject
strings aren't hand-formatted at each call site.

A SHARED LEAF: both `screamingface-engine serve` (which subscribes) and
`screamingface-engine run` (which publishes) import this, and the layering gate
names it as one of the three modules allowed to sit on that line. It used to be
duplicated across two distributions with a contract test pinning the copies
together; one module means there is nothing left to drift.
"""

from __future__ import annotations

PREFIX = "url4-cloud"

# The durable run queue (OME-1088): ONE stream for every run, unlike the per-run event streams,
# so it is named OUTSIDE the per-run `url4-cloud_` prefix — see `owns_stream` for why that is
# load-bearing. Per-caller subjects (`url4-runq.<bucket>`) are the fairness seam; they land in
# OME-1091, so this unit uses the single `url4-runq.work` subject.
RUN_QUEUE_STREAM = "url4-runq"
RUN_QUEUE_SUBJECT_PREFIX = "url4-runq"
RUN_QUEUE_SUBJECT = f"{RUN_QUEUE_SUBJECT_PREFIX}.work"


def subject_for(topic: str) -> str:
    return f"{PREFIX}.{topic}"


def stream_for(topic: str) -> str:
    return f"{PREFIX}_{topic}"


def owns_stream(stream_name: str) -> bool:
    """Whether a stream on the broker is one of ours.

    INVARIANT: the NATS store may be shared with other workloads. Reclamation enumerates every
    stream the broker holds, so this is what keeps a sweep from deleting a stranger's data.

    INVARIANT (OME-1088): the run queue is OURS but must never be swept — it is the durable
    substrate an accepted run may not be lost from, and `_sweep_orphans` deletes anything this
    accepts. It is named outside the per-run prefix (`url4-runq` does not start with
    `url4-cloud_`), and it is ALSO excluded explicitly here, so a future rename of either side
    cannot silently re-arm the sweep against it.
    """
    if stream_name == RUN_QUEUE_STREAM:
        return False
    return stream_name.startswith(f"{PREFIX}_")


def topic_of(stream_name: str) -> str:
    """Inverse of :func:`stream_for`. Callers must check :func:`owns_stream` first."""
    return stream_name.removeprefix(f"{PREFIX}_")


__all__ = [
    "RUN_QUEUE_STREAM",
    "RUN_QUEUE_SUBJECT",
    "RUN_QUEUE_SUBJECT_PREFIX",
    "owns_stream",
    "stream_for",
    "subject_for",
    "topic_of",
]
