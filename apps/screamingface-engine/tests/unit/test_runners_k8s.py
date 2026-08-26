from dataclasses import dataclass

import pytest
from _k8s_fakes import FakeCreatedJob, fake_created_job
from kubernetes.client import ApiException

from screamingface_engine import job_env
from screamingface_engine.adapters.k8s import K8sJobRunner
from url4.streaming.interfaces import JobAlreadyExists, JobRunner, job_name

pytestmark = pytest.mark.asyncio

TOPIC = "cap-topic"


@dataclass
class FakeCondition:
    type: str
    status: str
    reason: str | None = None


@dataclass
class FakeJobStatus:
    active: int | None = None
    conditions: list[FakeCondition] | None = None


@dataclass
class FakeJob:
    status: FakeJobStatus | None = None


class FakeBatchV1:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.states: dict[str, FakeJob] = {}
        self.deleted: list[str] = []
        self.delete_policies: list[str] = []

    def create_namespaced_job(
        self, namespace: str, body, *, _request_timeout: float | None = None
    ) -> FakeCreatedJob:
        name = body["metadata"]["name"]
        if name in self.jobs:
            raise ApiException(status=409)
        self.jobs[name] = body
        return fake_created_job(f"uid-{name}")

    def read_namespaced_job(
        self, name: str, namespace: str, *, _request_timeout: float | None = None
    ) -> FakeJob:
        if name not in self.jobs:
            raise ApiException(status=404)
        return self.states.get(name, FakeJob())

    def delete_namespaced_job(
        self,
        name: str,
        namespace: str,
        *,
        propagation_policy: str = "",
        _request_timeout: float | None = None,
    ) -> dict:
        if name not in self.jobs:
            raise ApiException(status=404)
        del self.jobs[name]
        self.deleted.append(name)
        self.delete_policies.append(propagation_policy)
        return {}


def _runner(client: FakeBatchV1) -> K8sJobRunner:
    return K8sJobRunner(
        client,
        image="registry/screamingface-engine:1",
        namespace="url4",
        env_configmap="screamingface-engine-runner-env",
    )


def test_runner_satisfies_the_port() -> None:
    runner: JobRunner = _runner(FakeBatchV1())
    assert isinstance(runner, JobRunner)


async def test_schedule_builds_a_run_once_named_spec() -> None:
    client = FakeBatchV1()
    runner = _runner(client)
    name = await runner.schedule(TOPIC, "chat(hi)", deadline_s=57600)

    assert name == job_name(TOPIC)
    manifest = client.jobs[name]
    assert manifest["metadata"]["name"] == name
    spec = manifest["spec"]
    assert spec["backoffLimit"] == 0
    # CONTRACT CHANGE (owner-approved 2026-08-10): this asserted `== 57600`, pinning
    # `activeDeadlineSeconds == JOB_DEADLINE_S`. That equality was the defect: the run
    # self-terminates at its own deadline, then waits out the drain grace before deleting its
    # stream, so an identical pod deadline SIGKILLed it mid-teardown and every timed-out run
    # leaked a stream. The run keeps its full requested budget; the POD outlives it by the
    # teardown allowance.
    assert spec["activeDeadlineSeconds"] > 57600 + job_env.DEFAULT_STREAM_GRACE_S
    pod = spec["template"]["spec"]
    assert pod["restartPolicy"] == "Never"
    container = pod["containers"][0]
    assert container["image"] == "registry/screamingface-engine:1"
    env = {e["name"]: e["value"] for e in container["env"]}
    assert env[job_env.TOPIC] == TOPIC
    assert env[job_env.EXPRESSION] == "chat(hi)"
    # The NATS URL is deploy-time: the chart names and values it, the Job inherits it wholesale.
    assert container["envFrom"] == [{"configMapRef": {"name": "screamingface-engine-runner-env"}}]


def _container_env_entries(client: FakeBatchV1, name: str) -> list[dict]:
    manifest = client.jobs[name]
    container = manifest["spec"]["template"]["spec"]["containers"][0]
    return container["env"]


def _container_env(client: FakeBatchV1, name: str) -> dict[str, str]:
    return {e["name"]: e["value"] for e in _container_env_entries(client, name) if "value" in e}


async def test_schedule_omits_the_aigateway_profile_when_none_was_asked_for() -> None:
    client = FakeBatchV1()
    name = await _runner(client).schedule(TOPIC, "chat(hi)", deadline_s=60)

    assert job_env.AIGATEWAY_PROFILE not in _container_env(client, name)


