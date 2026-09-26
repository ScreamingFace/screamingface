"""OME-1381 — the Engine stops producing selector-bearing runs but still honours legacy ones.

# FEATURE: selector-less provider access, Stage D rollout step 2 (Engine producer-off) — the
# carrier half. `test_selector_refusal.py` pins the ingress; this module pins what a run carries
# from the queue message to the gateway call.
# INVARIANT: a queue message without `AIGATEWAY_PROFILE` runs with NO profile — an ambient worker
# value is removed, never inherited — while a legacy message that carries the field (work accepted
# before the cutover) is honoured and forwarded, on every delivery, until the drain proof. This
# build is the rollback floor for the gateway reject, so both halves must hold at once.
# AIDEV-NOTE: the legacy half is deleted at Phase 5 (the Engine drops the legacy message read and
# forward), not before; the ambient half stays.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from _fakes import FixedGate
from httpx import ASGITransport
from test_aigateway_connector import _MockAigateway
from test_profile_env_characterisation import _FakeMsg, _FakeProcess, _FakePublisher, _FakeQueue
from test_queue_admission import _FakeQueue as _FakeRunQueue
from test_queue_admission import _runner as _queue_runner
from test_scope_producers import MODEL, _config

from screamingface_engine import job_env
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.runner.main import build_executor
from screamingface_engine.runner_queue import encode_message
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.worker.loop import Worker

pytestmark = pytest.mark.asyncio

_AMBIENT = "ambient-team"
_LEGACY = "legacy-team"
# HS256 key of at least 32 bytes (RFC 7518 §3.2): shorter keys make PyJWT warn on every sign.
_SECRET = "selector-carrier-hs256-test-secret-0123456789"
_WINDOW_S = 60
_LIFETIME_S = 58_800
_T0 = datetime(2026, 9, 25, 9, 0, 0, tzinfo=UTC)


# --- the producer: what the REST edge publishes ------------------------------------------------


@pytest.mark.parametrize("profile_header", [None, "", "   "], ids=["absent", "blank", "whitespace"])
async def test_a_run_the_queue_runner_publishes_carries_no_profile(
    profile_header: str | None,
) -> None:
    """New ingress + either worker: the message an old worker would decode has no field to honour.

    Real `QueueJobRunner`, real codec — the fake stops at the broker, so what is asserted is the
    body a worker actually receives.
    """
    queue = _FakeRunQueue()
    app = create_app(
        Settings(jwt_secret=_SECRET, iat_window_s=_WINDOW_S),
        stream=InMemoryEventStream(),
        job_runner=_queue_runner(queue),
        clock=lambda: _T0,
        interest=FixedGate(True),
    )
    codec = JwtCodec(secret=_SECRET, iat_window_s=_WINDOW_S, capability_lifetime_s=_LIFETIME_S)
    headers = {"URL4-Capability": codec.sign("carrier-new", _T0)}
    if profile_header is not None:
        headers["X-Profile"] = profile_header

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/", params={"q": "gpt(hi)"}, headers={**headers, "Prefer": "respond-async"}
        )

    assert response.status_code == 202, response.text
    ((body, _identity),) = queue.published
    assert job_env.AIGATEWAY_PROFILE not in json.loads(body)


# --- the worker: what the child is spawned with ---------------------------------------------


def _delivered(message: bytes, *, times: int = 1) -> _FakeMsg:
    msg = _FakeMsg(message)
    msg.metadata = SimpleNamespace(timestamp=datetime.now(UTC), num_delivered=times)
    return msg


async def _spawned_env(msg: _FakeMsg) -> dict[str, str]:
    """Claim one message through the real worker and return the env its child was spawned with.

    The claim path of `test_profile_env_characterisation._child_env_for`, taking the message
    itself so a test can shape its delivery metadata.
    """
    envs: list[dict[str, str]] = []

    async def spawn(*_args: Any, env: Any = None, **_kwargs: Any) -> _FakeProcess:
        envs.append(dict(env))
        return _FakeProcess()

    worker = Worker(
        queue=_FakeQueue([msg]),
        publisher=_FakePublisher(),
        slots=1,
        drain_grace_s=0.1,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        spawn=spawn,
        pull_timeout_s=0.05,
        kill_grace_s=0.05,
    )
    async with asyncio.TaskGroup() as tg:
        claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001 - the claim path is the unit
        deadline = asyncio.get_running_loop().time() + 2.0
        while not envs:
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the worker never spawned the child")
            await asyncio.sleep(0.01)
        claim.cancel()
    return envs[0]


async def test_a_new_message_on_a_worker_with_an_ambient_profile_runs_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The in-process runner's rule, now on the worker too: absence in the message is absence."""
    monkeypatch.setenv(job_env.AIGATEWAY_PROFILE, _AMBIENT)

    env = await _spawned_env(_delivered(encode_message("carrier-ambient", "'hi'", 60)))

    assert job_env.AIGATEWAY_PROFILE not in env


