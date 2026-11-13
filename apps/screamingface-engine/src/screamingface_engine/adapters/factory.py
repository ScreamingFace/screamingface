"""Wires the `JobRunner` port to its concrete adapter for the deployment at hand.

# INVARIANT: this is the one place a concrete `JobRunner` implementation gets chosen and
# constructed — everything else in the app depends only on the port, never on a concrete
# adapter directly.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from screamingface_engine import job_env
from screamingface_engine.adapters.candidate_outcomes_jetstream import (
    CandidateOutcomesStreamConfig,
    JetStreamCandidateOutcomeStream,
)
from screamingface_engine.adapters.jetstream import EventsStreamConfig, JetStreamPublisher
from screamingface_engine.adapters.queue_runner import ControlClient, QueueJobRunner
from screamingface_engine.adapters.topic_claims_jetstream import (
    JetStreamTopicClaims,
    TopicClaimsBucketConfig,
)
from screamingface_engine.artifacts.run_results import RunResultStore
from screamingface_engine.artifacts.wiring import (
    RunResultStoreNotConfigured,
    run_results_from_values,
)
from screamingface_engine.candidate_outcomes import CandidateOutcomeStream
from screamingface_engine.config import Settings
from screamingface_engine.runner_queue import RunQueue
from url4.streaming.interfaces import JobRunner


def build_job_runner(
    settings: Settings,
    *,
    extra_models: Callable[[], Sequence[str]] | None = None,
    world_digest: str | None = None,
    outcomes: CandidateOutcomeStream | None = None,
) -> JobRunner | None:
    """Selects the `JobRunner` adapter for `settings.runner`.

    Returns `None` when no runner is configured (e.g. local mode, where nothing schedules
    runs) rather than raising — callers decide whether the absence of a runner is fatal.

    ``extra_models`` (OME-880) is the dynamically-admitted-model overlay, read at schedule
    time and written onto each run as ``URL4_CLOUD_EXTRA_MODELS``.

    ``world_digest`` (OME-1770 review) is the App's one read of its world config, stamped on each
    run as ``URL4_CLOUD_WORLD_DIGEST``.

    ``outcomes`` (OME-1785) receives the queued-cancel tombstone's Candidate outcome.
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
            publisher=JetStreamPublisher(settings.nats_url, events=events_stream_config(settings)),
            control=ControlClient(settings.nats_url),
            clock=lambda: datetime.now(UTC),
            capability_lifetime_s=settings.capability_lifetime_s,
            io_concurrency=settings.runner_io_concurrency,
            extra_models=extra_models,
            world_digest=world_digest,
            depth_ceiling=settings.run_queue_depth_ceiling,
            caller_inflight_cap=settings.run_queue_caller_inflight_cap,
            outcomes=outcomes,
        )
    return None


def events_stream_config(settings: Settings) -> EventsStreamConfig:
    """The events stream as the chart configures it (`events.*` → `URL4_CLOUD_EVENTS_*`)."""
    return EventsStreamConfig(
        max_bytes=settings.events_max_bytes,
        max_msgs_per_subject=settings.events_max_msgs_per_subject,
        max_age_s=settings.events_max_age_s,
        replicas=settings.events_replicas,
    )


def build_topic_claims(settings: Settings) -> JetStreamTopicClaims:
    """The runner pool's `url4-claims` bucket (E5 P2 spec D7): the event stream's retention,
    replicas and storage, so a claim lasts as long as the topic's terminal frame."""
    return JetStreamTopicClaims(
        settings.nats_url, config=TopicClaimsBucketConfig.for_events(events_stream_config(settings))
    )


def build_candidate_outcome_stream(settings: Settings) -> JetStreamCandidateOutcomeStream:
    """The outcome stream as the chart configures it (`candidateOutcomes.*`), for the App and
    the runner pool alike (spec R11)."""
    return JetStreamCandidateOutcomeStream(
        settings.nats_url,
        config=CandidateOutcomesStreamConfig(
            max_age_s=settings.candidate_outcomes_max_age_s,
            max_bytes=settings.candidate_outcomes_max_bytes,
        ),
    )


# Local mode's folder, beside the Engine database (`runs/wiring.py`, `LOCAL_DATA_DIR`).
_LOCAL_RUN_RESULTS = Path(".screamingface-engine") / "run-results"


def run_results_values(settings: Settings, *, home: Path | None = None) -> dict[str, str]:
    """The run-results store's settings, env-named, as both halves read them.

    Local mode with no setting keeps a folder beside its database, in the Engine's data dir; its
    in-process runs read these values from their env, so they write where the App reads.
    """
    values = {
        job_env.RUN_RESULTS_STORE: settings.run_results_store or "",
        job_env.RUN_RESULTS_DIR: settings.run_results_dir,
        job_env.RUN_RESULTS_S3_ENDPOINT_URL: settings.run_results_s3_endpoint_url,
        job_env.RUN_RESULTS_S3_BUCKET: settings.run_results_s3_bucket,
        job_env.RUN_RESULTS_S3_REGION: settings.run_results_s3_region,
        job_env.RUN_RESULTS_S3_ACCESS_KEY: settings.run_results_s3_access_key,
        job_env.RUN_RESULTS_S3_SECRET_KEY: settings.run_results_s3_secret_key,
        job_env.RUN_RESULT_WRITE_BUDGET_S: str(settings.run_result_write_budget_s),
    }
    if settings.run_results_store is None and settings.runner != "queue":
        base = home if home is not None else Path.home()
        values[job_env.RUN_RESULTS_STORE] = "filesystem"
        values[job_env.RUN_RESULTS_DIR] = settings.run_results_dir or str(base / _LOCAL_RUN_RESULTS)
    return values


def build_run_result_store(
    settings: Settings, *, home: Path | None = None
) -> RunResultStore | None:
    """The App's run-results store (E5 P2 spec D9a), or None on a deployment with none.

    WHY through `run_results_from_values`: the runner pool resolves its store with the same
    function from the same `job_env` names, so the two halves cannot use different buckets.

    INVARIANT: a deployed App (`runner="queue"`) refuses a folder, since its workers write the
    results and cannot see its disk.
    """
    if settings.runner == "queue" and settings.run_results_store == "filesystem":
        raise ValueError(
            f"runner='queue' writes results from worker pods that cannot see this App's disk: "
            f"set {job_env.RUN_RESULTS_STORE}=s3 and the {job_env.RUN_RESULTS_S3_BUCKET} settings"
        )
    try:
        return run_results_from_values(run_results_values(settings, home=home))
    except RunResultStoreNotConfigured:
        return None