async def test_schedule_forwards_the_profile() -> None:
    client = FakeBatchV1()
    name = await _runner(client).schedule(TOPIC, "chat(hi)", deadline_s=60, profile="p")

    assert _container_env(client, name)[job_env.AIGATEWAY_PROFILE] == "p"


# INVARIANT: a Job never carries an aigateway bearer token, however the caller supplied one.
# aigateway is in `cloudflare_headers` mode in this topology and does not read `Authorization`,
# so forwarding one would store an unread secret and require Secret-write RBAC to do it.
async def test_a_supplied_credential_is_dropped_rather_than_forwarded() -> None:
    client = FakeBatchV1()
    name = await _runner(client).schedule(
        TOPIC, "chat(hi)", deadline_s=60, credential="tok", profile="p"
    )

    entries = _container_env_entries(client, name)
    assert not any("TOKEN" in e["name"] for e in entries)
    assert all("valueFrom" not in e for e in entries), "no Job env may reference a Secret"
    assert "tok" not in str(client.jobs[name])


async def test_schedule_twice_is_the_stateless_single_use_guard() -> None:
    client = FakeBatchV1()
    runner = _runner(client)
    await runner.schedule(TOPIC, "chat(hi)", deadline_s=60)
    with pytest.raises(JobAlreadyExists):
        await runner.schedule(TOPIC, "chat(hi)", deadline_s=60)


async def test_exists_reflects_the_scheduled_job() -> None:
    client = FakeBatchV1()
    runner = _runner(client)
    assert await runner.exists(TOPIC) is False
    await runner.schedule(TOPIC, "chat(hi)", deadline_s=60)
    assert await runner.exists(TOPIC) is True


async def test_stop_deletes_the_job_and_is_idempotent() -> None:
    client = FakeBatchV1()
    runner = _runner(client)
    await runner.schedule(TOPIC, "chat(hi)", deadline_s=60)
    await runner.stop(TOPIC)
    assert client.deleted == [job_name(TOPIC)]
    assert await runner.exists(TOPIC) is False
    await runner.stop(TOPIC)


async def _schedule_with_state(state: FakeJobStatus | None) -> K8sJobRunner:
    client = FakeBatchV1()
    runner = _runner(client)
    await runner.schedule(TOPIC, "chat(hi)", deadline_s=60)
    if state is not None:
        client.states[job_name(TOPIC)] = FakeJob(status=state)
    return runner


async def test_status_not_found_for_unknown_topic() -> None:
    runner = _runner(FakeBatchV1())
    assert await runner.status(TOPIC) == "not_found"


async def test_status_scheduled_when_no_status_yet() -> None:
    runner = await _schedule_with_state(None)
    assert await runner.status(TOPIC) == "scheduled"


async def test_status_running_when_active() -> None:
    runner = await _schedule_with_state(FakeJobStatus(active=1))
    assert await runner.status(TOPIC) == "running"


async def test_status_succeeded_on_complete_condition() -> None:
    runner = await _schedule_with_state(
        FakeJobStatus(conditions=[FakeCondition(type="Complete", status="True")])
    )
    assert await runner.status(TOPIC) == "succeeded"


async def test_status_failed_on_failed_condition() -> None:
    runner = await _schedule_with_state(
        FakeJobStatus(
            conditions=[FakeCondition(type="Failed", status="True", reason="BackoffLimitExceeded")]
        )
    )
    assert await runner.status(TOPIC) == "failed"


async def test_status_timed_out_on_deadline_exceeded() -> None:
    runner = await _schedule_with_state(
        FakeJobStatus(
            conditions=[FakeCondition(type="Failed", status="True", reason="DeadlineExceeded")]
        )
    )
    assert await runner.status(TOPIC) == "timed_out"


async def test_status_ignores_a_false_condition() -> None:
    runner = await _schedule_with_state(
        FakeJobStatus(active=1, conditions=[FakeCondition(type="Complete", status="False")])
    )
    assert await runner.status(TOPIC) == "running"


async def test_status_reraises_non_404_api_errors() -> None:
    class Boom(FakeBatchV1):
        def read_namespaced_job(
            self, name: str, namespace: str, *, _request_timeout: float | None = None
        ) -> FakeJob:
            raise ApiException(status=500)

    runner = _runner(Boom())
    with pytest.raises(ApiException):
        await runner.status(TOPIC)


