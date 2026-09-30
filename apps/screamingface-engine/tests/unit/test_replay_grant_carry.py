"""E14 (RP-11) — a run carries an opaque replay grant from the REST edge to every gateway call.

FEATURE: reproducible submissions (OME-1307). A replay run must be served from the cache
version its grant names, so the grant travels the same way the answer seed does (OME-1038):

    GET /?q= (X-SF-Cache-Replay) ──► _schedule ──► ReplayAwareJobRunner.schedule(replay_grant=…)
      ──► the run's ENV ──► request_scope_from_env ──► RequestScope.replay_grant
      ──► the connector's gateway-owned replay header (written LAST) ──► aigateway

INVARIANT (RP-D2, C11): the engine treats the grant as an opaque string. It never decodes it,
never logs it, and exactly one module (`world/connector.py`) spells the outbound header.

INVARIANT: absence is the default. A run with no grant sends byte-identical requests, and a
runner that is not replay-aware keeps working for every plain run.
"""

from __future__ import annotations

import ast
import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner
from fastapi import FastAPI
from httpx import ASGITransport

import screamingface_engine
from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.job_env import RunShape
from screamingface_engine.ports import ReplayAwareJobRunner
from screamingface_engine.request_scope import RequestScope
from screamingface_engine.runner.main import (
    RunnerConfigError,
    build_executor,
    request_scope_from_env,
)
from screamingface_engine.runner_queue import decode_message, encode_message
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.worker.supervisor import cold_child_env
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import CachePolicy

SECRET = "replay-grant-secret"
WINDOW_S = 60
LIFETIME_S = 58_800
T0 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)
MODEL = "anthropic/claude-haiku-4-5"
GRANT = "eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0.eyJ2aWQiOiJ2In0.c2ln"
NOT_A_JWS = "opaque grant with spaces"
_REPLAY_HEADER = "X-SF-Cache-Replay"
_GATEWAY_HEADER = "X-AIGW-Cache-Replay"


class _GrantRecordingRunner(RecordingJobRunner, ReplayAwareJobRunner):
    """`RecordingJobRunner`, plus the one argument the replay port adds.

    Recorded here rather than on the shared fake's `ScheduledRun` on purpose: that tuple is
    compared whole by an existing test, so widening it would change a committed assertion.
    """

    def __init__(self) -> None:
        super().__init__()
        self.replay_grants: list[str | None] = []

    async def schedule(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        credential: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
        answer_seed: int | None = None,
        client_version: str | None = None,
        shape: RunShape = "expression",
        replay_grant: str | None = None,
    ) -> str:
        self.replay_grants.append(replay_grant)
        return await super().schedule(
            topic,
            url4,
            deadline_s,
            traceparent=traceparent,
            credential=credential,
            identity=identity,
        )


async def _start(
    runner: RecordingJobRunner, topic: str, headers: list[tuple[str, str]]
) -> httpx.Response:
    app: FastAPI = create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=InMemoryEventStream(),
        job_runner=runner,
        clock=lambda: T0,
        interest=FixedGate(),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers=[
                (
                    "URL4-Capability",
                    JwtCodec(
                        secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S
                    ).sign(topic, T0),
                ),
                ("Prefer", "respond-async"),
                *headers,
            ],
        )


# --- the REST edge: the header reaches the job runner -----------------------------------------


@pytest.mark.asyncio
async def test_the_replay_header_reaches_the_job_runner_unchanged() -> None:
    runner = _GrantRecordingRunner()

    resp = await _start(runner, "grant-declared", [(_REPLAY_HEADER, GRANT)])

    assert resp.status_code == 202
    assert runner.replay_grants == [GRANT]


