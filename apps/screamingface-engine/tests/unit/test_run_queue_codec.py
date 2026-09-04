"""The queue message codec (OME-1088): ONE encoding, through `job_env`.

The message body is exactly the per-run env mapping `K8sJobRunner._env` writes onto a Job —
topic, expression, deadline, stream grace, validated traceparent, profile, identity headers,
cache policy, extra models, io budget. Both sides render through `job_env`, so there is no
second encoding to drift; these tests pin the two mappings identical.
"""

from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.adapters.k8s import K8sJobRunner
from screamingface_engine.runner_queue import decode_message, encode_message, topic_of_message
from url4.streaming.protocol import CachePolicy

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


class _RecordingBatchApi:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def create_namespaced_job(
        self, namespace: str, body: Any, *, _request_timeout: float | None = None
    ) -> object:
        self.created.append(dict(body))
        return object()

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


def _job_env_mapping(api: _RecordingBatchApi) -> dict[str, str]:
    env = api.created[0]["spec"]["template"]["spec"]["containers"][0]["env"]
    return {entry["name"]: entry["value"] for entry in env}


@pytest.mark.asyncio
async def test_a_queue_message_round_trips_to_the_job_env_mapping() -> None:
    """The queue message decodes to the IDENTICAL env mapping the Job path produces — the
    codec and `K8sJobRunner._env` must never drift into a second encoding."""
    api = _RecordingBatchApi()
    runner = K8sJobRunner(api, image="screamingface-engine:1", io_concurrency=7)
    await runner.schedule(
        "topic-a",
        "'hi'!'go'",
        60,
        traceparent=TRACEPARENT,
        profile="p1",
        identity={"X-User-Email": "a@b.c"},
        cache=CachePolicy(participate=True, max_age=300),
    )
    job_mapping = _job_env_mapping(api)

    message = encode_message(
        "topic-a",
        "'hi'!'go'",
        60,
        traceparent=TRACEPARENT,
        profile="p1",
        identity={"X-User-Email": "a@b.c"},
        cache=CachePolicy(participate=True, max_age=300),
        io_concurrency=7,
    )
    assert decode_message(message) == job_mapping
    assert topic_of_message(message) == "topic-a"


@pytest.mark.asyncio
async def test_an_invalid_traceparent_is_dropped_like_the_job_path_drops_it() -> None:
    api = _RecordingBatchApi()
    runner = K8sJobRunner(api, image="screamingface-engine:1")
    await runner.schedule("topic-a", "'hi'", 60, traceparent="not-a-traceparent")
    job_mapping = _job_env_mapping(api)

    message = encode_message("topic-a", "'hi'", 60, traceparent="not-a-traceparent")
    assert decode_message(message) == job_mapping
    assert job_env.TRACEPARENT not in job_mapping


@pytest.mark.asyncio
async def test_an_unstated_cache_policy_renders_nothing_like_the_job_path() -> None:
    api = _RecordingBatchApi()
    runner = K8sJobRunner(api, image="screamingface-engine:1")
    await runner.schedule("topic-a", "'hi'", 60)
    job_mapping = _job_env_mapping(api)

    message = encode_message("topic-a", "'hi'", 60)
    assert decode_message(message) == job_mapping
    assert job_env.CACHE_PARTICIPATE not in job_mapping
