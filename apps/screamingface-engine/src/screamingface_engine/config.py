"""Typed settings for the screamingface-engine App, loaded from `URL4_CLOUD_*`
environment variables."""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from screamingface_engine import job_env

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
    # INVARIANT: stateless iat window (seconds) — start rejected when now - iat exceeds it (§4).
    iat_window_s: int = 60
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
