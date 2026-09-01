"""Kubernetes adapter for the `JobRunner` port (`url4.streaming.interfaces`): schedules one
Batch v1 Job per run and maps its live status to `JobStatus` (spec §3).

INVARIANT: a Job carries NO aigateway credential. This adapter only ever runs in the deployed
topology, where aigateway is in `cloudflare_headers` mode and resolves the caller from the
verified `X-User-Email` header — it never reads `Authorization`. A forwarded token would be
unread by its recipient, unobtainable by the caller (aigateway has no public ingress there), and
would cost a per-run Secret plus the RBAC to write one.
"""

import asyncio
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from kubernetes.client import ApiException
from kubernetes.utils.quantity import parse_quantity

from screamingface_engine import job_env
from screamingface_engine.ports import IdentityAwareJobRunner
from url4.streaming.interfaces import (
    JobAlreadyExists,
    JobRunnerAtCapacity,
    JobStatus,
    job_name,
)
from url4.streaming.protocol import CachePolicy
from url4.streaming.trace import valid_traceparent

_CONFLICT = 409
_NOT_FOUND = 404
# Slack on top of the run deadline and the drain grace, covering the delete round trip itself.
_TEARDOWN_MARGIN_S = 30
# How long a failed quota read disables admission before the next retry. A permanently denied
# read (RBAC) must not hammer the API server every refresh; a transient error recovers on the
# next retry. During the backoff, schedules proceed exactly as before this feature.
_QUOTA_FAILURE_BACKOFF_S = 30

RUNNER_LABELS = {
    "app.kubernetes.io/name": "url4-runner",
    "app.kubernetes.io/part-of": "url4-cloud",
    "app.kubernetes.io/component": "job",
}


# WHY: narrow structural Protocols instead of the generated `kubernetes` client models — only
# the fields this adapter actually reads/writes, so callers (including tests) can supply fakes
# without importing or subclassing the real client types.
class _JobCondition(Protocol):
    @property
    def type(self) -> str: ...
    @property
    def status(self) -> str: ...
    @property
    def reason(self) -> str | None: ...


class _JobStatusView(Protocol):
    @property
    def active(self) -> int | None: ...
    @property
    def conditions(self) -> Sequence[_JobCondition] | None: ...


class _JobView(Protocol):
    @property
    def status(self) -> _JobStatusView | None: ...


# `_request_timeout` is the generated kubernetes client's per-call deadline. It is spelled out in
# these Protocols (rather than passed through an untyped `**kwargs`) so that a call site which
# forgets it is a type error: every one of these is a blocking round trip running on a
# `to_thread` worker, and an un-deadlined one holds that worker until the process exits.
class BatchV1JobsClient(Protocol):
    def create_namespaced_job(
        self, namespace: str, body: Mapping[str, object], *, _request_timeout: float | None = None
    ) -> object: ...
    def read_namespaced_job(
        self, name: str, namespace: str, *, _request_timeout: float | None = None
    ) -> _JobView: ...
    # `propagation_policy` is required, not optional, and it is why this signature is spelled out:
    # batch/v1's server-side default is `orphanDependents`, kept for backwards compatibility, so a
    # delete that omits it removes the Job and LEAVES ITS POD RUNNING.
    def delete_namespaced_job(
        self,
        name: str,
        namespace: str,
        *,
        propagation_policy: str,
        _request_timeout: float | None = None,
    ) -> object: ...


# The quota/limitrange read surface, in the same narrow structural style as `BatchV1JobsClient`:
# only the fields this adapter reads, so tests can supply fakes without importing the generated
# client models. `_request_timeout` is spelled out for the same reason as on the jobs client —
# these are blocking round trips running on `to_thread` workers.
class _QuotaStatus(Protocol):
    @property
    def used(self) -> Mapping[str, str] | None: ...
    @property
    def hard(self) -> Mapping[str, str] | None: ...


class _QuotaView(Protocol):
    @property
    def status(self) -> _QuotaStatus | None: ...


class _QuotaList(Protocol):
    @property
    def items(self) -> Sequence[_QuotaView]: ...


class _LimitRangeItem(Protocol):
    @property
    def type(self) -> str: ...
    @property
    def default(self) -> Mapping[str, str] | None: ...
    @property
    def defaultRequest(self) -> Mapping[str, str] | None: ...


class _LimitRangeSpec(Protocol):
    @property
    def limits(self) -> Sequence[_LimitRangeItem] | None: ...


