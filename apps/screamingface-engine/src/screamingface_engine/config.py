"""Typed settings for the screamingface-engine App, loaded from `URL4_CLOUD_*`
environment variables."""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from screamingface_engine import job_env, runner_queue, subjects

# WHY a margin at all: the App decides a token is expired from its own clock, while the k8s TTL
# controller deletes the Job from the control plane's. Without slack a skewed pair could reclaim
# the guard a few seconds before the token is actually refused. 60s is far beyond realistic
# in-cluster skew and still ~500x cheaper than the old job_deadline_s-based floor.
_TTL_SKEW_MARGIN_S = 60

RunnerBackend = Literal["none", "k8s"]
ArtifactStoreBackend = Literal["filesystem", "s3"]
"""Which ``JobRunner`` substrate the deployed App schedules runs on (spec §9).

``k8s`` is prod (namespace-scoped batch/v1 Jobs) and ``none`` a stream-only App that mints tokens
and bridges NATS but schedules nothing.
"""

# WHY a named module constant (not a bare literal) for the insecure default: the prod guard in
# app.py (_require_prod_secret) compares against this same sentinel so the two never drift. If the
# default changes and the guard isn't updated, a prod boot would silently proceed on the weak
# secret.
INSECURE_DEFAULT_JWT_SECRET = "dev-insecure-change-me"

# WHY a named module constant (not a bare literal) for the local gateway address: it is the
# DEFAULT of `local_aigateway_base_url` below, and naming it lets a test pin the loopback value
# without restating the literal — the same shape as INSECURE_DEFAULT_JWT_SECRET above.
LOCAL_AIGATEWAY_BASE_URL = "http://127.0.0.1:9105"


