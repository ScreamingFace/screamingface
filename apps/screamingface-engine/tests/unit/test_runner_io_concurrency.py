"""The OME-908 run-admission plumbing: env contract, executor call shape, local wiring.

The gate's own scheduling invariants live in `test_fair_share_gate.py`. What this file
pins is everything AROUND the gate: the env name and its total reader, the exact
`url4_run` call shape for each mode (a kwarg omitted vs. a value vs. an explicit
opt-out), the local app's composition (one shared gate, closed after the runner), and —
the point of the whole feature — two concurrent runs through a real executor pair
interleaving on one mock gateway.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from screamingface_engine import job_env
from screamingface_engine.config import Settings
from screamingface_engine.local import create_local_app
from screamingface_engine.runner import executor as executor_module
from screamingface_engine.runner.fair_share import FairShareGate
from screamingface_engine.runner.main import build_executor
from screamingface_engine.world_config import AigatewaySection, ModelSpec, WorldConfig

MODEL = "anthropic/claude-haiku-4-5"


def _declared() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://gateway.test",
            default_model=MODEL,
            models=(ModelSpec(id=MODEL),),
        )
    )


# --- the env contract ---------------------------------------------------------------------------


def test_the_io_concurrency_env_name_is_per_run() -> None:
    assert job_env.IO_CONCURRENCY in job_env.WRITTEN_BY_APP
    assert job_env.IO_CONCURRENCY not in job_env.SECRET
    assert job_env.IO_CONCURRENCY not in job_env.DEPLOY_TIME


def test_the_env_reader_is_total_and_fails_safe() -> None:
    """Absent, malformed, or sub-1 values all resolve to the historic default path."""
    reader = job_env.io_concurrency_from_env
    assert reader({}) is None
    assert reader({job_env.IO_CONCURRENCY: "16"}) == 16
    assert reader({job_env.IO_CONCURRENCY: " 8 "}) == 8
    assert reader({job_env.IO_CONCURRENCY: "0"}) is None
    assert reader({job_env.IO_CONCURRENCY: "-4"}) is None
    assert reader({job_env.IO_CONCURRENCY: "lots"}) is None


def test_the_settings_reject_a_non_positive_budget() -> None:
    with pytest.raises(ValueError):
        Settings(runner_io_concurrency=0)
    with pytest.raises(ValueError):
        Settings(local_io_capacity=0)


# --- the executor call shape ---------------------------------------------------------------------


class _RecordingRun:
    """Stands in for `url4_run`, capturing the kwargs each execute passed."""

    def __init__(self, real_run: Any) -> None:
        self.real = real_run
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.real(*args, **kwargs)


class _CannedGateway:
    """Serves every completions request instantly — the call-shape tests only record kwargs."""

    def _body(self) -> dict[str, Any]:
        return {
            "id": "chatcmpl-x",
            "object": "chat.completion",
            "created": 0,
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    def client(self) -> httpx.AsyncClient:
        gw = self

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=gw._body())

        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://gateway.test"
        )


async def _drive(env: dict[str, str], *, config: WorldConfig | None = None) -> None:
    gw = _CannedGateway()
    async with gw.client() as client:
        executor = build_executor(env, config or _declared(), client=client)
        async for _ in executor.execute(f"/{MODEL}('hi')!'go'"):
            pass


@pytest.mark.asyncio
async def test_a_clean_env_omits_the_concurrency_kwarg_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invariant 5: an unconfigured run is byte-identical to a pre-OME-908 one."""
    recording = _RecordingRun(executor_module.url4_run)
    monkeypatch.setattr(executor_module, "url4_run", recording)

    await _drive({job_env.TOPIC: "t-clean"})

    assert len(recording.calls) == 1
    assert "concurrency" not in recording.calls[0]


@pytest.mark.asyncio
async def test_a_stated_budget_reaches_url4_run(monkeypatch: pytest.MonkeyPatch) -> None:
    recording = _RecordingRun(executor_module.url4_run)
    monkeypatch.setattr(executor_module, "url4_run", recording)

    await _drive({job_env.TOPIC: "t-budget", job_env.IO_CONCURRENCY: "16"})

    assert recording.calls[0].get("concurrency") == 16


@pytest.mark.asyncio
async def test_a_gate_bound_run_opts_out_of_the_per_run_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate mode passes `concurrency=None` EXPLICITLY — the gate replaces the cap."""
    recording = _RecordingRun(executor_module.url4_run)
    monkeypatch.setattr(executor_module, "url4_run", recording)
    gate = FairShareGate(4)
    gw = _CannedGateway()

    async with gw.client() as client:
        executor = build_executor(
            {
                job_env.TOPIC: "t-gate",
                job_env.IO_CONCURRENCY: "16",
            },  # env must NOT win over the gate
            _declared(),
            client=client,
            io_gate=gate,
        )
        async for _ in executor.execute(f"/{MODEL}('hi')!'go'"):
            pass

    assert recording.calls[0].get("concurrency") is None


# --- the local composition ------------------------------------------------------------------------


def test_local_mode_builds_one_shared_gate_and_closes_it_after_the_runner() -> None:
    app: FastAPI = create_local_app(Settings(), env={})

    gate = app.state.fair_share_gate
    assert isinstance(gate, FairShareGate)
    assert gate.capacity == Settings().local_io_capacity

    # Shutdown order is the correctness property: runs release their permits into a live gate.
    shutdown_names = [f.__qualname__ for f in app.router.on_shutdown]
    assert shutdown_names.index("InProcessJobRunner.aclose") < shutdown_names.index(
        "FairShareGate.aclose"
    )


def test_local_mode_pops_an_ambient_budget_from_a_runs_env() -> None:
    """Local's bound is the gate, never a static env — even one exported in the shell."""
    from screamingface_engine.adapters.inprocess import InProcessJobRunner
    from screamingface_engine.testing import InMemoryEventStream

    async def _factory(env: dict[str, str]) -> Any:
        raise NotImplementedError

    runner = InProcessJobRunner(
        InMemoryEventStream(),
        _factory,  # type: ignore[arg-type]
        base_env={job_env.IO_CONCURRENCY: "3"},
    )

    env = runner._env("topic-x", "'hi'!'go'", 60, None, None)

    assert job_env.IO_CONCURRENCY not in env