class _LimitRangeView(Protocol):
    @property
    def spec(self) -> _LimitRangeSpec | None: ...


class _LimitRangeList(Protocol):
    @property
    def items(self) -> Sequence[_LimitRangeView]: ...


class CoreV1QuotaClient(Protocol):
    def list_namespaced_resource_quota(
        self, namespace: str, *, _request_timeout: float | None = None
    ) -> _QuotaList: ...
    def list_namespaced_limit_range(
        self, namespace: str, *, _request_timeout: float | None = None
    ) -> _LimitRangeList: ...


def _terminal_status(conditions: Sequence[_JobCondition] | None) -> JobStatus | None:
    """Reads the Job's `Complete`/`Failed` condition, if either has fired; `None` while running."""
    for cond in conditions or ():
        if cond.status != "True":
            continue
        if cond.type == "Complete":
            return "succeeded"
        if cond.type == "Failed":
            return "timed_out" if cond.reason == "DeadlineExceeded" else "failed"
    return None


def _map_status(job: _JobView | None) -> JobStatus:
    """Maps a Job's live state to `JobStatus` (spec §3): terminal condition first, else
    `running`/`scheduled` from whether a Pod is currently active, else `not_found`."""
    if job is None:
        return "not_found"
    view = job.status
    terminal = _terminal_status(view.conditions if view else None)
    if terminal is not None:
        return terminal
    return "running" if (view and view.active) else "scheduled"


@dataclass(frozen=True, slots=True)
class _QuotaSnapshot:
    """One cached reading of the namespace's capacity, in exact integer units.

    cpu is in millicores ("200m" → 200, "2" → 2000), memory in bytes, pods as a count.
    Integer arithmetic keeps the ceiling comparison exact: a float comparison at the ceiling
    (0.4 + 8*0.2 > 2.0) would refuse the run that exactly fills the quota.
    """

    used: dict[str, int]
    hard: dict[str, int]
    # The quota charge of ONE Runner Pod: its own `resources` spec plus LimitRange defaults.
    charge: dict[str, int]


def _quantity(dimension: str, value: str) -> int:
    """Parse a k8s resource quantity into an exact integer in the dimension's natural unit.

    cpu → millicores, everything else → its natural unit (bytes for memory, count for pods).
    `parse_quantity` returns a float (0.2 for "200m"); scaling to the natural unit and
    truncating keeps the admission arithmetic exact.
    """

    parsed = parse_quantity(value)
    if "cpu" in dimension:
        return int(parsed * 1000)
    return int(parsed)


def _max_quantity(target: dict[str, int], key: str, value: str) -> None:
    parsed = _quantity(key, value)
    if key not in target or parsed > target[key]:
        target[key] = parsed


def _limitrange_defaults(
    limitranges: Sequence[_LimitRangeView],
) -> tuple[dict[str, int], dict[str, int]]:
    """The namespace's effective LimitRange defaults: max per resource across LimitRanges.

    Conservative: if two LimitRanges disagree on a default, the Pod would be rejected as
    ambiguous anyway, and the larger charge is the honest estimate. `default` fills missing
    LIMITS, `defaultRequest` fills missing REQUESTS.
    """

    default_limits: dict[str, int] = {}
    default_requests: dict[str, int] = {}
    for limitrange in limitranges:
        spec = limitrange.spec
        if spec is None:
            continue
        for item in spec.limits or ():
            if item.type != "Container":
                continue
            for key, value in (item.default or {}).items():
                _max_quantity(default_limits, key, value)
            for key, value in (item.defaultRequest or {}).items():
                _max_quantity(default_requests, key, value)
    return default_limits, default_requests


def _pod_charge(
    resources: Mapping[str, Mapping[str, str]] | None,
    limitranges: Sequence[_LimitRangeView],
) -> dict[str, int]:
    """The quota charge of one Runner Pod: its own spec plus LimitRange defaults.

    The runner sets no `limits.cpu`, so the namespace LimitRange supplies it — the arithmetic
    is wrong by 500m per Pod if that default is not accounted for (OME-1064).
    """

    requests = (resources or {}).get("requests", {})
    limits = (resources or {}).get("limits", {})
    default_limits, default_requests = _limitrange_defaults(limitranges)

    def spec_or_default(
        spec: Mapping[str, str], defaults: Mapping[str, int], key: str, dimension: str
    ) -> int:
        value = spec.get(key)
        if value is not None:
            return _quantity(dimension, value)
        return defaults.get(key, 0)

    return {
        "pods": 1,
        "requests.cpu": spec_or_default(requests, default_requests, "cpu", "requests.cpu"),
        "requests.memory": spec_or_default(requests, default_requests, "memory", "requests.memory"),
        "limits.cpu": spec_or_default(limits, default_limits, "cpu", "limits.cpu"),
        "limits.memory": spec_or_default(limits, default_limits, "memory", "limits.memory"),
    }


