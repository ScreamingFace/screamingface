"""Wires the `JobRunner` port to its concrete adapter for the deployment at hand.

# INVARIANT: this is the one place a concrete `JobRunner` implementation gets chosen and
# constructed — everything else in the app depends only on the port, never on a concrete
# adapter directly.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from screamingface_engine.adapters.jetstream import JetStreamPublisher
from screamingface_engine.adapters.queue_runner import ControlClient, QueueJobRunner
from screamingface_engine.config import Settings
from screamingface_engine.runner_queue import RunQueue
from url4.streaming.interfaces import JobRunner


def build_job_runner(
    settings: Settings,
    *,
    extra_models: Callable[[], Sequence[str]] | None = None,
) -> JobRunner | None:
    """Selects the `JobRunner` adapter for `settings.runner`.

    Returns `None` when no runner is configured (e.g. local mode, where nothing schedules
    runs) rather than raising — callers decide whether the absence of a runner is fatal.

    ``extra_models`` (OME-880) is the dynamically-admitted-model overlay, read at schedule
    time and written onto each run as ``URL4_CLOUD_EXTRA_MODELS``.
    """
    if settings.runner == "queue":
        # The OME-1086 substrate (OME-1090): one durable queue + a fixed worker pool. The
        # queue, the publisher, and the control client all connect lazily, so building the
        # runner never dials the broker. The k8s Job adapter was retired at the cutover
        # (OME-1092); this is the only deployed backend.
        return QueueJobRunner(
            queue=RunQueue(
                settings.nats_url,
                # The stream and subject-prefix follow the CONFIGURED settings (review
                # follow-up P2-2): the App publishes to the same stream and buckets the
                # worker pulls, so a renamed queue must not split the two sides (a stream
                # name mismatch makes every admission fail loudly; a prefix mismatch
                # publishes where no worker listens). `run_worker` passes the same
                # settings, so the sides agree for any Settings.
                stream=settings.run_queue_stream,
                subject_prefix=settings.run_queue_subject_prefix,
                ack_wait_s=settings.run_queue_ack_wait_s,
                max_deliver=settings.run_queue_max_deliver,
                max_ack_pending=settings.run_queue_max_ack_pending,
                duplicate_window_s=settings.run_queue_duplicate_window_s,
                max_age_s=settings.run_queue_max_age_s,
                bucket_count=settings.run_queue_bucket_count,
                # INVARIANT: the same rule as `stream` above, for a property the broker
                # itself enforces. `ensure_stream` refuses a declaration whose properties
                # diverge from an existing stream, and the App usually declares FIRST —
                # it accepts a run before any worker pulls it. An App left on the code
                # default while the worker reads configuration is therefore a startup
                # failure for the worker, not a cosmetic mismatch.
                replicas=settings.run_queue_replicas,
            ),
            # The publisher's sweep must exclude the CONFIGURED queue stream (review
            # follow-up P2-3) — the same rule `run_worker` already applied.
            publisher=JetStreamPublisher(
                settings.nats_url, run_queue_stream=settings.run_queue_stream
            ),
            control=ControlClient(settings.nats_url),
            clock=lambda: datetime.now(UTC),
            capability_lifetime_s=settings.capability_lifetime_s,
            io_concurrency=settings.runner_io_concurrency,
            extra_models=extra_models,
            depth_ceiling=settings.run_queue_depth_ceiling,
            caller_inflight_cap=settings.run_queue_caller_inflight_cap,
        )
    return None