# --- the point of the feature: two runs interleave on one gateway ---------------------------------


class _ParkingGateway:
    """A mock aigateway whose completions each park until the test releases them."""

    def __init__(self) -> None:
        self.started: list[asyncio.Event] = []
        self.active = 0
        self.peak_active = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self._body())

    def _body(self) -> dict[str, Any]:
        # The response content is irrelevant to admission; it only has to parse.
        return {
            "id": "chatcmpl-x",
            "object": "chat.completion",
            "created": 0,
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    def client(self) -> httpx.AsyncClient:
        transport = _ParkingTransport(self)
        return httpx.AsyncClient(transport=transport, base_url="http://gateway.test")


class _ParkingTransport(httpx.AsyncBaseTransport):
    """Parks each request on its own event; the test releases them one by one."""

    def __init__(self, gw: _ParkingGateway) -> None:
        self._gw = gw

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        park = asyncio.Event()
        self._gw.started.append(park)
        self._gw.active += 1
        self._gw.peak_active = max(self._gw.peak_active, self._gw.active)
        try:
            await park.wait()
        finally:
            self._gw.active -= 1
        return httpx.Response(200, json=self._gw._body())


_SOURCES = 6
_FANOUT = "(" + ", ".join(f"/{MODEL}('s{i}')!'s{i}'" for i in range(_SOURCES)) + ")!'go'"


def _drive_until_parked(executor: Any) -> asyncio.Task[str]:
    return asyncio.get_running_loop().create_task(_collect(executor))


async def _collect(executor: Any) -> str:
    frames: list[Any] = []
    async for frame in executor.execute(_FANOUT):
        frames.append(frame)
    return "done"


@pytest.mark.asyncio
async def test_two_concurrent_runs_interleave_through_one_shared_gate() -> None:
    """The OME-908 invariant, end to end: a freed permit serves the OTHER run first."""
    gate = FairShareGate(4)
    gw = _ParkingGateway()

    async with gw.client() as client:
        run_a = build_executor({job_env.TOPIC: "run-a"}, _declared(), client=client, io_gate=gate)
        run_b = build_executor({job_env.TOPIC: "run-b"}, _declared(), client=client, io_gate=gate)

        task_a = _drive_until_parked(run_a)
        await _until(lambda: _in_flight(gate, "run-a") == 4)
        # A alone: it holds the whole gate (work-conserving — the solo invariant).
        assert _share(gate, "run-a").waiting == _SOURCES - 4

        task_b = _drive_until_parked(run_b)
        await _until(lambda: _waiting(gate, "run-b") == _SOURCES)
        # B queues behind A's holdings

        # One of A's fetches completes. The freed permit MUST serve B, not A's own queue
        # — this is exactly the starvation the feature exists to prevent.
        gw.started[0].set()
        await _until(lambda: _in_flight(gate, "run-b") == 1)
        assert _share(gate, "run-a").in_flight == 3

        # Released permits let queued fetches start — which park on FRESH events — so
        # draining is a loop, not one pass: keep releasing until both runs complete.
        for _ in range(1000):
            if task_a.done() and task_b.done():
                break
            for park in gw.started:
                park.set()
            await asyncio.sleep(0)
        await asyncio.gather(task_a, task_b)

    snapshot = gate.snapshot()
    assert snapshot.in_flight == 0
    assert snapshot.runs == ()
    assert gw.peak_active <= 4  # the gate, not the gateway, was the ceiling


def _share(gate: FairShareGate, run: str) -> Any:
    return next(entry for entry in gate.snapshot().runs if entry.run == run)


def _in_flight(gate: FairShareGate, run: str) -> int:
    """Total on absence (0): poll conditions must tolerate a run not yet in the books."""
    entry = next((e for e in gate.snapshot().runs if e.run == run), None)
    return 0 if entry is None else entry.in_flight


def _waiting(gate: FairShareGate, run: str) -> int:
    entry = next((e for e in gate.snapshot().runs if e.run == run), None)
    return 0 if entry is None else entry.waiting


async def _settle(rounds: int = 4) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


async def _until(predicate: Any, limit: int = 1000) -> None:
    """Step the loop until `predicate()` holds — settle-with-a-condition, no wall clock."""
    for _ in range(limit):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never held")


# --- the metrics surface --------------------------------------------------


def test_the_gate_is_scrapable_through_the_app_registry() -> None:
    from prometheus_client import generate_latest

    from screamingface_engine.metrics import build_metrics, register_fair_share_metrics

    gate = FairShareGate(2)
    metrics = build_metrics()
    register_fair_share_metrics(metrics, lambda: gate)

    body = generate_latest(metrics.registry).decode()
    for name in (
        "screamingface_engine_fair_share_granted_total",
        "screamingface_engine_fair_share_in_flight",
        "screamingface_engine_fair_share_waiting",
        "screamingface_engine_fair_share_active_runs",
    ):
        assert name in body