class Settings(BaseSettings):
    """Environment-backed configuration for the App: auth, NATS, job-runner backend selection,
    and model-catalog cache tuning."""

    model_config = SettingsConfigDict(env_prefix="URL4_CLOUD_")

    # WHY: HS256 signing secret for the JWT topic-capability token (spec §4). Never logged.
    #
    # The prod guard in app.py rejects the insecure DEFAULT, but sentinel equality alone would
    # pass any short string — a 4-character production secret is brute-forceable and satisfied it.
    # RFC 7518 §3.2 requires an HMAC key at least as long as the hash output; below that, PyJWT
    # itself warns. Enforced here so a weak secret fails at startup rather than at the first
    # forged token.
    jwt_secret: str = INSECURE_DEFAULT_JWT_SECRET
    # WHY the shared constant and not a literal: `job_env` states the fallback beside the variable
    # name so serve and run cannot be pointed at different brokers by a one-sided edit.
    nats_url: str = job_env.DEFAULT_NATS_URL
    # FEATURE: deliver large results in full instead of cutting them off at 1 MiB (OME-892).
    # Same env var (URL4_CLOUD_ARTIFACTS_DIR) the Runner's spill side reads — one name, so the
    # writer and the `GET /artifacts/{id}` server cannot be pointed at different directories.
    artifacts_dir: str = job_env.DEFAULT_ARTIFACTS_DIR
    # FEATURE: over-cap results survive the Runner Job on a multi-pod deployment (OME-929).
    #
    # INVARIANT: every field below reads the env var `job_env` declares for it, by construction —
    # `env_prefix` + the field name, uppercased. `test_artifact_storage_selection.py` pins that
    # equality, because a one-sided rename would point the Runner's writer and the App's reader at
    # different buckets, which is OME-929 again in a shape the 404 would not hint at.
    #
    # WHY a choice and not derived from `runner`: the Runner cannot see its own cluster topology,
    # so the chart states this for both halves. The App CAN see it, and `create_app` refuses
    # `runner="k8s"` paired with filesystem storage — that pairing IS the bug, and it used to be
    # the default.
    artifact_store: ArtifactStoreBackend = "filesystem"
    artifact_s3_endpoint_url: str = ""
    artifact_s3_bucket: str = ""
    artifact_s3_region: str = job_env.DEFAULT_ARTIFACT_S3_REGION
    artifact_s3_access_key: str = ""
    # AIDEV-NOTE: credential material. Never logged, never rendered into a ConfigMap — it
    # reaches the pod from a Secret, the same way `TAVILY_API_KEY` does.
    artifact_s3_secret_key: str = ""
    # WHY 48h: long enough for any client that survived its run to come back for the parcel
    # (a run itself is bounded by job_deadline_s = 16h), short enough that crashed runs
    # cannot pool disk for more than two days. Swept at App startup AND periodically.
    artifact_ttl_s: int = 172_800
    # WHY periodic and not startup-only: a hosted Engine pod can stay up for weeks, and a
    # startup-only sweep would let abandoned parcels pool until the next redeploy (owner
    # decision on OME-892). Hourly is far finer than the 48h TTL it enforces, and one
    # directory scan an hour costs nothing.
    artifact_sweep_interval_s: float = 3600.0
    # FEATURE: tie a run's lifetime to its audience (OME-890).
    #
    # WHY 120s: a run whose last WebSocket subscriber disconnects gets this long to get one back
    # before the App stops it. Uvicorn needs up to ws_ping_interval + ws_ping_timeout (~40s on
    # its defaults) to notice a partitioned peer, so anything much below a minute reaps mostly on
    # clean closes while starting to risk live runs on slow reconnects. 0 disables the reaper.
    #
    # INVARIANT: this bounds SPEND, not correctness — job_deadline_s (16h) remains the backstop.
    # Raising it costs money per orphaned run; lowering it risks stopping a live one.
    orphan_grace_s: float = Field(default=120.0, ge=0.0)
    # INVARIANT: stateless iat window (seconds) — now a CLOCK-SKEW tolerance only: a mint
    # from more than one window in the future is rejected. It never bounds lifetime.
    iat_window_s: int = 60
    # INVARIANT: capability-token lifetime (seconds) — `exp = iat + this` at mint (spec §6
    # S1, OME-1016). WHY 58_800: the 16 h Job deadline (job_deadline_s) plus 1 h slack, so a
    # Run's owner can always re-attach, stop, or redeem for the Run's whole life (D1).
    capability_lifetime_s: int = 58_800
    # WHY: sync-hold cap; a run outliving it degrades to 202 async (spec §5).
    sync_max_wait_s: float = 30.0
    # WHY: idle interval between WS HeartbeatEvents for liveness (spec §6).
    ws_heartbeat_s: float = 15.0
    # INVARIANT: k8s Job activeDeadlineSeconds ceiling = 16h (spec §3).
    job_deadline_s: int = 57600
    # WHY: the run substrate is deployment-shaped, not code-shaped — the helm chart sets `k8s`.
    # Default `none` keeps a bare `Settings()` from reaching for a cluster.
    runner: RunnerBackend = "none"
    # INVARIANT: the App's RBAC Role is namespace-scoped, so Jobs are only ever created here (§9).
    namespace: str = "default"
    # WHY this is still a setting when the Job now runs the App's OWN image: a process cannot
    # reliably learn the image reference it was started from (the pod spec holds it, reading it
    # back needs RBAC on pods and the Downward API does not expose it), so the deployment states
    # it. The chart renders the same `image:` it gives the Deployment, which is what keeps the
    # two in lockstep. It is a distinct field rather than a hardcoded constant precisely so a
    # deployment CAN pin the Job to a different tag during a staged rollout.
    runner_image: str = "screamingface-engine:latest"
    # WHY: the model catalog forwards the CALLER's credential to aigateway directly, and this is
    # its ONLY consumer (`catalog/__init__.py:build_catalog_service`) — despite sitting among the
    # runner-config fields around it, it is no longer forwarded into a Runner Job's env (that now
    # travels via `runner_env_configmap`/`K8sJobRunner._env_from`, below). It used to be: the
    # Runner's own fallback is loopback (127.0.0.1:9105), which inside a Job Pod resolves to
    # itself, not the aigateway Service — the trap `runner_env_configmap` now sidesteps by having
    # Helm value the variable directly instead of copying it through this field. `None` disables
    # the model-catalog endpoint (503 "not configured").
    aigateway_base_url: str | None = None
    # WHY: deploy-time Runner env travels as k8s objects the Job references with `envFrom`, so the
    # App neither names nor reads those variables — Helm owns name AND value. These two settings
    # are the only thing it needs: what to reference.
    runner_env_configmap: str | None = None
    # FEATURE (OME-908): the per-run downstream in-flight budget written onto every Runner Job
    # as `URL4_CLOUD_IO_CONCURRENCY` and enforced by URL4's `BoundedIOLayer`.
    #
    # WHY a STATIC bound in deployed mode: each run is its own Job Pod, so no process sees
    # enough of the fleet to schedule it dynamically — the fair-share gate exists only in local
    # mode (`local_io_capacity`). The static value shapes each run's ARRIVALS at the gateway's
    # per-provider FIFO, which is what keeps one benchmark-sized run from monopolizing it.
    #
    # WHY 4 and not the URL4 default of 32: with the gateway admitting 4 per provider
    # (`AIGW_PROVIDER_MAX_CONCURRENCY`), a 32-wide run keeps the queue continuously full for
    # hours, so a second run's calls wait behind a wall of the first run's requests. 4 matches
    # the provider ceiling exactly — a run can saturate its provider but never pile a backlog
    # behind it, so a second run's calls interleave as soon as the first run's in-flight calls
    # complete. 32 restores the previous behavior exactly — that is the revert switch.
    # INVARIANT (pinned by `test_job_env_contract`): the App writes it on EVERY Job, so a stale
    # copy left in the Helm ConfigMap can never reach a Job through `envFrom`.
    runner_io_concurrency: int = Field(default=4, ge=1)
    # --- Tavily web tools (spec 2026-07-23). The connector declares web_search/web_fetch ONLY
    # when the Runner sees TAVILY_API_KEY; unset here => deny-by-default (dec:W5).
    #
    # WHY a reference (not a value): a ``batch/v1`` Job object is NOT a secret — readable with
    # ``get jobs`` RBAC (far looser than ``get secrets``) and surfaced in ``kubectl describe``/
    # ``-o yaml`` and the create-call audit log — so the key travels as a Secret *reference*, via
    # `envFrom.secretRef`, never a literal copied into the manifest (see
    # ``K8sJobRunner._env_from``). The name of the Secret the Runner Job's env references:
    tavily_secret_name: str | None = None
    # The Secret carrying URL4_CLOUD_ARTIFACT_S3_SECRET_KEY into each Runner Job (OME-929).
    # A reference for the same reason `tavily_secret_name` is one: a `batch/v1` Job object is not
    # a secret, so the credential travels via `envFrom.secretRef` and never as a literal in the
    # manifest. The App reads the same Secret through its own Deployment `envFrom`.
    artifact_s3_secret_name: str | None = None
    # WHY: the Runner drives the url4 DAG engine and buffers model responses — it is the
    # workload that actually consumes CPU/memory here. Without requests it schedules into the
    # BestEffort QoS class (placed blind, evicted first, free to OOM its node), so the chart
    # supplies the numbers. Shape is the k8s `resources` block verbatim, e.g.
    # {"requests": {"cpu": "200m", "memory": "256Mi"}, "limits": {"memory": "1Gi"}}.
    runner_resources: dict[str, dict[str, str]] | None = None
    # INVARIANT: Runner Jobs use the same operator-owned placement as the Engine Deployment.
    # The chart supplies Kubernetes-native structures, so this code stays environment-neutral.
    runner_node_selector: dict[str, str] = Field(default_factory=dict)
    runner_tolerations: list[dict[str, object]] = Field(default_factory=list)
    # --- model catalog (OME-625). The catalog endpoint forwards the CALLER's
    # credential, so there is deliberately NO credential setting here:
    # screamingface-engine holds no aigateway secret. `aigateway_base_url` above is
    # the only precondition for the feature.
    #
    # WHY a TTL at all: the catalog is a provider registry — it changes on deploy, not on traffic.
    models_cache_ttl_s: float = 300.0
    # WHY a ceiling on stale service: an outage should not empty every client's model list, but an
    # indefinitely stale catalog would advertise models that may since have been retired.
    models_cache_stale_max_s: float = 3600.0
    # WHY: single-flight collapses CONCURRENT misses; this bounds SEQUENTIAL retries so a warm
    # caller polling through an aigateway outage does not hit upstream on every request.
    models_cache_error_backoff_s: float = 30.0
    # INVARIANT: cache keys derive from credentials screamingface-engine does not
    # verify, so the entry count must be bounded rather than left to the caller
    # population (spec §7).
    models_cache_max_entries: int = 256
    # INVARIANT: distinct credentials bypass single-flight entirely, so this bulkhead is the only
    # thing bounding concurrent upstream catalog fetches. The apigw is the rate limiter in front;
    # this is the in-app backstop.
    models_upstream_concurrency: int = 8

    # --- local mode (`screamingface-engine serve --local`). Ignored by every other
    # backend: these bound resources that only a single-process deployment has to
    # bound for itself.
    #
    # INVARIANT: local mode is selected by ARGV, never by these settings — they tune it, they do
    # not enable it. See the mode invariant in `cli.py`.
    #
    # WHY a concurrency cap at all: k8s spreads Jobs across a cluster and queues the surplus, but
    # every local run shares one event loop and one process, so admitting without bound degrades
    # the runs already in flight instead of delaying new ones.
    #
    # WHY 32 and not a tighter number: the Client opens one run per Candidate and keeps up to 8 in
    # flight (`_MAX_CANDIDATES_IN_FLIGHT`), so anything at or below 8 leaves no headroom — one
    # ordinary Evaluation fills the runner exactly and the next schedule 503s. That is worse than
    # it sounds, because a WebSocket disconnect does not stop a run: an abandoned one holds its
    # slot until `job_deadline_s` (16h). 32 keeps roughly four Evaluations, or one plus slack for
    # orphans. INVARIANT (pinned by `tests/unit/test_local_capacity_contract.py`): this stays
    # strictly above the Client fan-out, and equal to `DEFAULT_MAX_CONCURRENT_RUNS` so capacity
    # does not depend on which path built the runner.
    local_max_concurrent_runs: int = 32
    # WHY: the in-memory stream has no retention policy of its own (JetStream does), so a
    # long-lived dev server would accumulate every frame of every run it ever served.
    local_stream_max_frames: int = 10_000
    # WHY bounded run history: `status()` answers from finished tasks, so they are retained past
    # completion — this caps how many, the way `ttlSecondsAfterFinished` caps retained Jobs.
    local_max_run_history: int = 1000
    # FEATURE (OME-908): the shared downstream capacity every local run fair-shares through
    # `runner.fair_share.FairShareGate` — the dynamic, work-conserving counterpart of the
    # deployed mode's static `runner_io_concurrency`.
    #
    # WHY dynamic here and static in deployed mode: local mode's runs share one event loop and
    # one process, so ONE gate can watch every active run — a solo run gets the whole capacity,
    # two runs split it near-evenly, and a finished run's share reverts instantly. Deployed Jobs
    # are separate processes and get the static per-run bound instead.
    #
    # WHY 32: equal to URL4's `DEFAULT_RUN_CONCURRENCY`, so a solo local run's ceiling — and
    # therefore its speed — is unchanged from before this feature existed. Lower it to shape
    # local arrivals the same way `runner_io_concurrency` shapes a Job's.
    local_io_capacity: int = Field(default=32, ge=1)
    # WHY a SECOND gateway address rather than defaulting `aigateway_base_url` itself: that field
    # is read by the model catalog too, where `None` is a meaningful state (the endpoint answers
    # 503 "not configured"). Defaulting it to loopback would silently switch the local catalog on
    # and point it at a gateway that may not be running. This field says the narrower thing —
    # where local-mode CONNECTION operations go when nothing else was stated.
    #
    # INVARIANT: `aigateway_base_url` still wins. `create_local_app` substitutes this only when
    # that field is unset, so one explicit `URL4_CLOUD_AIGATEWAY_BASE_URL` continues to point the
    # whole App — catalog and connections alike — at one gateway.
    #
    # WHY loopback, like `LOCAL_HOST`: local mode is a single-process developer deployment, and
    # the gateway it manages credentials through is the one running beside it.
    local_aigateway_base_url: str = LOCAL_AIGATEWAY_BASE_URL

    # INVARIANT: a finished Job's NAME is the stateless single-use replay guard, so reclaiming
    # it re-opens replay for that topic — but only for as long as the token is still usable.
    # See `effective_job_ttl_s` and `_reject_replayable_job_ttl`. None => derive the floor.
    job_ttl_s: int | None = None

    # --- durable run queue (OME-1088) -------------------------------------------------------
    # WHY a queue at all: OME-1086 replaces one-Job-per-run scheduling with a fixed worker pool
    # pulling from a durable work queue. THIS unit adds the queue substrate only — no worker,
    # no cutover — so these settings are the substrate's knobs, not the worker's.
    #
    # INVARIANT: the stream name must NOT begin with `url4-cloud_` — `_sweep_orphans` deletes
    # any stream `owns_stream()` accepts, and the queue is the one stream an accepted run may
    # not be lost from. `subjects.owns_stream` excludes it explicitly; the default here is the
    # same constant, so the two cannot drift. The invariant is ENFORCED below by
    # `_reject_sweepable_run_queue_stream` (review follow-up V-8): a comment could not stop an
    # operator or a composition root from naming the queue into the sweepable prefix, and the
    # exclusion in `owns_stream` only holds where the CONFIGURED name actually reaches it.
    run_queue_stream: str = subjects.RUN_QUEUE_STREAM
    run_queue_subject_prefix: str = subjects.RUN_QUEUE_SUBJECT_PREFIX
    # WHY a window at all: a retried submission (a client retrying a timed-out request) must
    # not become a second run. The broker deduplicates `Nats-Msg-Id` within this window; 120s
    # is far beyond any retry interval and far below the queue's own lifetime.
    run_queue_duplicate_window_s: float = runner_queue.DEFAULT_DUPLICATE_WINDOW_S
    # WHY a backstop and not a correctness mechanism: `max_age` is the storage backstop for a
    # run nobody ever pulled (a worker outage). It must be GENEROUS — an accepted run may not
    # be lost, and the queue is the only record of it.
    run_queue_max_age_s: float = runner_queue.DEFAULT_QUEUE_MAX_AGE_S
    run_queue_ack_wait_s: float = runner_queue.DEFAULT_ACK_WAIT_S
    run_queue_max_deliver: int = runner_queue.DEFAULT_MAX_DELIVER
    # WHY replicas × worker_slots: `max_ack_pending` bounds how many unacked messages one
    # worker may hold; with `QUEUE_REPLICAS` replicas of the stream and `worker_slots` runs per
    # worker, that is the most a single worker can legitimately have in flight.
    run_queue_worker_slots: int = runner_queue.DEFAULT_WORKER_SLOTS
    # WHY fleet-sized: `max_ack_pending` is a WHOLE-CONSUMER bound — the total unacked
    # messages the queue's durable consumer may hand out across EVERY worker in the fleet,
    # not a per-worker limit. Size it to the deployment's true fleet concurrency
    # (worker pods × slots); note the value binds at consumer CREATION, so changing it on a
    # running queue means deleting and recreating the consumer.
    run_queue_max_ack_pending: int = runner_queue.DEFAULT_MAX_ACK_PENDING
    # WHY a ceiling at all: the serving half must stop accepting when the queue is deeper than
    # the fleet can drain in a reasonable time, rather than piling up unbounded work. THIS unit
    # only declares the setting; the admission decision lands with the cutover (OME-1086).
    run_queue_depth_ceiling: int = runner_queue.DEFAULT_DEPTH_CEILING

    @property
    def effective_job_ttl_s(self) -> int:
        """Seconds a finished Runner Job is retained before k8s reclaims it.

        ``ttlSecondsAfterFinished`` counts from the moment the Job FINISHES, and the Job object
        exists for the whole run already — so the only gap the guard must cover is the interval
        after completion in which the starting token could still be presented again. A token
        carries ``exp = iat + iat_window_s`` (:meth:`JwtCodec.mint`), so it is rejected at auth,
        before ``exists()`` is ever consulted, once that window passes. ``iat_window_s`` is
        therefore the true floor; the extra :data:`_TTL_SKEW_MARGIN_S` only absorbs clock skew
        between the App validating ``exp`` and the k8s TTL controller doing the deletion.

        AIDEV-NOTE: this used to derive ``iat_window_s + job_deadline_s``, which conflated two
        different clocks — ``job_deadline_s`` measures a RUN, not the post-completion replay
        gap. At the 16 h default that retained ~960x more Job/Pod objects than the guard needs
        (~14 KB of etcd per request, held for 16 h), which is the scaling ceiling of this design
        rather than a property of it. Do not reintroduce the ``job_deadline_s`` term.
        """
        if self.job_ttl_s is not None:
            return self.job_ttl_s
        return self.iat_window_s + _TTL_SKEW_MARGIN_S

    @field_validator("run_queue_stream")
    @classmethod
    def _reject_sweepable_run_queue_stream(cls, value: str) -> str:
        """Refuse a queue stream named under the per-run `url4-cloud_` prefix.

        The reclamation sweep deletes every stream `owns_stream()` accepts; a queue so
        named is one rejected publish away from being deleted with an accepted run on it.
        The exact-name exclusion in `owns_stream` guards the sites that RECEIVE the
        configured name; this validator makes the hazard impossible at its source, so a
        wiring gap (a site built from the default constant) can only ever produce a
        split — loud — never a swept queue.
        """
        if value.startswith(f"{subjects.PREFIX}_"):
            raise ValueError(
                "run_queue_stream must not live under the per-run prefix 'url4-cloud_': "
                "the orphan sweep deletes any stream it owns, and the queue is the one "
                "stream an accepted run may not be lost from"
            )
        return value

    @field_validator("artifacts_dir", mode="before")
    @classmethod
    def _blank_artifacts_dir_means_unset(cls, value: object) -> object:
        """An empty or whitespace value falls back to the default instead of becoming `Path("")`.

        WHY (OME-929): `Path("")` is the WORKING DIRECTORY, not an error — so a ConfigMap that
        renders the key with no value would silently relocate the store to wherever the process
        happens to be, which for a read-only rootfs also fails at write time rather than here.
        The chart omits the key when it has no value; this makes the same intent safe even if
        some other deployment path renders it blank.
        """
        if isinstance(value, str) and not value.strip():
            return job_env.DEFAULT_ARTIFACTS_DIR
        return value

    @model_validator(mode="after")
    def _reject_replayable_job_ttl(self) -> Self:
        """INVARIANT: an explicit ``job_ttl_s`` may never drop below the token's own lifetime.

        Reclaiming the Job deletes the name that makes a replayed token fail with 409. Below
        ``iat_window_s`` that deletion can happen while the token is still within its ``exp``,
        opening a window for an already-spent token to start a second run. Raising it is
        legitimate (keeping failures around for post-mortem); dropping below the floor is a
        security regression, and is refused at startup rather than on the first replay.
        """
        if self.job_ttl_s is not None and self.job_ttl_s < self.iat_window_s:
            raise ValueError(
                f"job_ttl_s={self.job_ttl_s} is below the replay floor {self.iat_window_s} "
                f"(iat_window_s, the token's own lifetime) — a Job reclaimed while its token is "
                f"still valid re-opens replay"
            )
        return self