@pytest.mark.asyncio
async def test_a_run_without_the_header_schedules_no_grant() -> None:
    """The absence pin: green as soon as the header route exists, kept so a later change that
    defaults a grant onto a plain run fails here."""
    aware = _GrantRecordingRunner()
    plain = RecordingJobRunner()

    aware_resp = await _start(aware, "grant-absent-aware", [])
    plain_resp = await _start(plain, "grant-absent-plain", [])

    assert aware_resp.status_code == 202
    assert aware.replay_grants == [None]
    # A runner that is not replay-aware keeps working for every plain run.
    assert plain_resp.status_code == 202
    assert len(plain.scheduled) == 1


@pytest.mark.asyncio
async def test_an_oversized_grant_is_a_431_and_nothing_is_scheduled() -> None:
    runner = _GrantRecordingRunner()

    resp = await _start(runner, "grant-too-large", [(_REPLAY_HEADER, "g" * 2049)])

    assert resp.status_code == 431
    assert resp.json()["code"] == "replay_grant_too_large"
    assert runner.scheduled == []


@pytest.mark.asyncio
async def test_a_grant_of_exactly_the_limit_is_carried() -> None:
    runner = _GrantRecordingRunner()
    grant = "g" * job_env.MAX_REPLAY_GRANT_BYTES

    resp = await _start(runner, "grant-at-limit", [(_REPLAY_HEADER, grant)])

    assert resp.status_code == 202
    assert runner.replay_grants == [grant]


@pytest.mark.asyncio
async def test_a_blank_grant_header_is_a_plain_run() -> None:
    runner = _GrantRecordingRunner()

    resp = await _start(runner, "grant-blank", [(_REPLAY_HEADER, "   ")])

    assert resp.status_code == 202
    assert runner.replay_grants == [None]


@pytest.mark.asyncio
async def test_two_grant_headers_are_a_400_and_nothing_is_scheduled() -> None:
    runner = _GrantRecordingRunner()

    resp = await _start(
        runner, "grant-ambiguous", [(_REPLAY_HEADER, GRANT), (_REPLAY_HEADER, NOT_A_JWS)]
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "replay_grant_ambiguous"
    assert runner.scheduled == []


@pytest.mark.asyncio
async def test_a_grant_on_a_runner_without_replay_support_is_a_503() -> None:
    runner = RecordingJobRunner()

    resp = await _start(runner, "grant-unsupported", [(_REPLAY_HEADER, GRANT)])

    assert resp.status_code == 503
    assert resp.json()["code"] == "replay_unsupported"
    assert runner.scheduled == []


# --- the two renderings: the queue codec and the in-process adapter ---------------------------


def test_the_queue_codec_carries_the_grant_and_renders_nothing_without_it() -> None:
    carried = decode_message(encode_message("t", "gpt(hi)", 60, replay_grant=GRANT))
    plain = decode_message(encode_message("t", "gpt(hi)", 60))

    assert carried[job_env.CACHE_REPLAY_GRANT] == GRANT
    assert job_env.CACHE_REPLAY_GRANT not in plain


class _NeverExecutor(Executor):
    """Never executed — these tests assert the env the runner BUILDS, not what it then runs."""

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        raise NotImplementedError  # pragma: no cover
        yield  # pragma: no cover


def _local_runner(base_env: dict[str, str]) -> InProcessJobRunner:
    return InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _NeverExecutor(),
        base_env=base_env,
    )


def test_the_inprocess_env_replaces_any_ambient_grant() -> None:
    """`_base_env` is shared by every local run — a grant left there would replay one caller's
    version onto another caller's run."""
    runner = _local_runner({job_env.CACHE_REPLAY_GRANT: "stale"})

    cleared = runner._env("t", "gpt(hi)", 60, None, None, replay_grant=None)  # noqa: SLF001
    stated = runner._env("t", "gpt(hi)", 60, None, None, replay_grant=GRANT)  # noqa: SLF001

    assert job_env.CACHE_REPLAY_GRANT not in cleared
    assert stated[job_env.CACHE_REPLAY_GRANT] == GRANT