async def test_removing_the_ambient_profile_leaves_the_rest_of_the_worker_env_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the selector is reset; the deploy-time env the child needs still reaches it."""
    monkeypatch.setenv(job_env.AIGATEWAY_PROFILE, _AMBIENT)
    monkeypatch.setenv("AIGATEWAY_BASE_URL", "http://aigateway.test")

    env = await _spawned_env(_delivered(encode_message("carrier-rest", "'hi'", 60)))

    assert env["AIGATEWAY_BASE_URL"] == "http://aigateway.test"
    assert env[job_env.TOPIC] == "carrier-rest"


async def test_a_legacy_message_is_honoured_on_a_worker_without_an_ambient_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(job_env.AIGATEWAY_PROFILE, raising=False)
    legacy = encode_message("carrier-legacy", "'hi'", 60, profile=_LEGACY)

    env = await _spawned_env(_delivered(legacy))

    assert env[job_env.AIGATEWAY_PROFILE] == _LEGACY


@pytest.mark.parametrize("times", [2, 5])
async def test_a_redelivered_legacy_message_is_honoured_on_every_delivery(
    monkeypatch: pytest.MonkeyPatch, times: int
) -> None:
    """A worker that died mid-run restarts it from scratch; the restart must route the same way."""
    monkeypatch.setenv(job_env.AIGATEWAY_PROFILE, _AMBIENT)
    legacy = encode_message("carrier-redelivered", "'hi'", 60, profile=_LEGACY)

    env = await _spawned_env(_delivered(legacy, times=times))

    assert env[job_env.AIGATEWAY_PROFILE] == _LEGACY


# --- the run: what reaches the gateway -------------------------------------------------------


async def _gateway_profile_header(env: dict[str, str]) -> str | None:
    gw = _MockAigateway((MODEL,))
    async with gw.client() as client:
        executor = build_executor(env, _config(), client=client)
        async for _ in executor.execute(f"/{MODEL}('ctx')!'go'"):
            pass
    (outbound,) = gw.posts_to(MODEL)
    return outbound.headers.get("X-Profile")


async def test_a_legacy_messages_profile_still_reaches_the_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(job_env.AIGATEWAY_PROFILE, _AMBIENT)
    legacy = encode_message("carrier-forward", "'hi'", 60, profile=_LEGACY)

    env = await _spawned_env(_delivered(legacy))

    assert await _gateway_profile_header(env) == _LEGACY


async def test_a_new_message_reaches_the_gateway_without_a_profile_despite_an_ambient_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No silent retarget: the ambient value must not become the run's selector on the wire."""
    monkeypatch.setenv(job_env.AIGATEWAY_PROFILE, _AMBIENT)

    env = await _spawned_env(_delivered(encode_message("carrier-wire", "'hi'", 60)))

    assert await _gateway_profile_header(env) is None
