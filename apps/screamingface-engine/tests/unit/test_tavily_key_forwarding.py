"""How the Tavily credential reaches a Runner Job — by reference, and named by the chart.

The Secret is deploy-time, so each Job attaches it whole with `envFrom.secretRef`. That injects
every key under its OWN name and cannot rename, which is why the Secret's key must literally be
`TAVILY_API_KEY` (the chart pins that; `tavily.secretKey` is gone).

The invariant that matters is unchanged and stricter than before: the credential is never a
literal in the Job spec. A Job object is readable with `get jobs` RBAC alone.
"""

from typing import Any

import pytest
from _k8s_fakes import FakeCoreV1, FakeCreatedJob, fake_created_job

from screamingface_engine import job_env as runner_job_env
from screamingface_engine.adapters.factory import build_job_runner
from screamingface_engine.adapters.k8s import K8sJobRunner
from screamingface_engine.config import Settings

pytestmark = pytest.mark.asyncio


class _RecordingBatchApi:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def create_namespaced_job(
        self, namespace: str, body: Any, *, _request_timeout: float | None = None
    ) -> FakeCreatedJob:
        self.created.append(dict(body))
        return fake_created_job(f"uid-{body['metadata']['name']}")

    def read_namespaced_job(
        self, name: str, namespace: str, *, _request_timeout: float | None = None
    ) -> Any:  # pragma: no cover
        raise NotImplementedError

    def delete_namespaced_job(
        self,
        name: str,
        namespace: str,
        *,
        propagation_policy: str = "",
        _request_timeout: float | None = None,
    ) -> object:  # pragma: no cover
        raise NotImplementedError


class _RecordingSecretsApi:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def create_namespaced_secret(
        self, namespace: str, body: Any, *, _request_timeout: float | None = None
    ) -> object:
        self.created.append(dict(body))
        return object()

    def delete_namespaced_secret(
        self, name: str, namespace: str, *, _request_timeout: float | None = None
    ) -> object:  # pragma: no cover
        raise NotImplementedError


def _container(api: _RecordingBatchApi) -> dict[str, Any]:
    return api.created[0]["spec"]["template"]["spec"]["containers"][0]


def _entry(api: _RecordingBatchApi, name: str) -> dict[str, Any] | None:
    return next((e for e in _container(api)["env"] if e["name"] == name), None)


async def test_the_job_attaches_the_tavily_secret_by_reference() -> None:
    api = _RecordingBatchApi()

    await K8sJobRunner(
        api, image="screamingface-engine:kind", env_secrets=("screamingface-engine-tavily",)
    ).schedule("topic-a", "(x)!go", 60)

    assert {"secretRef": {"name": "screamingface-engine-tavily"}} in _container(api)["envFrom"]


async def test_the_credential_is_never_a_literal_in_the_job_spec() -> None:
    api = _RecordingBatchApi()

    await K8sJobRunner(
        api, image="screamingface-engine:kind", env_secrets=("screamingface-engine-tavily",)
    ).schedule("topic-a", "(x)!go", 60)

    assert "tvly-" not in repr(api.created[0])
    assert _entry(api, runner_job_env.TAVILY_API_KEY) is None, (
        "the App must not name TAVILY_API_KEY at all — envFrom injects it under the Secret's key"
    )


async def test_a_job_without_a_configured_secret_attaches_none() -> None:
    api = _RecordingBatchApi()

    await K8sJobRunner(api, image="screamingface-engine:kind").schedule("topic-b", "(x)!go", 60)

    assert "envFrom" not in _container(api)


async def test_the_deploy_time_secret_is_the_jobs_only_secret_reference() -> None:
    # The Tavily Secret rides `envFrom` (deploy-time). Nothing per-run does: a run carries no
    # aigateway credential, so no `valueFrom.secretKeyRef` should appear in the container env.
    api = _RecordingBatchApi()
    runner = K8sJobRunner(
        api,
        image="screamingface-engine:kind",
        env_secrets=("s",),
    )

    await runner.schedule("topic-c", "(x)!go", 60)

    assert _entry(api, runner_job_env.TOPIC) == {
        "name": runner_job_env.TOPIC,
        "value": "topic-c",
    }
    container = api.created[0]["spec"]["template"]["spec"]["containers"][0]
    assert all("valueFrom" not in entry for entry in container["env"])
    assert container["envFrom"] == [{"secretRef": {"name": "s"}}]


def test_settings_build_a_runner_carrying_the_secret_name() -> None:
    settings = Settings(runner="k8s", tavily_secret_name="screamingface-engine-tavily")

    runner = build_job_runner(
        settings,
        k8s_client_factory=_RecordingBatchApi,
        core_client_factory=FakeCoreV1,
    )

    assert isinstance(runner, K8sJobRunner)
    assert runner._env_secrets == ["screamingface-engine-tavily"]


def test_settings_without_a_secret_name_attach_no_secret() -> None:
    runner = build_job_runner(
        Settings(runner="k8s"),
        k8s_client_factory=_RecordingBatchApi,
        core_client_factory=FakeCoreV1,
    )

    assert isinstance(runner, K8sJobRunner)
    assert runner._env_secrets == []