def _merge_quota(
    target_used: dict[str, int], target_hard: dict[str, int], quota: _QuotaView
) -> None:
    """Fold one quota into the running used/hard: max used, min hard per dimension."""
    status = quota.status
    if status is None:
        return
    for key, value in (status.used or {}).items():
        parsed = _quantity(key, value)
        if key not in target_used or parsed > target_used[key]:
            target_used[key] = parsed
    for key, value in (status.hard or {}).items():
        parsed = _quantity(key, value)
        if key not in target_hard or parsed < target_hard[key]:
            target_hard[key] = parsed


def _build_snapshot(
    quotas: Sequence[_QuotaView],
    limitranges: Sequence[_LimitRangeView],
    resources: Mapping[str, Mapping[str, str]] | None,
) -> _QuotaSnapshot | None:
    """Merge the namespace's quotas into one snapshot; `None` when nothing constrains it.

    Multiple quotas all apply, so the effective hard is the MIN per dimension and the effective
    used the MAX (the used values should agree, modulo update timing).
    """

    if not quotas:
        return None
    used: dict[str, int] = {}
    hard: dict[str, int] = {}
    for quota in quotas:
        _merge_quota(used, hard, quota)
    if not hard:
        return None
    return _QuotaSnapshot(used=used, hard=hard, charge=_pod_charge(resources, limitranges))


