"""Characterisation of how a profile selector travels into a run, and of the Local listing's
ambiguity rule (OME-1199, Stage 0 of OME-1138).

# FEATURE: OME-1138 adapter-first convergence. The later selector sunset (Stage D) rejects a
# present `AIGATEWAY_PROFILE`; the Local listing's 409 ambiguity rule is a retained consumer
# obligation that must survive untouched while the Hosted listing moves (A4). Both are pinned
# here BEFORE any boundary work.
# AIDEV-NOTE: this module records LEGACY behaviour exactly; it does not judge or fix it. The
# queued runner and the in-process runner disagree about an ambient profile today — that
# asymmetry is the point of the first three tests, not a defect they should make go away.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import Caller, ConnectionConflict
from screamingface_engine.runner_queue import encode_message
from screamingface_engine.worker.loop import Worker
from url4.streaming.interfaces import Completed, ExecStep, Executor, TraceContext
from url4.streaming.protocol import TerminatedEvent

pytestmark = pytest.mark.asyncio

_AMBIENT = "ambient-team"


# --- the worker's fakes: the slice of the queue, the publisher and the child the claim path
# touches, mirroring `test_worker_claim.py` -----------------------------------------------------


class _FakeMsg:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.metadata = SimpleNamespace(timestamp=datetime.now(UTC))
        self.headers: dict[str, str] | None = None

    async def ack(self) -> None:
        pass

    async def in_progress(self) -> None:
        pass


class _FakePublisher:
    async def last_frame(self, topic: str) -> TerminatedEvent | None:
        return None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


class _FakeProcess:
    """A child that has already exited cleanly."""

    returncode: int | None = 0
    stdout = None
    stderr = None

    async def wait(self) -> int:
        return 0

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


class _FakeQueue:
    def __init__(self, batch: list[_FakeMsg]) -> None:
        self._batch: list[_FakeMsg] | None = batch

    async def pull(self, batch: int, timeout_s: float) -> list[_FakeMsg]:
        if self._batch is not None:
            served, self._batch = self._batch, None
            return served
        await asyncio.sleep(timeout_s)
        return []


async def _child_env_for(message: bytes) -> dict[str, str]:
    """Claim one message through the real worker and return the env its child was spawned with."""
    envs: list[dict[str, str]] = []

    async def spawn(*_args: Any, env: Any = None, **_kwargs: Any) -> _FakeProcess:
        envs.append(dict(env))
        return _FakeProcess()

    worker = Worker(
        queue=_FakeQueue([_FakeMsg(message)]),
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
        claim = tg.create_task(worker._claim_loop(tg))
        deadline = asyncio.get_running_loop().time() + 2.0
        while not envs:
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the worker never spawned the child")
            await asyncio.sleep(0.01)
        claim.cancel()
    return envs[0]


# --- 1. the queued runner: the child INHERITS an ambient profile the message did not carry ----


async def test_the_worker_child_inherits_an_ambient_profile_the_message_did_not_carry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """# INVARIANT (legacy, pinned): `RunSupervisor._child_env` starts from `dict(os.environ)`
    and overlays the message (`worker/supervisor.py:729-744`); the queue codec writes
    `AIGATEWAY_PROFILE` only when a profile was requested (`runner_queue._env_mapping`) and never
    clears it. A worker Pod with an ambient profile therefore routes every profile-less run
    through that profile.
    """
    monkeypatch.setenv(job_env.AIGATEWAY_PROFILE, _AMBIENT)

    env = await _child_env_for(encode_message("t-profile-inherit", "'hi'", 60))

    assert env[job_env.AIGATEWAY_PROFILE] == _AMBIENT


async def test_a_profile_carried_by_the_message_replaces_the_ambient_one_in_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The message's per-run values win over the worker's ambient ones — the merge order the
    `_child_env` docstring promises."""
    monkeypatch.setenv(job_env.AIGATEWAY_PROFILE, _AMBIENT)

    env = await _child_env_for(encode_message("t-profile-carried", "'hi'", 60, profile="p"))

    assert env[job_env.AIGATEWAY_PROFILE] == "p"


# --- 2. the in-process runner: an ambient profile is DROPPED unless the request carries one --


