"""The caller's verified identity travels from the mesh gateway's header to aigateway's request.

Cloudflare Access authenticates at the edge and Envoy re-verifies that assertion before stripping
any client-supplied copy and re-injecting `X-User-Email`
(https://pulse.dev.openmined.org/docs/products/gateway-identity-flow/), so what arrives at the App
is trustworthy. It is NOT header pass-through: the App and the Runner Pod are different processes,
and the outgoing aigateway request does not exist yet when the header arrives. So identity is
captured at the REST edge, serialized onto the run's env, and re-rendered by the connector.

These tests pin each hop of that chain separately, plus the two boundaries that make it safe: an
absent header forwards nothing at all, and no inbound value can displace the run's own credential.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner
from _k8s_fakes import FakeCreatedJob, fake_created_job
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.k8s import K8sJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world_config import ModelSpec
from url4.dag import run as url4_run
from url4.streaming.interfaces import ExecStep, Executor, TraceContext

pytestmark = pytest.mark.asyncio

SECRET = "identity-propagation-unit-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
T0 = datetime(2026, 7, 21, 9, 0, 0, tzinfo=UTC)
TOKEN = "tok-identity"  # noqa: S105 - not a real credential, test fixture only
MODEL = "anthropic/claude-haiku-4-5"

IDENTITY = {"X-User-Email": "someone@openmined.org"}


# --- the REST edge: headers -> the scheduled run --------------------------------------------


def _token(topic: str) -> str:
    return JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(topic, T0)


def _app(job_runner: RecordingJobRunner) -> FastAPI:
    return create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=InMemoryEventStream(),
        job_runner=job_runner,
        clock=lambda: T0,
        interest=FixedGate(),
    )


async def _start(runner: RecordingJobRunner, topic: str, **headers: str) -> httpx.Response:
    app = _app(runner)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={
                "URL4-Capability": _token(topic),
                "Prefer": "respond-async",
                **headers,
            },
        )


async def test_the_identity_header_reaches_the_scheduled_run() -> None:
    runner = RecordingJobRunner()

    resp = await _start(runner, "identity-present", **IDENTITY)

    assert resp.status_code == 202
    assert runner.scheduled[0].identity == IDENTITY


async def test_the_header_is_read_case_insensitively() -> None:
    """Whatever casing the gateway emits, one canonical spelling leaves for aigateway."""
    runner = RecordingJobRunner()

    await _start(runner, "identity-lower", **{"x-user-email": "a@b.c"})

    assert runner.scheduled[0].identity == {"X-User-Email": "a@b.c"}


async def test_a_blank_identity_header_is_dropped_not_forwarded_empty() -> None:
    runner = RecordingJobRunner()

    await _start(runner, "identity-blank", **{"X-User-Email": "   "})

    assert runner.scheduled[0].identity is None


async def test_no_identity_header_forwards_nothing() -> None:
    """Absent identity is ``None`` — the same "nothing to forward" credential and profile use."""
    runner = RecordingJobRunner()

    await _start(runner, "identity-none")

    assert runner.scheduled[0].identity is None


async def test_the_dropped_headers_are_not_forwarded() -> None:
    """Tenant and service-token headers are deliberately out of scope and must not travel.

    Forwarding an unread header would put a caller attribute on the wire that nothing downstream
    consumes, which reads to a later maintainer as though it were part of the contract.
    """
    runner = RecordingJobRunner()

    await _start(runner, "identity-dropped", **{"X-Tenant": "openmined", "X-Service-Id": "svc-abc"})

    assert runner.scheduled[0].identity is None


async def test_identity_is_forwarded_without_a_credential() -> None:
    """Unlike the routing profile, identity does not depend on a credential to forward.

    A profile selects WHICH credential aigateway routes, so it is meaningless alone. Identity says
    WHO called, which is true regardless — and dropping it here would silently unattribute a run.
    """
    runner = RecordingJobRunner()

    await _start(runner, "identity-no-cred", **IDENTITY)

    assert runner.scheduled[0].credential is None
    assert runner.scheduled[0].identity == IDENTITY


# --- the env round trip: both adapters render one contract -----------------------------------


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


async def test_the_k8s_adapter_writes_identity_as_plain_env_and_the_runner_reads_it_back() -> None:
    api = _RecordingBatchApi()

    await K8sJobRunner(api, image="runner:test").schedule("t", "gpt(hi)", 60, identity=IDENTITY)

    container = api.created[0]["spec"]["template"]["spec"]["containers"][0]  # type: ignore[index]
    entries = {entry["name"]: entry for entry in container["env"]}
    for name in job_env.IDENTITY_HEADER_ENV.values():
        # Plain `value`, never `valueFrom`: identity is not a credential (see IDENTITY_HEADER_ENV).
        assert "value" in entries[name], f"{name} must be a plain env value, got {entries[name]}"
    env = {name: entry["value"] for name, entry in entries.items() if "value" in entry}

    assert job_env.identity_from_env(env) == IDENTITY


async def test_the_inprocess_adapter_renders_the_same_env_as_the_k8s_one() -> None:
    """The two adapters are two renderings of ONE contract — local mode must not diverge."""
    runner = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _CapturingExecutor(env),
    )

    env = runner._env("t", "gpt(hi)", 60, None, None, IDENTITY)  # noqa: SLF001

    assert job_env.identity_from_env(env) == IDENTITY


async def test_this_requests_identity_replaces_any_ambient_one() -> None:
    """`_base_env` is the App's own environment, so a stale key there must not reach this run.

    Left in place it would attribute one caller's run to whoever ran before them — the worst kind of
    wrong, because the run succeeds and the audit trail simply names the wrong person.
    """
    stale = {job_env.IDENTITY_HEADER_ENV["X-User-Email"]: "previous@caller.test"}
    runner = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _CapturingExecutor(env),
        base_env=stale,
    )

    env = runner._env("t", "gpt(hi)", 60, None, None, IDENTITY)  # noqa: SLF001

    assert job_env.identity_from_env(env) == IDENTITY


async def test_a_run_with_no_identity_clears_any_ambient_one() -> None:
    """An unattributed run must be unattributed, not attributed to the ambient leftover."""
    stale = {job_env.IDENTITY_HEADER_ENV["X-User-Email"]: "previous@caller.test"}
    runner = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _CapturingExecutor(env),
        base_env=stale,
    )

    env = runner._env("t", "gpt(hi)", 60, None, None, None)  # noqa: SLF001

    assert job_env.identity_from_env(env) == {}


class _CapturingExecutor(Executor):
    """Never executed — these tests assert the env the runner BUILDS, not what it then runs."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self.env = env

    async def execute(  # type: ignore[override]
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:  # pragma: no cover - the run is never started
        raise NotImplementedError
        yield  # pragma: no cover - unreachable; makes this an async generator


# --- the connector: identity -> the aigateway request ----------------------------------------


class _MockAigateway:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )


