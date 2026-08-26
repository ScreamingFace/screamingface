"""Kubernetes adapter for the `JobRunner` port (`url4.streaming.interfaces`): schedules one
Batch v1 Job per run and maps its live status to `JobStatus` (spec §3).

INVARIANT: a Job carries NO aigateway credential. This adapter only ever runs in the deployed
topology, where aigateway is in `cloudflare_headers` mode and resolves the caller from the
verified `X-User-Email` header — it never reads `Authorization`. A forwarded token would be
unread by its recipient, unobtainable by the caller (aigateway has no public ingress there), and
would cost a per-run Secret plus the RBAC to write one.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from kubernetes.client import ApiException

from screamingface_engine import job_env
from screamingface_engine.ports import IdentityAwareJobRunner
from url4.streaming.interfaces import JobAlreadyExists, JobStatus, job_name
from url4.streaming.protocol import CachePolicy
from url4.streaming.trace import valid_traceparent

_CONFLICT = 409
_NOT_FOUND = 404
# Slack on top of the run deadline and the drain grace, covering the delete round trip itself.
_TEARDOWN_MARGIN_S = 30

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


class K8sJobRunner(IdentityAwareJobRunner):
    """Implements `JobRunner` by scheduling one Kubernetes Batch v1 Job per run. The Job's name
    is derived deterministically from the topic (`job_name`), so `schedule`/`stop`/`status` all
    address the same object without any separate lookup table."""

    def __init__(
        self,
        client: BatchV1JobsClient,
        *,
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
        io_concurrency: int = 16,
    ) -> None:
        self._client = client
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
        try:
            self._client.create_namespaced_job(
                self._namespace,
                self._manifest(
                    name, topic, url4, deadline_s, traceparent, profile, identity, cache
                ),
                _request_timeout=self._request_timeout_s,
            )
        except ApiException as exc:
            if exc.status == _CONFLICT:
                raise JobAlreadyExists(name) from exc
            raise
        return name

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
