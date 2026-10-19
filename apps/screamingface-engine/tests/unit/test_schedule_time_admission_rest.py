"""Schedule-time admission, the REST half: a scheduled url4's own models reach its run world.

FEATURE: run any OpenRouter model (OME-878). The App writes the admitted overlay onto each run
(`URL4_CLOUD_EXTRA_MODELS`) at the moment it schedules it, so a model the url4 names must be
admitted BEFORE `job_runner.schedule` takes that snapshot — in the same request, on the same
replica. Until now only a `GET /v1/model-parameters` probe admitted, so a client that schedules a
complete url4 without probing (the SDK's url4 replay, a raw HTTP caller) ran in a world without
its model: every Case failed "Answering failed", zero gateway calls, `runner world models=117`.

INVARIANT (spec 02 §5.3 1a): a frozen-copy replay never asks the gateway to admit a model.
INVARIANT: admission is best-effort — a gateway that refuses or cannot answer still lets the run
be scheduled, and the refusal surfaces on the run's own stream as it did before.

These tests drive the real `create_app` with the real `QueueJobRunner` (fake broker), so the
assertion is on the queue message a worker pod would receive. Only existing ports are used, so
before the fix they fail on BEHAVIOUR, not on an import.

A separate module (append-only gate).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from schedule_admission_support import PUBLISHED_OPUS_URL4

from screamingface_engine import job_env
from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.catalog.admission import AdmissionAnswer, AdmittedModels
from screamingface_engine.catalog.executable import ExecutableModelParameterSource
from screamingface_engine.catalog.port import Credential, ModelParameterResponse
from screamingface_engine.config import Settings
from screamingface_engine.request_scope import REPLAY_FROZEN_COPY_HEADER
from screamingface_engine.rest.mounts import register_mounts
from screamingface_engine.runner_queue import decode_message
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.serving import MountDescriptor, MountTable

pytestmark = pytest.mark.asyncio

_OPUS = "openrouter/anthropic/claude-opus-5.5"
_DECLARED = "openrouter/openai/gpt-5.5"
_EMAIL = {"X-User-Email": "alice@example.com"}
_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
_COPY = "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11"

SECRET = "schedule-time-admission-secret-0123456789"
WINDOW_S = 60
LIFETIME_S = 58_800
T0 = datetime(2026, 10, 19, 9, 0, 0, tzinfo=UTC)


class _FakeQueue:
    """The slice of `RunQueue` the queue runner uses: records every published message."""

    def __init__(self) -> None:
        self.published: list[bytes] = []

    async def publish(self, message: bytes, *, identity: Mapping[str, str] | None = None) -> None:
        self.published.append(message)

    async def depth(self) -> int:
        return 0

    async def oldest_age(self) -> float | None:
        return None


class _FakePublisher:
    async def last_frame(self, topic: str) -> Any:
        return None

    async def stream_exists(self, topic: str) -> bool:
        return True

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


class _FakeControl:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


class _ParamSource:
    """AI Gateway's model-parameter endpoint: always answers 200."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    async def fetch_model_parameters(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> ModelParameterResponse:
        self.fetched.append(model)
        return ModelParameterResponse(status=200, content=b"{}")


