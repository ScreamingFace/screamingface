"""How the aigateway base URL reaches a Runner Job — via the chart, not via the App.

It is constant for a deployment, so the chart names it AND values it in the runner-env ConfigMap
and each Job inherits it with `envFrom`. The App only references that ConfigMap by name. These
tests pin the App OUT of the path: if it starts writing the variable again there are two sources
of truth for one value, and the quiet one wins.
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
    def create_namespaced_secret(
        self, namespace: str, body: Any, *, _request_timeout: float | None = None
    ) -> object:  # pragma: no cover
        raise NotImplementedError

    def delete_namespaced_secret(
        self, name: str, namespace: str, *, _request_timeout: float | None = None
    ) -> object:  # pragma: no cover
        raise NotImplementedError


def _container(api: _RecordingBatchApi) -> dict[str, Any]:
    return api.created[0]["spec"]["template"]["spec"]["containers"][0]


def _job_env(api: _RecordingBatchApi) -> dict[str, Any]:
    return {item["name"]: item.get("value") for item in _container(api)["env"]}


async def test_the_app_never_writes_the_aigateway_base_url_into_a_job() -> None:
    api = _RecordingBatchApi()

    await K8sJobRunner(
        api, image="screamingface-engine:1", env_configmap="rel-runner-env"
    ).schedule("topic-a", "'hi'!'go'", 60)

    assert runner_job_env.AIGATEWAY_BASE_URL not in _job_env(api)


async def test_the_job_inherits_it_from_the_charts_configmap_instead() -> None:
    api = _RecordingBatchApi()

    await K8sJobRunner(
        api, image="screamingface-engine:1", env_configmap="rel-runner-env"
    ).schedule("topic-a", "'hi'!'go'", 60)

    assert {"configMapRef": {"name": "rel-runner-env"}} in _container(api)["envFrom"]


def test_the_factory_threads_the_configmap_name_from_settings() -> None:
    settings = Settings(runner="k8s", runner_env_configmap="screamingface-engine-runner-env")

    runner = build_job_runner(
        settings,
        k8s_client_factory=_RecordingBatchApi,
        core_client_factory=FakeCoreV1,
    )

    assert isinstance(runner, K8sJobRunner)
    assert runner._env_configmap == "screamingface-engine-runner-env"


def test_the_configmap_name_defaults_to_unset() -> None:
    # A chartless deployment (docker compose, local dev) has no ConfigMap to reference; the Job
    # simply gets no `envFrom` and the Runner falls back to its own defaults.
    assert Settings().runner_env_configmap is None


def test_aigateway_base_url_remains_a_setting_for_the_apps_own_catalog_endpoint() -> None:
    # It stopped being forwarded to Jobs, but the App still needs it for `GET /v1/models`.
    assert Settings().aigateway_base_url is None
    assert Settings(aigateway_base_url="http://aigateway:9105").aigateway_base_url == (
        "http://aigateway:9105"
    )