async def test_schedule_reraises_non_409_api_errors() -> None:
    class Boom(FakeBatchV1):
        def create_namespaced_job(
            self, namespace: str, body, *, _request_timeout: float | None = None
        ) -> FakeCreatedJob:
            raise ApiException(status=500)

    runner = _runner(Boom())
    with pytest.raises(ApiException):
        await runner.schedule(TOPIC, "chat(hi)", deadline_s=60)


async def test_stop_reraises_non_404_api_errors() -> None:
    class Boom(FakeBatchV1):
        def delete_namespaced_job(
            self,
            name: str,
            namespace: str,
            *,
            propagation_policy: str = "",
            _request_timeout: float | None = None,
        ) -> dict:
            raise ApiException(status=500)

    runner = _runner(Boom())
    with pytest.raises(ApiException):
        await runner.stop(TOPIC)


def _pod(client: FakeBatchV1, name: str) -> dict:
    return client.jobs[name]["spec"]["template"]["spec"]


async def test_runner_job_container_is_hardened_like_the_app() -> None:
    client = FakeBatchV1()
    name = await _runner(client).schedule(TOPIC, "chat(hi)", deadline_s=60)

    sec = _pod(client, name)["containers"][0]["securityContext"]
    assert sec["allowPrivilegeEscalation"] is False
    assert sec["capabilities"] == {"drop": ["ALL"]}
    assert sec["runAsNonRoot"] is True
    assert sec["runAsUser"] == 1000
    assert sec["readOnlyRootFilesystem"] is True


