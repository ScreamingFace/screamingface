from typing import Any

import pytest
from _k8s_fakes import FakeCreatedJob, fake_created_job

from screamingface_engine import job_env
from screamingface_engine.adapters.k8s import K8sJobRunner

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


def _pod_spec(api: _RecordingBatchApi) -> dict[str, Any]:
    return api.created[0]["spec"]["template"]["spec"]


async def test_runner_job_disables_service_link_env_injection() -> None:
    api = _RecordingBatchApi()
    await K8sJobRunner(api, image="screamingface-engine:1").schedule("topic-a", "'hi'!'go'", 60)

    assert _pod_spec(api)["enableServiceLinks"] is False


async def test_runner_job_env_is_exactly_what_the_app_set() -> None:
    """The App's explicit `env` is PER-RUN only; deploy-time values arrive via `envFrom`.

    An exact-set assertion, so a deploy-time variable creeping back into `_env` fails here — that
    would give one value two sources of truth, with the App's copy silently winning.
    """
    api = _RecordingBatchApi()
    await K8sJobRunner(
        api, image="screamingface-engine:1", env_configmap="rel-runner-env"
    ).schedule("topic-a", "'hi'!'go'", 60)

    names = {e["name"] for e in _pod_spec(api)["containers"][0]["env"]}
    # STREAM_GRACE_S joined this set on 2026-08-10 (owner-approved): the App must write it
    # BECAUSE it also widens `activeDeadlineSeconds` to cover the same wait, and two independently
    # configured values would silently disagree — a grace longer than the deadline slack is a pod
    # SIGKILLed mid-teardown. It is per-run by that argument, not deploy-time, so the invariant
    # this test protects is unchanged and the assertion stays exact.
    # EXTRA_MODELS joined on 2026-08-19 (OME-880, PR #633 review F4): the admitted-model
    # overlay is a per-run, schedule-time value, and the entry is written even when EMPTY —
    # an explicit env entry beats `envFrom`, which is exactly what keeps a stale
    # URL4_CLOUD_EXTRA_MODELS left in the Helm ConfigMap from leaking onto a Job. Same
    # invariant, one more per-run key.
    # IO_CONCURRENCY joined on 2026-08-26 (OME-908): the per-run downstream budget is
    # deployment-wide but PER-RUN-rendered, and written unconditionally for the same
    # envFrom-staleness reason as EXTRA_MODELS. Local mode never writes it (its bound is
    # the shared fair-share gate, and `InProcessJobRunner._env` pops ambient copies).
    assert names == {
        job_env.TOPIC,
        job_env.EXPRESSION,
        job_env.JOB_DEADLINE_S,
        job_env.STREAM_GRACE_S,
        job_env.EXTRA_MODELS,
        job_env.IO_CONCURRENCY,
    }