async def _run_once(identity: dict[str, str] | None) -> httpx.Request:
    gw = _MockAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client, identity_headers=identity)
        await url4_run(f"/{MODEL}('ctx')!'go'", world.node)
    assert len(gw.requests) == 1
    return gw.requests[0]


async def test_the_connector_renders_identity_onto_the_chat_completions_request() -> None:
    request = await _run_once(IDENTITY)

    for header, value in IDENTITY.items():
        assert request.headers[header] == value
    assert "authorization" not in request.headers
    assert json.loads(request.content)["model"] == MODEL


async def test_a_run_with_no_identity_sends_no_identity_headers() -> None:
    request = await _run_once(None)

    for header in job_env.IDENTITY_HEADER_ENV:
        assert header not in request.headers


async def test_an_inbound_header_cannot_displace_the_runs_own_profile() -> None:
    """Gateway-owned headers are written LAST.

    Envoy guarantees the identity header itself is not forged, but nothing guarantees the mapping
    reaching the connector holds ONLY that key — so `X-Profile` must win regardless.
    """
    gw = _MockAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(
            cfg,
            client=client,
            profile="gateway-owned",
            identity_headers={**IDENTITY, "X-Profile": "attacker-profile"},
        )
        await url4_run(f"/{MODEL}('ctx')!'go'", world.node)

    assert gw.requests[0].headers["x-profile"] == "gateway-owned"


# --- the contract sets ----------------------------------------------------------------------


def test_identity_is_per_run_and_is_not_a_secret() -> None:
    names = set(job_env.IDENTITY_HEADER_ENV.values())

    assert names <= job_env.WRITTEN_BY_APP, "the App writes identity onto the Job spec"
    assert not (names & job_env.SECRET), (
        "identity authorizes nothing on its own — declaring it SECRET would force it through "
        "valueFrom.secretKeyRef and imply a confidentiality it does not have"
    )
    assert not (names & job_env.DEPLOY_TIME), "identity is per-run; Helm cannot know it"