class K8sJobRunner(IdentityAwareJobRunner):
    """Implements `JobRunner` by scheduling one Kubernetes Batch v1 Job per run. The Job's name
    is derived deterministically from the topic (`job_name`), so `schedule`/`stop`/`status` all
    address the same object without any separate lookup table."""

    def __init__(
        self,
        client: BatchV1JobsClient,
        *,
        core_client: CoreV1QuotaClient | None = None,
        image: str,
        namespace: str = "default",
        # WHY this default: the Job runs the App's OWN image in its run mode
        # (`screamingface_engine.cli`), so the command is the mode switch and nothing
        # else. It is pinned here, beside the Job spec that uses it, rather than
        # exposed as a chart value — the entrypoint belongs to the image, and a
        # values-file override could only ever name a mode the image does not have.
        command: Sequence[str] = ("url4-cloud", "run"),
        env_configmap: str | None = None,
        env_secrets: Sequence[str] = (),
        resources: Mapping[str, Mapping[str, str]] | None = None,
        node_selector: Mapping[str, str] | None = None,
        tolerations: Sequence[Mapping[str, object]] = (),
        job_ttl_s: int | None = None,
        request_timeout_s: float | None = None,
        extra_models: Callable[[], Sequence[str]] | None = None,
        # FEATURE (OME-908): the per-run downstream in-flight budget, written onto every Job
        # from `Settings.runner_io_concurrency` and enforced by the run's own URL4 layer.
        # Default matches the setting's default so a directly-constructed runner (tests) is
        # honest about what a scheduled run actually gets.
        io_concurrency: int = 4,
        # FEATURE (OME-1065): how long a quota reading stays fresh before the next refresh.
        # A `get` per schedule would add an API round-trip to the hot path; the reservation
        # counter covers the window between refreshes.
        quota_cache_ttl_s: float = 2.0,
    ) -> None:
        self._client = client
        # WHY optional: admission is an optimisation over detection (OME-1059), never a
        # replacement for it. `None` disables admission — the factory always wires the real
        # client; direct constructions (tests) opt out by default.
        self._core_client = core_client
        self._request_timeout_s = request_timeout_s
        self._image = image
        self._namespace = namespace
        self._command = list(command)
        self._env_configmap = env_configmap
        self._env_secrets = list(env_secrets)
        self._resources = resources
        # WHY snapshots: deployment settings can be caller-owned mutable objects. A later
        # mutation must not redirect future Jobs or remove a required taint boundary.
        self._node_selector = dict(node_selector or {})
        self._tolerations = [dict(toleration) for toleration in tolerations]
        self._job_ttl_s = job_ttl_s
        # WHY a callable and not a snapshot (OME-880): the admitted-model overlay grows while
        # the app runs, and a model admitted a second ago must reach the very next Job.
        self._extra_models = extra_models
        self._io_concurrency = io_concurrency
        # FEATURE (OME-1065): quota admission state. `_quota_snapshot` is the last successful
        # reading; `_quota_cache_time` is when it was taken (or, on a failed read, when the
        # backoff ends). `_reserved` counts runs admitted since the last refresh — it closes
        # the read-modify-write race when several `schedule()` calls run between two refreshes.
        # The lock makes refresh + check + reserve atomic; `_schedule_blocking` runs on
        # `to_thread` workers, so it is a threading lock, not an asyncio one.
        self._quota_cache_ttl_s = quota_cache_ttl_s
        self._quota_snapshot: _QuotaSnapshot | None = None
        self._quota_cache_time: float | None = None
        self._reserved = 0
        self._admission_lock = threading.Lock()

    async def schedule(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        credential: str | None = None,
        profile: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
    ) -> str:
        """Creates the Job.

        `credential` is accepted for port compatibility and DELIBERATELY DROPPED: see the module
        INVARIANT. A caller that still sends `Authorization` is not an error — aigateway would
        ignore the token anyway — so the run proceeds on its verified identity alone.

        Raises:
            JobAlreadyExists: a Job for this topic already exists (409 from the API server).
            JobRunnerAtCapacity: the namespace ResourceQuota has no headroom for one more
                Runner Pod (503 + `Retry-After` at the REST edge).
        """
        return await asyncio.to_thread(
            self._schedule_blocking,
            topic,
            url4,
            deadline_s,
            traceparent=traceparent,
            profile=profile,
            identity=identity,
            cache=cache,
        )

    def _schedule_blocking(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        profile: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
    ) -> str:
        name = job_name(topic)
        self._reserve_or_raise()
        try:
            self._client.create_namespaced_job(
                self._namespace,
                self._manifest(
                    name, topic, url4, deadline_s, traceparent, profile, identity, cache
                ),
                _request_timeout=self._request_timeout_s,
            )
        except ApiException as exc:
            # The reservation was for a Job that does not exist — release it so the next
            # schedule in this window is not refused for a run that never started.
            self._release_reservation()
            if exc.status == _CONFLICT:
                raise JobAlreadyExists(name) from exc
            raise
        return name

    # --- quota admission (OME-1065) ---------------------------------------------------------

    def _reserve_or_raise(self) -> None:
        """Admission gate: refresh the quota, refuse if one more Pod does not fit, else reserve.

        Raises:
            JobRunnerAtCapacity: the namespace quota has no headroom for one more Runner Pod.
        """
        if self._core_client is None:
            return
        with self._admission_lock:
            self._refresh_quota_if_stale()
            if self._quota_snapshot is not None and not self._fits(
                self._quota_snapshot, self._reserved
            ):
                raise JobRunnerAtCapacity(
                    self._reserved, self._max_runs_that_fit(self._quota_snapshot)
                )
            self._reserved += 1

    def _release_reservation(self) -> None:
        if self._core_client is None:
            return
        with self._admission_lock:
            self._reserved -= 1

    def _refresh_quota_if_stale(self) -> None:
        """Re-read the quota and LimitRanges when the cache is stale; degrade on failure.

        A failed read (absent, RBAC denied, API error) falls back to today's behaviour: create
        the Job and let OME-1059's detection catch an un-startable run. The backoff is longer
        than the TTL so a permanently denied read does not hammer the API server.
        """
        now = time.monotonic()
        if (
            self._quota_cache_time is not None
            and now - self._quota_cache_time < self._quota_cache_ttl_s
        ):
            return
        core = self._core_client
        if core is None:
            return
        try:
            quotas = core.list_namespaced_resource_quota(
                self._namespace, _request_timeout=self._request_timeout_s
            )
            limitranges = core.list_namespaced_limit_range(
                self._namespace, _request_timeout=self._request_timeout_s
            )
        except ApiException:
            self._quota_snapshot = None
            self._quota_cache_time = now + _QUOTA_FAILURE_BACKOFF_S
            return
        self._quota_snapshot = _build_snapshot(quotas.items, limitranges.items, self._resources)
        self._quota_cache_time = now
        # The quota's `used` now reflects everything older than the window, so the window's
        # reservations are reset — the counter only covers the gap between refreshes.
        self._reserved = 0

    def _fits(self, snapshot: _QuotaSnapshot, reserved: int) -> bool:
        """Whether one more Pod fits on every charged dimension the quota constrains."""
        for dimension, charge in snapshot.charge.items():
            if charge <= 0 or dimension not in snapshot.hard:
                continue
            used = snapshot.used.get(dimension, 0)
            if used + (reserved + 1) * charge > snapshot.hard[dimension]:
                return False
        return True

    def _max_runs_that_fit(self, snapshot: _QuotaSnapshot) -> int:
        """The number of additional Pods that fit, bounded by the tightest dimension."""
        limit: int | None = None
        for dimension, charge in snapshot.charge.items():
            if charge <= 0 or dimension not in snapshot.hard:
                continue
            headroom = snapshot.hard[dimension] - snapshot.used.get(dimension, 0)
            fits = headroom // charge
            limit = fits if limit is None else min(limit, fits)
        return limit if limit is not None else 0

    async def stop(self, topic: str) -> None:
        await asyncio.to_thread(self._stop_blocking, topic)

    def _stop_blocking(self, topic: str) -> None:
        name = job_name(topic)
        try:
            self._delete_job(name)
        except ApiException as exc:
            if exc.status != _NOT_FOUND:
                raise

    def _delete_job(self, name: str) -> None:
        """Delete a Job AND the Pod running it.

        INVARIANT: `propagation_policy="Background"` is mandatory. batch/v1 declares
        `DefaultGarbageCollectionPolicy: OrphanDependents`, so a delete that omits the policy
        removes the Job object and leaves its Pod running — still evaluating the expression, still
        publishing frames, still spending the caller's model credit, with `activeDeadlineSeconds`
        gone along with the Job that carried it. It is also invisible afterwards: `exists()` reads
        the Job, so it reports `not_found` while the Pod runs on, and the topic can be scheduled
        again while the first run is live. This is why `kubectl delete job` passes
        `--cascade=background` explicitly rather than relying on the default.
        """
        self._client.delete_namespaced_job(
            name,
            self._namespace,
            propagation_policy="Background",
            _request_timeout=self._request_timeout_s,
        )

    async def exists(self, topic: str) -> bool:
        return await asyncio.to_thread(self._read, topic) is not None

    async def status(self, topic: str) -> JobStatus:
        return _map_status(await asyncio.to_thread(self._read, topic))

    def _read(self, topic: str) -> _JobView | None:
        try:
            return self._client.read_namespaced_job(
                job_name(topic), self._namespace, _request_timeout=self._request_timeout_s
            )
        except ApiException as exc:
            if exc.status == _NOT_FOUND:
                return None
            raise

    def _env(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        traceparent: str | None,
        profile: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
    ) -> list[dict[str, object]]:
        # INVARIANT: PER-RUN values only. Everything constant for a deployment (the NATS URL, the
        # aigateway base URL and model, the Tavily key) arrives through `envFrom` — Helm owns both
        # its name and its value, so the App never learns those names. What is left here is what
        # Helm cannot know: it does not exist until someone submits a run.
        env: list[dict[str, object]] = [
            {"name": job_env.TOPIC, "value": topic},
            {"name": job_env.EXPRESSION, "value": url4},
            {"name": job_env.JOB_DEADLINE_S, "value": str(deadline_s)},
            {"name": job_env.STREAM_GRACE_S, "value": str(job_env.DEFAULT_STREAM_GRACE_S)},
        ]
        forwarded_traceparent = valid_traceparent(traceparent)
        if forwarded_traceparent is not None:
            env.append({"name": job_env.TRACEPARENT, "value": forwarded_traceparent})
        if profile is not None:
            env.append({"name": job_env.AIGATEWAY_PROFILE, "value": profile})
        # Plain `value`, deliberately — identity authorizes nothing on its own, and a Secret would
        # imply a confidentiality it does not have (see `job_env.IDENTITY_HEADER_ENV`). It is
        # absent from `job_env.SECRET` for the same reason, which is what lets
        # `test_job_env_contract` keep asserting that every SECRET name travels by reference.
        # INVARIANT: no bearer-token entry is ever emitted here — see the module
        # docstring. That is what makes `job_env.SECRET` vacuous for this adapter.
        env.extend(
            {"name": name, "value": value}
            for name, value in job_env.identity_to_env(identity or {}).items()
        )
        # Plain `value` again, and for a plainer reason: a cache directive names nothing about the
        # caller and authorizes nothing — it says only whether this run may reuse a stored answer.
        # A run that declared nothing writes nothing, so a Job spec still shows exactly what was
        # decided rather than the default restated.
        env.extend(
            {"name": name, "value": value}
            for name, value in job_env.cache_policy_to_env(cache).items()
        )
        # The admitted-model overlay (OME-880), read at SCHEDULE time. Plain `value`: model ids
        # are public catalog names, not credentials.
        # INVARIANT (review F4): the entry is ALWAYS written — empty when there is no
        # overlay — because an explicit env entry beats `envFrom`. This is the k8s
        # rendering of the inprocess adapter's unconditional pop: a stale
        # URL4_CLOUD_EXTRA_MODELS left in the Helm-owned ConfigMap can never leak
        # onto a Job.
        overlay = () if self._extra_models is None else self._extra_models()
        rendered = job_env.extra_models_to_env(overlay).get(job_env.EXTRA_MODELS, "")
        env.append({"name": job_env.EXTRA_MODELS, "value": rendered})
        # FEATURE (OME-908): written UNCONDITIONALLY, exactly like EXTRA_MODELS — an explicit
        # env entry beats `envFrom`, which is what keeps a stale copy in the Helm ConfigMap
        # from leaking a different budget onto a Job.
        env.append({"name": job_env.IO_CONCURRENCY, "value": str(self._io_concurrency)})
        return env

    def _env_from(self) -> list[dict[str, object]]:
        """The deploy-time env sources the Job inherits wholesale.

        `envFrom` injects every key of a ConfigMap/Secret under its OWN name, which is the point:
        the chart is the single place a deploy-time Runner variable is named. Ordering matters
        only against `env`, which always wins — so a per-run value can never be shadowed.
        """
        sources: list[dict[str, object]] = []
        if self._env_configmap is not None:
            sources.append({"configMapRef": {"name": self._env_configmap}})
        sources.extend({"secretRef": {"name": name}} for name in self._env_secrets)
        return sources

    def _manifest(
        self,
        name: str,
        topic: str,
        url4: str,
        deadline_s: int,
        traceparent: str | None = None,
        profile: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
    ) -> dict[str, object]:
        """Builds the Job manifest: a hardened, single-attempt Pod (no restarts, no privilege
        escalation, non-root, read-only rootfs) running `self._command` with per-run env layered
        over the deploy-time `envFrom` sources, and an optional `ttlSecondsAfterFinished`."""
        container: dict[str, object] = {
            "name": "runner",
            "image": self._image,
            "command": self._command,
            "env": self._env(topic, url4, deadline_s, traceparent, profile, identity, cache),
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"]},
                "runAsNonRoot": True,
                "runAsUser": 1000,
                "readOnlyRootFilesystem": True,
            },
            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
        }
        env_from = self._env_from()
        if env_from:
            container["envFrom"] = env_from
        if self._resources is not None:
            container["resources"] = {k: dict(v) for k, v in self._resources.items()}
        pod_spec: dict[str, object] = {
            "restartPolicy": "Never",
            "enableServiceLinks": False,
            "automountServiceAccountToken": False,
            "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
            "containers": [container],
            "volumes": [{"name": "tmp", "emptyDir": {}}],
        }
        # INVARIANT: the operator owns placement through Helm. The adapter transports those
        # Kubernetes-native values without embedding Preview or another environment's policy.
        if self._node_selector:
            pod_spec["nodeSelector"] = dict(self._node_selector)
        if self._tolerations:
            pod_spec["tolerations"] = [dict(toleration) for toleration in self._tolerations]
        spec: dict[str, object] = {
            "backoffLimit": 0,
            # WHY this is NOT `deadline_s`: the run self-terminates at `JOB_DEADLINE_S`, publishes
            # its terminal frame, then waits out `STREAM_GRACE_S` before deleting its own stream.
            # Setting the pod's hard deadline to the same value SIGKILLed it mid-wait, so every
            # timed-out run leaked a stream holding a full `max_bytes` reservation — the long runs
            # with the fullest streams. The pod has to outlive the teardown it is asked to do.
            "activeDeadlineSeconds": (
                deadline_s + int(job_env.DEFAULT_STREAM_GRACE_S) + _TEARDOWN_MARGIN_S
            ),
            "template": {
                "metadata": {"labels": RUNNER_LABELS},
                "spec": pod_spec,
            },
        }
        if self._job_ttl_s is not None:
            spec["ttlSecondsAfterFinished"] = self._job_ttl_s
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": name, "labels": RUNNER_LABELS},
            "spec": spec,
        }
