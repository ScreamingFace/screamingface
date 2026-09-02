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

# The publish-time stamp on every queued run (OME-1088): the wall-clock moment the
# submission was accepted onto the queue. JetStream's own message metadata records only
# the DELIVERY timestamp — the moment a worker pulled it — so "how long has this run
# waited?" (the deadline-expiry drop at claim time) is unanswerable from the metadata.
# The publisher stamps this header; the worker reads it back. A message without the
# header (published before the stamp existed) falls back to the delivery timestamp —
# the pre-stamp semantics, never worse.
ENQUEUED_AT_HEADER = "Url4-Enqueued-At"

# The run-control channel (OME-1090): a core NATS request/reply subject per run, on which
# the App asks "is this run running here?" and the owning worker answers by SIGTERMing its
# child. Every worker subscribes to the wildcard; only the owner replies.
CONTROL_SUBJECT_PREFIX = "url4.runctl"


def control_subject_for(topic: str) -> str:
    return f"{CONTROL_SUBJECT_PREFIX}.{topic}"


def subject_for(topic: str) -> str:
    return f"{PREFIX}.{topic}"


def stream_for(topic: str) -> str:
    return f"{PREFIX}_{topic}"


def owns_stream(stream_name: str, *, run_queue_stream: str = RUN_QUEUE_STREAM) -> bool:
    """Whether a stream on the broker is one of ours.

    INVARIANT: the NATS store may be shared with other workloads. Reclamation enumerates every
    stream the broker holds, so this is what keeps a sweep from deleting a stranger's data.

    INVARIANT (OME-1088): the run queue is OURS but must never be swept — it is the durable
    substrate an accepted run may not be lost from, and `_sweep_orphans` deletes anything this
    accepts. It is named outside the per-run prefix (`url4-runq` does not start with
    `url4-cloud_`), and it is ALSO excluded explicitly here, so a future rename of either side
    cannot silently re-arm the sweep against it.

    The exclusion follows the CONFIGURED queue stream, not the default constant: the name is
    a Settings field (`run_queue_stream`), and an operator who renames the queue must not have
    the sweep re-armed against the renamed stream by a stale constant. Composition roots pass
    their configured name; the default keeps tests and the default deployment on the constant.
    """
    if stream_name == run_queue_stream:
        return False
    return stream_name.startswith(f"{PREFIX}_")


def topic_of(stream_name: str) -> str:
    """Inverse of :func:`stream_for`. Callers must check :func:`owns_stream` first."""
    return stream_name.removeprefix(f"{PREFIX}_")


__all__ = [
    "ENQUEUED_AT_HEADER",

    "CONTROL_SUBJECT_PREFIX",
    "RUN_QUEUE_STREAM",
    "RUN_QUEUE_SUBJECT",
    "RUN_QUEUE_SUBJECT_PREFIX",
    "control_subject_for",
    "owns_stream",
    "stream_for",
    "subject_for",
    "topic_of",
]