async def test_runner_job_pod_sets_the_restricted_seccomp_profile() -> None:
    client = FakeBatchV1()
    name = await _runner(client).schedule(TOPIC, "chat(hi)", deadline_s=60)

    assert _pod(client, name)["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}


async def test_runner_job_mounts_a_writable_tmp_for_the_read_only_root() -> None:
    client = FakeBatchV1()
    name = await _runner(client).schedule(TOPIC, "chat(hi)", deadline_s=60)

    pod = _pod(client, name)
    assert {"name": "tmp", "emptyDir": {}} in pod["volumes"]
    mounts = pod["containers"][0]["volumeMounts"]
    assert {"name": "tmp", "mountPath": "/tmp"} in mounts


async def test_runner_job_does_not_mount_a_serviceaccount_token() -> None:
    client = FakeBatchV1()
    name = await _runner(client).schedule(TOPIC, "chat(hi)", deadline_s=60)

    assert _pod(client, name)["automountServiceAccountToken"] is False


async def test_runner_job_carries_the_configured_resources() -> None:
    client = FakeBatchV1()
    runner = K8sJobRunner(
        client,
        image="registry/screamingface-engine:1",
        namespace="url4",
        resources={"requests": {"cpu": "200m", "memory": "256Mi"}, "limits": {"memory": "1Gi"}},
    )
    name = await runner.schedule(TOPIC, "chat(hi)", deadline_s=60)

    container = _pod(client, name)["containers"][0]
    assert container["resources"] == {
        "requests": {"cpu": "200m", "memory": "256Mi"},
        "limits": {"memory": "1Gi"},
    }


async def test_runner_job_omits_resources_when_unset() -> None:
    client = FakeBatchV1()
    name = await _runner(client).schedule(TOPIC, "chat(hi)", deadline_s=60)

    assert "resources" not in _pod(client, name)["containers"][0]


async def test_runner_job_ttl_is_forwarded_so_finished_jobs_are_reclaimed() -> None:
    client = FakeBatchV1()
    runner = K8sJobRunner(
        client, image="registry/screamingface-engine:1", namespace="url4", job_ttl_s=57660
    )
    name = await runner.schedule(TOPIC, "chat(hi)", deadline_s=60)

    assert client.jobs[name]["spec"]["ttlSecondsAfterFinished"] == 57660


async def test_runner_accepts_a_configured_job_ttl() -> None:
    client = FakeBatchV1()
    runner = K8sJobRunner(
        client,
        image="registry/screamingface-engine:1",
        namespace="url4",
        job_ttl_s=60,
    )
    name = await runner.schedule(TOPIC, "chat(hi)", deadline_s=60)
    assert client.jobs[name]["spec"]["ttlSecondsAfterFinished"] == 60


async def test_runner_job_omits_ttl_when_unset_so_the_replay_guard_never_expires() -> None:
    client = FakeBatchV1()
    name = await _runner(client).schedule(TOPIC, "chat(hi)", deadline_s=60)

    assert "ttlSecondsAfterFinished" not in client.jobs[name]["spec"]


async def test_stop_deletes_the_pod_too_not_just_the_job() -> None:
    """REGRESSION (C1): `stop` must cascade to the Pod, or the run does not actually stop.

    batch/v1 declares `DefaultGarbageCollectionPolicy: OrphanDependents`, so a delete that omits
    `propagation_policy` removes the Job object and leaves its Pod running — still evaluating the
    expression, still publishing frames, still spending the caller's model credit, and now with no
    `activeDeadlineSeconds` to bound it because that lived on the Job. `exists()` reads the Job, so
    the orphan is invisible and the topic can be scheduled again while the first run is still live.

    Asserting the policy reaches the client is the only way to see this without a cluster: the Job
    disappears either way, so every other observable in the fake is identical.
    """
    api = FakeBatchV1()
    runner = K8sJobRunner(api, image="runner:test")
    await runner.schedule(TOPIC, "/m('x')!'go'", 60)

    await runner.stop(TOPIC)

    assert api.delete_policies == ["Background"]


async def test_the_pod_outlives_its_own_stream_reclamation() -> None:
    """REGRESSION: `activeDeadlineSeconds` used to equal `JOB_DEADLINE_S` exactly.

    The runner self-terminates at its own deadline, publishes `Terminated(timed_out)`, then waits
    out the drain grace before deleting its stream. With both deadlines identical, k8s killed the
    pod during that wait, so EVERY timed-out run leaked a stream holding a full `max_bytes`
    reservation — the long runs with the fullest streams, and exactly what the reclamation exists
    to prevent. The Job's hard deadline must leave room for the teardown it is supposed to allow.
    """
    api = FakeBatchV1()
    runner = K8sJobRunner(api, image="runner:test")
    name = await runner.schedule(TOPIC, "/m('x')!'go'", 60)

    spec = api.jobs[name]["spec"]
    env = {e["name"]: e["value"] for e in spec["template"]["spec"]["containers"][0]["env"]}
    grace = float(env[job_env.STREAM_GRACE_S])

    assert float(env[job_env.JOB_DEADLINE_S]) == 60
    assert spec["activeDeadlineSeconds"] > 60 + grace


async def test_runner_job_carries_configured_scheduling() -> None:
    client = FakeBatchV1()
    node_selector = {"openmined.org/pool": "preview"}
    tolerations = [
        {
            "key": "workload",
            "operator": "Equal",
            "value": "preview",
            "effect": "NoSchedule",
        }
    ]
    runner = K8sJobRunner(
        client,
        image="runner:test",
        node_selector=node_selector,
        tolerations=tolerations,
    )
    node_selector["openmined.org/pool"] = "default"
    tolerations[0]["value"] = "default"
    name = await runner.schedule(TOPIC, "chat(hi)", deadline_s=60)
    pod = _pod(client, name)
    assert pod["nodeSelector"] == {"openmined.org/pool": "preview"}
    assert pod["tolerations"] == [
        {"key": "workload", "operator": "Equal", "value": "preview", "effect": "NoSchedule"}
    ]
    assert pod["automountServiceAccountToken"] is False


async def test_runner_job_omits_empty_scheduling() -> None:
    client = FakeBatchV1()
    name = await K8sJobRunner(client, image="runner:test").schedule(
        TOPIC, "chat(hi)", deadline_s=60
    )
    pod = _pod(client, name)
    assert "nodeSelector" not in pod
    assert "tolerations" not in pod


async def test_the_job_carries_the_per_run_io_concurrency() -> None:
    """OME-908: every Job states its downstream budget explicitly, beating `envFrom` staleness."""
    client = FakeBatchV1()
    await _runner(client).schedule(TOPIC, "chat(hi)", 60)

    env = _container_env(client, job_name(TOPIC))
    assert env[job_env.IO_CONCURRENCY] == "16"  # the ctor/Settings default


async def test_an_overridden_io_concurrency_reaches_the_job() -> None:
    client = FakeBatchV1()
    runner = K8sJobRunner(
        client,
        image="registry/screamingface-engine:1",
        namespace="url4",
        io_concurrency=9,
    )

    await runner.schedule(TOPIC, "chat(hi)", 60)

    env = _container_env(client, job_name(TOPIC))
    assert env[job_env.IO_CONCURRENCY] == "9"