def test_cold_child_env_drops_an_ambient_grant() -> None:
    """Only the queue message may carry a grant into a cold child."""
    ambient = {job_env.CACHE_REPLAY_GRANT: "stale"}

    without = cold_child_env(ambient, {}, 4)
    with_run = cold_child_env(ambient, {job_env.CACHE_REPLAY_GRANT: GRANT}, 4)

    assert job_env.CACHE_REPLAY_GRANT not in without
    assert with_run[job_env.CACHE_REPLAY_GRANT] == GRANT


# --- the env contract sets and the run producer -----------------------------------------------


def test_the_grant_env_name_is_per_run_and_never_a_secret_or_deploy_time() -> None:
    assert job_env.CACHE_REPLAY_GRANT in job_env.WRITTEN_BY_APP
    assert job_env.CACHE_REPLAY_GRANT not in job_env.DEPLOY_TIME
    assert job_env.CACHE_REPLAY_GRANT not in job_env.SECRET


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_an_absent_or_blank_grant_reads_back_as_none(raw: str | None) -> None:
    env = {} if raw is None else {job_env.CACHE_REPLAY_GRANT: raw}

    assert job_env.replay_grant_from_env(env) is None


def test_the_grant_reads_back_as_written_not_stripped() -> None:
    padded = f" {NOT_A_JWS} "

    assert job_env.replay_grant_from_env(job_env.replay_grant_to_env(padded)) == padded


def test_the_run_producer_binds_the_grant_into_the_scope() -> None:
    scope = request_scope_from_env({job_env.CACHE_REPLAY_GRANT: NOT_A_JWS})

    assert scope.replay_grant == NOT_A_JWS
    assert request_scope_from_env({}).replay_grant is None


def test_an_over_long_grant_refuses_the_run_without_echoing_it() -> None:
    too_long = "g" * (job_env.MAX_REPLAY_GRANT_BYTES + 1)

    with pytest.raises(RunnerConfigError) as raised:
        request_scope_from_env({job_env.CACHE_REPLAY_GRANT: too_long})

    assert too_long not in str(raised.value)
    assert job_env.CACHE_REPLAY_GRANT in str(raised.value)


def test_the_grant_is_not_in_the_scope_repr() -> None:
    assert GRANT not in repr(RequestScope(origin="run", replay_grant=GRANT))


# --- the run mode: the env reaches the gateway header -----------------------------------------


def _declared() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=MODEL,
            models=(ModelSpec(id=MODEL),),
        )
    )


class _MockAigateway:
    """Records every chat-completions request the world sends."""

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


async def _run_with_env(env: Mapping[str, str]) -> _MockAigateway:
    gw = _MockAigateway()
    async with gw.client() as client:
        executor = build_executor(env, _declared(), client=client)
        async for _ in executor.execute(f"/{MODEL}('ctx')!'go'"):
            pass
    return gw


@pytest.mark.asyncio
async def test_the_runs_env_reaches_the_gateway_header() -> None:
    gw = await _run_with_env(job_env.replay_grant_to_env(GRANT))

    assert [r.headers[_GATEWAY_HEADER] for r in gw.requests] == [GRANT]
    assert json.loads(gw.requests[0].content)["model"] == MODEL


@pytest.mark.asyncio
async def test_a_plain_run_sends_no_replay_header() -> None:
    gw = await _run_with_env({})

    assert len(gw.requests) == 1
    assert _GATEWAY_HEADER not in gw.requests[0].headers


# --- the source: nothing decodes the grant, one module writes the header ----------------------


def test_the_engine_never_decodes_the_grant_and_one_module_writes_it() -> None:
    root = Path(screamingface_engine.__file__).parent
    jwt_importers: list[str] = []
    header_files: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        if _GATEWAY_HEADER.lower() in source.lower():
            header_files.add(relative)
        if relative.startswith("auth/"):
            continue
        for node in ast.walk(ast.parse(source)):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = [node.module]
            if any(name == "jwt" or name.startswith("jwt.") for name in names):
                jwt_importers.append(relative)

    assert jwt_importers == [], "C11: no jwt import outside screamingface_engine/auth/"
    assert header_files == {"world/connector.py"}
