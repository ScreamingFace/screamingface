from collections.abc import Mapping
from typing import Any

import pytest
from _k8s_fakes import FakeCoreV1, FakeCreatedJob

from screamingface_engine.adapters.factory import build_job_runner
from screamingface_engine.adapters.k8s import K8sJobRunner
from screamingface_engine.config import Settings


class _FakeBatchApi:
    def create_namespaced_job(
        self, namespace: str, body: Mapping[str, object], *, _request_timeout: float | None = None
    ) -> FakeCreatedJob:  # pragma: no cover
        raise NotImplementedError

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


def test_runner_none_builds_no_job_runner() -> None:
    assert build_job_runner(Settings(runner="none")) is None


def test_default_settings_build_no_job_runner() -> None:
    assert build_job_runner(Settings()) is None


def test_k8s_runner_is_built_from_settings() -> None:
    settings = Settings(
        runner="k8s",
        namespace="url4-prod",
        runner_image="ghcr.io/screamingface/url4-cloud:1.2.3",
        nats_url="nats://nats.url4-prod:4222",
    )
    loaded: list[bool] = []

    runner = build_job_runner(
        settings,
        k8s_client_factory=lambda: (loaded.append(True), _FakeBatchApi())[1],
        core_client_factory=FakeCoreV1,
    )

    assert isinstance(runner, K8sJobRunner)
    assert loaded == [True]
    assert runner._namespace == "url4-prod"
    assert runner._image == "ghcr.io/screamingface/url4-cloud:1.2.3"
    # The Job runs the App's OWN image in run mode, so the command IS the mode switch.
    assert runner._command == ["url4-cloud", "run"]


def test_unknown_runner_is_rejected_at_settings_construction() -> None:
    with pytest.raises(ValueError):
        Settings(runner="kubernetes")  # type: ignore[arg-type]


def test_k8s_runner_receives_deployment_scheduling() -> None:
    settings = Settings(
        runner="k8s",
        runner_node_selector={"openmined.org/pool": "preview"},
        runner_tolerations=[
            {
                "key": "workload",
                "operator": "Equal",
                "value": "preview",
                "effect": "NoSchedule",
            }
        ],
    )

    runner = build_job_runner(
        settings,
        k8s_client_factory=_FakeBatchApi,
        core_client_factory=FakeCoreV1,
    )

    assert isinstance(runner, K8sJobRunner)
    assert runner._node_selector == {"openmined.org/pool": "preview"}
    assert runner._tolerations == [
        {
            "key": "workload",
            "operator": "Equal",
            "value": "preview",
            "effect": "NoSchedule",
        }
    ]


def test_k8s_runner_receives_the_settings_io_concurrency() -> None:
    """OME-908: the per-run downstream budget reaches the runner that writes it onto Jobs."""
    settings = Settings(runner="k8s", runner_io_concurrency=9)

    runner = build_job_runner(
        settings,
        k8s_client_factory=_FakeBatchApi,
        core_client_factory=FakeCoreV1,
    )

    assert isinstance(runner, K8sJobRunner)
    assert runner._io_concurrency == 9


def test_k8s_runner_receives_the_core_client() -> None:
    """OME-1065: the quota/limitrange read surface is wired alongside the batch client."""
    settings = Settings(runner="k8s", namespace="url4-prod")

    runner = build_job_runner(
        settings,
        k8s_client_factory=_FakeBatchApi,
        core_client_factory=FakeCoreV1,
    )

    assert isinstance(runner, K8sJobRunner)
    assert isinstance(runner._core_client, FakeCoreV1)
