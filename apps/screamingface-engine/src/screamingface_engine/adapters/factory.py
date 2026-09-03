"""Wires the `JobRunner` port to its concrete adapter for the deployment at hand.

# INVARIANT: this is the one place a concrete `JobRunner` implementation gets chosen and
# constructed — everything else in the app depends only on the port, never on `K8sJobRunner`
# (or any future adapter) directly.
"""

import functools
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, cast

from screamingface_engine.adapters.jetstream import JetStreamPublisher
from screamingface_engine.adapters.k8s import (
    BatchV1JobsClient,
    CoreV1QuotaClient,
    K8sJobRunner,
)
from screamingface_engine.adapters.queue_runner import ControlClient, QueueJobRunner
from screamingface_engine.config import Settings
from screamingface_engine.runner_queue import RunQueue
from url4.streaming.interfaces import JobRunner

# WHY a timeout at all: `K8sJobRunner` offloads its blocking calls to a worker thread, so a
# hung API server no longer freezes the event loop — but without a deadline those threads are
# never reclaimed, and each stuck request holds a `to_thread` worker until the process dies. The
# call is one round trip to an in-cluster API server; seconds, not minutes, is the honest bound.
_K8S_REQUEST_TIMEOUT_S = 10


@functools.cache
def _in_cluster_api_client() -> Any:  # pragma: no cover - live cluster (INFRA)
    """The process's single kubernetes ApiClient — one config load, one connection pool.

    Built once and shared: two `ApiClient`s would mean two TLS pools and two lazily-spawned
    thread pools held for the life of the process, for one API server.
    """
    from kubernetes.client import ApiClient, Configuration
    from kubernetes.config import load_incluster_config

    configuration = Configuration()
    load_incluster_config(client_configuration=configuration)
    # WHY no retries: the generated client retries at the urllib3 layer, which multiplies the
    # per-call `_request_timeout` by the retry count and makes the effective deadline unknowable.
    # `schedule` is not idempotent (a retried create can 409 against its own first attempt), so
    # retrying belongs to the caller, not the transport.
    # `Configuration.retries` is annotated `None` in the shipped stubs but is a real settable
    # attribute the REST client reads; setattr keeps the intent without a type: ignore on a line
    # whose meaning is not obvious.
    setattr(configuration, "retries", 0)  # noqa: B010
    return ApiClient(configuration)


def _in_cluster_batch_client() -> BatchV1JobsClient:  # pragma: no cover - live cluster (INFRA)
    from kubernetes.client import BatchV1Api

    return cast(BatchV1JobsClient, BatchV1Api(_in_cluster_api_client()))


def _in_cluster_core_client() -> CoreV1QuotaClient:  # pragma: no cover - live cluster (INFRA)
    """The quota/limitrange read surface, sharing the process's single cached ApiClient."""
    from kubernetes.client import CoreV1Api

    return cast(CoreV1QuotaClient, CoreV1Api(_in_cluster_api_client()))


def build_job_runner(
    settings: Settings,
    *,
    k8s_client_factory: Callable[[], BatchV1JobsClient] = _in_cluster_batch_client,
    core_client_factory: Callable[[], CoreV1QuotaClient] = _in_cluster_core_client,
    extra_models: Callable[[], Sequence[str]] | None = None,
) -> JobRunner | None:
    """Selects the `JobRunner` adapter for `settings.runner`.

    Returns `None` when no runner is configured (e.g. local mode, where nothing schedules
    Jobs) rather than raising — callers decide whether the absence of a runner is fatal.

    ``extra_models`` (OME-880) is the dynamically-admitted-model overlay, read at schedule
    time and written onto each Job as ``URL4_CLOUD_EXTRA_MODELS``.
    """
    if settings.runner == "k8s":
        # WHY: `command` is left to K8sJobRunner's default — the image entrypoint has one
        # source of truth, and it is next to the Job spec that uses it.
        return K8sJobRunner(
            k8s_client_factory(),
            core_client=core_client_factory(),
            request_timeout_s=_K8S_REQUEST_TIMEOUT_S,
            image=settings.runner_image,
            namespace=settings.namespace,
            env_configmap=settings.runner_env_configmap,
            # WHY built as a filtered tuple rather than two conditionals: a Job may need both
            # credentials (Tavily to search, object storage to park its result), and `envFrom`
            # takes a list — so the two are independent, not alternatives.
            env_secrets=tuple(
                name
                for name in (settings.tavily_secret_name, settings.artifact_s3_secret_name)
                if name
            ),
            resources=settings.runner_resources,
            node_selector=settings.runner_node_selector,
            tolerations=settings.runner_tolerations,
            job_ttl_s=settings.effective_job_ttl_s,
            extra_models=extra_models,
            io_concurrency=settings.runner_io_concurrency,
        )
    if settings.runner == "queue":
        # The OME-1086 substrate (OME-1090): one durable queue + a fixed worker pool. The
        # queue, the publisher, and the control client all connect lazily, so building the
        # runner never dials the broker. The cutover to this backend is OME-1092; the
        # adapter must exist and be selectable now.
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
                ack_wait_s=settings.run_queue_ack_wait_s,
                max_deliver=settings.run_queue_max_deliver,
                max_ack_pending=settings.run_queue_max_ack_pending,
                duplicate_window_s=settings.run_queue_duplicate_window_s,
                max_age_s=settings.run_queue_max_age_s,
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
        )
    return None