class _Admitter:
    def __init__(self, answer: AdmissionAnswer) -> None:
        self.answer = answer
        self.calls: list[tuple[str, Credential, str | None]] = []

    async def admit_model(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> AdmissionAnswer:
        self.calls.append((model, credential, traceparent))
        return self.answer


class _Harness:
    """The App as `app.py` wires it: one overlay, read by the runner, filled by the source."""

    def __init__(self, answer: AdmissionAnswer = AdmissionAnswer(outcome="admitted")) -> None:
        self.admitted = AdmittedModels()
        self.params = _ParamSource()
        self.admitter = _Admitter(answer)
        self.queue = _FakeQueue()
        self.runner = QueueJobRunner(
            queue=self.queue,
            publisher=_FakePublisher(),
            control=_FakeControl(),
            clock=lambda: T0,
            capability_lifetime_s=LIFETIME_S,
            # WHY a callable over the overlay, exactly as `app.py` passes
            # `catalog.admitted_model_ids`: the snapshot is taken inside `schedule`.
            extra_models=lambda: self.admitted.ids,
        )
        self.source = ExecutableModelParameterSource(
            self.params,
            frozenset({_DECLARED}),
            admitted=self.admitted,
            admission_source=self.admitter,
        )

    def app(self) -> FastAPI:
        return create_app(
            Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
            stream=InMemoryEventStream(),
            job_runner=self.runner,
            clock=lambda: T0,
            model_parameters=self.source,
        )

    def run_envs(self) -> list[dict[str, str]]:
        return [decode_message(message) for message in self.queue.published]


async def _start(
    app: FastAPI, url4: str, topic: str, headers: Mapping[str, str] | None = None
) -> httpx.Response:
    # Sync (no `respond-async`): no WebSocket needs to be attached, and the bound is tiny — the
    # assertion is on the queued message, not on the run's outcome.
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(
            "/",
            params={"q": url4},
            headers={
                "URL4-Capability": JwtCodec(
                    secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S
                ).sign(topic, T0),
                "Prefer": "wait=0.01",
                **_EMAIL,
                **(headers or {}),
            },
        )


def _extra_models(env: Mapping[str, str]) -> list[str]:
    raw = env[job_env.EXTRA_MODELS]
    return json.loads(raw) if raw else []


async def test_the_published_replay_url4_runs_in_a_world_that_has_its_model() -> None:
    # STORY: `sf.evaluate("<published url4>")` on a freshly started Engine — nobody has asked
    # `/v1/model-parameters` for the model — still schedules a run whose world can route it.
    harness = _Harness()

    await _start(harness.app(), PUBLISHED_OPUS_URL4, "replay-opus", {"traceparent": _TRACEPARENT})

    (env,) = harness.run_envs()
    assert _extra_models(env) == [_OPUS]
    ((model, credential, traceparent),) = harness.admitter.calls
    assert model == _OPUS
    # The ask runs as the CALLER (the same credential `GET /v1/model-parameters` would derive),
    # and joins the caller's trace.
    assert credential == Credential.derive(_EMAIL)
    assert traceparent == _TRACEPARENT


async def test_an_already_admitted_model_is_not_admitted_twice() -> None:
    harness = _Harness()
    harness.admitted.add(_OPUS)

    await _start(harness.app(), PUBLISHED_OPUS_URL4, "replay-opus-again")

    (env,) = harness.run_envs()
    assert _extra_models(env) == [_OPUS]
    assert harness.admitter.calls == []
    # One forward: the F1 heal check that the gateway still remembers the admission.
    assert harness.params.fetched == [_OPUS]


async def test_a_frozen_copy_replay_never_asks_the_gateway_to_admit() -> None:
    harness = _Harness()

    await _start(
        harness.app(),
        PUBLISHED_OPUS_URL4,
        "frozen-copy-opus",
        {REPLAY_FROZEN_COPY_HEADER: _COPY},
    )

    (env,) = harness.run_envs()
    assert env[job_env.REPLAY_FROZEN_COPY] == _COPY
    assert harness.admitter.calls == []
    assert harness.params.fetched == []


@pytest.mark.parametrize(
    "answer",
    [
        AdmissionAnswer(outcome="refused", code="model_not_on_openrouter", message="no"),
        AdmissionAnswer(outcome="unsupported"),
    ],
    ids=["refused", "unsupported"],
)
async def test_a_gateway_that_says_no_still_schedules_the_run(answer: AdmissionAnswer) -> None:
    # No new status code: the run is scheduled as before and fails on its own stream.
    harness = _Harness(answer)

    await _start(harness.app(), PUBLISHED_OPUS_URL4, "refused-opus")

    (env,) = harness.run_envs()
    assert _extra_models(env) == []
    assert [call[0] for call in harness.admitter.calls] == [_OPUS]


async def test_a_url4_naming_no_dynamic_model_costs_no_upstream_call() -> None:
    harness = _Harness()

    await _start(harness.app(), "/openrouter/openai/gpt-5.5('hi')!'go'", "declared-only")

    (env,) = harness.run_envs()
    assert _extra_models(env) == []
    assert harness.admitter.calls == []
    assert harness.params.fetched == []


async def test_a_mount_call_schedules_unchanged_and_costs_no_upstream_call() -> None:
    # `rest/mounts.py` schedules through the same `_schedule`. A direct run's target is a mount
    # path plus its raw query, not a DAG the run lowers, so it names no model to admit and the
    # call must reach the queue exactly as before, with nothing asked of the gateway.
    harness = _Harness()
    app = harness.app()
    register_mounts(
        app,
        MountTable(
            mounts=(MountDescriptor("/v1/chat/completions", "endpoint", None),),
            config_digest="abc",
        ),
    )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.get(
            "/v1/chat/completions?q=('hi')!'answer'",
            headers={**_EMAIL, "Prefer": "wait=0.01"},
        )

    (env,) = harness.run_envs()
    assert env[job_env.RUN_SHAPE] == "direct"
    assert _extra_models(env) == []
    assert harness.admitter.calls == []
    assert harness.params.fetched == []