class _CompletingExecutor(Executor):
    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        from decimal import Decimal

        from url4.streaming.protocol import ResultData
        from url4.streaming.protocol.signals import CostUsageData
        from url4.streaming.protocol.taxonomy import CostBreakdown, TokenUsage

        yield Completed(
            result=ResultData(body="ok"),
            subtree_cost=CostUsageData(
                scope="self",
                provider="test",
                model="test-model",
                pricing_version="v0",
                usage=TokenUsage(input_tokens=0, output_tokens=0),
                cost=CostBreakdown(total_usd=Decimal("0")),
            ),
        )


async def _in_process_env_for(profile: str | None) -> dict[str, str]:
    stream = InMemoryEventStream()
    seen: list[dict[str, str]] = []

    def factory(env: Any) -> Executor:
        seen.append(dict(env))
        return _CompletingExecutor()

    runner = InProcessJobRunner(
        stream, factory, base_env={job_env.AIGATEWAY_PROFILE: _AMBIENT}, max_concurrent_runs=1
    )
    await runner.schedule("t-local-profile", "'hi'", 42, traceparent=None, profile=profile)
    async for event in stream.subscribe("t-local-profile", from_sequence=None):
        if isinstance(event, TerminatedEvent):
            break
    return seen[0]


async def test_the_in_process_runner_drops_an_ambient_profile_the_request_did_not_carry() -> None:
    """# INVARIANT (legacy, pinned): `InProcessJobRunner._env` pops `AIGATEWAY_PROFILE` when the
    request carries none (`adapters/inprocess.py:179-185`) — the opposite of what the worker
    does with the same ambient variable.
    """
    env = await _in_process_env_for(profile=None)

    assert job_env.AIGATEWAY_PROFILE not in env


async def test_the_in_process_runner_lets_a_requested_profile_replace_the_ambient_one() -> None:
    env = await _in_process_env_for(profile="p")

    assert env[job_env.AIGATEWAY_PROFILE] == "p"


# --- 3. the Local listing refuses when more than one managed row exists, whatever its status --


def _adapter(rows: list[dict[str, object]]) -> AigatewayConnections:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "object": "provider",
                            "id": "openrouter",
                            "display_name": "OpenRouter",
                            "auth_methods": ["api_key"],
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"connections": rows})

    client = httpx.AsyncClient(
        base_url="http://aigateway.test", transport=httpx.MockTransport(handler)
    )
    return AigatewayConnections(client)


def _managed_row(connection_id: str, status: str) -> dict[str, object]:
    return {
        "id": connection_id,
        "account_id": "00000000-0000-0000-0000-000000000099",
        "provider": "openrouter",
        "label": "screamingface",
        "status": status,
        "auth_type": "api_key",
        "account": None,
        "credential_locator": {"service": "must-not-leak", "account": "default"},
        "created_at": "2026-07-31T00:00:00Z",
        "last_used_at": None,
        "last_refreshed_at": None,
        "error_message": None,
        "is_duplicate": False,
    }


_ROW_A = "00000000-0000-0000-0000-000000000001"
_ROW_B = "00000000-0000-0000-0000-000000000002"


@pytest.mark.parametrize("other_status", ["pending", "expired", "error", "revoked"])
async def test_one_active_and_one_other_managed_row_of_any_status_is_a_conflict(
    other_status: str,
) -> None:
    """# INVARIANT (legacy, pinned): `_select` (`connections/aigateway.py:251-257`) counts every
    managed-label row for the provider regardless of `status`; two of them refuse with
    `ConnectionConflict` (409 at the REST edge). The gateway's default listing already hides
    revoked rows (`OAuthConnectionStore.list` excludes them), so in practice the rule reads
    "more than one NON-REVOKED managed row of any status" — but the adapter itself is
    status-blind, which is what a gateway-side reproduction (A3) must know.
    """
    adapter = _adapter([_managed_row(_ROW_A, "active"), _managed_row(_ROW_B, other_status)])

    with pytest.raises(ConnectionConflict):
        await adapter.list(Caller())


async def test_two_non_active_managed_rows_are_a_conflict_too() -> None:
    adapter = _adapter([_managed_row(_ROW_A, "pending"), _managed_row(_ROW_B, "error")])

    with pytest.raises(ConnectionConflict):
        await adapter.list(Caller())


async def test_a_single_non_active_managed_row_is_not_a_conflict() -> None:
    """Control: one managed row, whatever its status, is selected rather than refused."""
    adapter = _adapter([_managed_row(_ROW_A, "pending")])

    (connection,) = await adapter.list(Caller())

    assert connection.status == "pending"
