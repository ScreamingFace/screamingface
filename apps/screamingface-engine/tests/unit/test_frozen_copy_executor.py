"""E14 F-B3 — the executor opens and seals the copy, and the run summary states the mode.

FEATURE: OME-1307 (design §5.2, §5.3). A capture run opens a frozen copy before its first step and
seals it after the last one (also when the run failed, never when it was cancelled: a cancelled run
is partial and stays open). The run summary and the run's cache summary log line always carry
`capture.frozen_copy_id`, `capture.status` and `capture.partial.*` for a capture run, and
`capture.replay` for a replay run, even when the run made no model call.
STORY: as a researcher who submits a score, the run's own summary names the copy that holds it.

A separate module (append-only gate).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from frozen_copy_support import (
    CHAT,
    COPY,
    EXPRESSION,
    MODEL,
    OPEN,
    REPLAY_CHAT,
    SEAL,
    TOOL_LOOKUP,
    TOOL_RESULTS,
    Gateway,
    Tavily,
    capture_scope,
    chat,
    error,
    replay_scope,
    stored,
    tool_call,
)

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.runner.summary import RunSummary
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.core.errors import ResolutionError
from url4.io.static import StaticIOLayer
from url4.streaming.interfaces import Traced
from url4.streaming.protocol import LogData

_EMPTY = "'hello'!go"


async def _run(
    gateway: Gateway,
    scope: RequestScope,
    expression: str = EXPRESSION,
    *,
    tavily: Tavily | None = None,
) -> tuple[RunSummary | None, list[LogData], BaseException | None]:
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL, web_search=True),), default_model=MODEL)
    logs: list[LogData] = []
    failure: BaseException | None = None
    tavily_client = tavily.client() if tavily is not None else None
    async with gateway.client() as client:
        world = await build_aigateway_world(
            cfg,
            client=client,
            tavily_api_key="tvly-test-key" if tavily is not None else None,  # noqa: S106
            tavily_client=tavily_client,
        )
        executor = Url4Executor(world.node)
        with request_scope(scope):
            try:
                async for step in executor.execute(expression):
                    if isinstance(step, Traced) and isinstance(step.payload, LogData):
                        logs.append(step.payload)
            except ResolutionError as exc:
                failure = exc
    if tavily_client is not None:
        await tavily_client.aclose()
    return executor.last_summary(), logs, failure


def _attributes(summary: RunSummary | None) -> dict[str, Any]:
    assert summary is not None and summary.cache_attributes is not None
    return dict(summary.cache_attributes)


def _capture_attributes(summary: RunSummary | None) -> dict[str, Any]:
    return {k: v for k, v in _attributes(summary).items() if k.startswith("capture.")}


def _lines(logs: list[LogData]) -> list[LogData]:
    return [log for log in logs if "gateway response cache" in log.body]


# ── TDD 11: open and seal ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_and_seal_called_once_per_run_open_before_the_steps_seal_after() -> None:
    gateway = Gateway([tool_call("web_search", {"query": "q"}, stored()), chat("done", stored())])

    summary, _logs, failure = await _run(gateway, capture_scope(), tavily=Tavily())

    assert failure is None
    paths = gateway.paths()
    assert paths.count(OPEN) == 1
    assert paths.count(SEAL) == 1
    assert paths[0] == OPEN
    assert paths[-1] == SEAL
    assert CHAT in paths and TOOL_RESULTS in paths
    # Every chat call names the copy the OPEN answered with.
    assert {h["X-AIGW-Frozen-Copy"] for h, _b in gateway.calls(CHAT)} == {COPY}
    assert _capture_attributes(summary) == {
        "capture.frozen_copy_id": COPY,
        "capture.status": "complete",
    }


@pytest.mark.asyncio
async def test_open_and_seal_carry_the_runs_identity_headers() -> None:
    gateway = Gateway([chat("done", stored())])
    scope = capture_scope(identity_headers={"X-User-Email": "a@b.test"})

    await _run(gateway, scope)

    for path in (OPEN, SEAL):
        ((headers, _body),) = gateway.calls(path)
        assert headers["X-User-Email"] == "a@b.test"


@pytest.mark.asyncio
async def test_seal_on_failed_run() -> None:
    # The one model call fails and nothing catches it, so the whole run fails.
    gateway = Gateway([error(400, "bad_request")])

    summary, _logs, failure = await _run(gateway, capture_scope())

    assert isinstance(failure, ResolutionError)
    assert summary is not None and summary.outcome == "failed"
    assert gateway.paths().count(OPEN) == 1
    assert gateway.paths().count(SEAL) == 1


@pytest.mark.asyncio
async def test_a_cancelled_run_is_never_sealed() -> None:
    chat_started = asyncio.Event()
    gateway = Gateway()
    calls: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == CHAT:
            chat_started.set()
            await asyncio.sleep(3600)
        return gateway.handle(request)

    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(world.node)

        async def consume() -> None:
            with request_scope(capture_scope()):
                async for _ in executor.execute(EXPRESSION):
                    pass

        task = asyncio.ensure_future(consume())
        await asyncio.wait_for(chat_started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert calls == [OPEN, CHAT]
    summary = executor.last_summary()
    assert summary is not None and summary.outcome == "stopped"


@pytest.mark.asyncio
async def test_a_normal_and_a_replay_run_never_open_or_seal() -> None:
    normal = Gateway([chat()])
    replay = Gateway(replay_steps=[chat()])

    await _run(normal, RequestScope(origin="run"))
    await _run(replay, replay_scope())

    assert OPEN not in normal.paths() and SEAL not in normal.paths()
    assert replay.paths() == [REPLAY_CHAT]


# ── a failed open or seal makes the run partial, and the run goes on ───────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(201, json={"status": "open"}),
        httpx.Response(201, json={"id": "../../etc"}),
        httpx.Response(201, content=b"not json"),
        httpx.ConnectError("down"),
    ],
    ids=["http-500", "no-id", "id-not-a-uuid", "not-json", "transport"],
)
async def test_a_failed_open_runs_uncaptured_and_is_partial_open(
    response: httpx.Response | BaseException,
) -> None:
    gateway = Gateway([chat("done")], open_response=response)

    summary, _logs, failure = await _run(gateway, capture_scope())

    assert failure is None
    assert _capture_attributes(summary) == {
        "capture.status": "partial",
        "capture.partial.open": 1,
    }
    # No copy, so no copy header, no tool-result post, no seal.
    ((headers, _body),) = gateway.calls(CHAT)
    assert "X-AIGW-Frozen-Copy" not in headers
    assert SEAL not in gateway.paths()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, json={"id": COPY, "status": "open"}),
        httpx.Response(200, content=b"not json"),
        httpx.ConnectError("down"),
    ],
    ids=["http-500", "not-sealed", "not-json", "transport"],
)
async def test_a_failed_seal_is_partial_seal(response: httpx.Response | BaseException) -> None:
    gateway = Gateway([chat("done", stored())], seal_response=response)

    summary, _logs, failure = await _run(gateway, capture_scope())

    assert failure is None
    assert _capture_attributes(summary) == {
        "capture.frozen_copy_id": COPY,
        "capture.status": "partial",
        "capture.partial.seal": 1,
    }


@pytest.mark.asyncio
async def test_the_gateway_not_confirming_a_call_makes_the_run_partial() -> None:
    gateway = Gateway([chat("done")])  # an older gateway: no X-AIGW-Capture header

    summary, _logs, _failure = await _run(gateway, capture_scope())

    assert _capture_attributes(summary) == {
        "capture.frozen_copy_id": COPY,
        "capture.status": "partial",
        "capture.partial.missing": 1,
    }


# ── TDD 10: the summary is always written for capture and replay runs ──────────────────────


@pytest.mark.asyncio
async def test_summary_always_written_for_capture_and_replay_runs() -> None:
    capture_summary, capture_logs, _ = await _run(Gateway(), capture_scope(), _EMPTY)
    replay_summary, replay_logs, _ = await _run(Gateway(), replay_scope(), _EMPTY)

    # A capture run that made no model call still states its copy and a complete status.
    assert _capture_attributes(capture_summary) == {
        "capture.frozen_copy_id": COPY,
        "capture.status": "complete",
    }
    (capture_line,) = _lines(capture_logs)
    assert dict(capture_line.attributes) == _attributes(capture_summary)
    # A replay run that made no model call still proves it honoured the header.
    assert _capture_attributes(replay_summary) == {"capture.replay": COPY}
    (replay_line,) = _lines(replay_logs)
    assert dict(replay_line.attributes) == _attributes(replay_summary)


@pytest.mark.asyncio
async def test_a_capture_run_with_an_unreachable_gateway_still_writes_its_summary() -> None:
    # No gateway client at all (a bare io layer): the copy cannot open, the run is partial.
    executor = Url4Executor(StaticIOLayer(fetch_map={"https://a": "A"}))
    logs: list[LogData] = []
    with request_scope(capture_scope()):
        async for step in executor.execute("https://a!go"):
            if isinstance(step, Traced) and isinstance(step.payload, LogData):
                logs.append(step.payload)

    assert _capture_attributes(executor.last_summary()) == {
        "capture.status": "partial",
        "capture.partial.open": 1,
    }
    (line,) = _lines(logs)
    assert line.attributes["capture.status"] == "partial"


@pytest.mark.asyncio
async def test_a_replay_that_failed_every_call_still_publishes_capture_replay() -> None:
    """A replay run that SUCCEEDS although its one model call fails, as a benchmark case that
    fails does: the call is made inside a route that catches the failure."""
    from url4.dag import run as url4_run

    gateway = Gateway(
        replay_steps=[httpx.Response(404, json={"detail": {"code": "frozen_copy_miss"}})]
    )
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    logs: list[LogData] = []
    async with gateway.client() as client:
        world = await build_aigateway_world(cfg, client=client)

        async def case(_context: str, _intent: str) -> str:
            try:
                await url4_run(EXPRESSION, io=world.node)
            except ResolutionError as exc:
                return f"case failed: {exc.code}"
            return "case passed"

        executor = Url4Executor(StaticIOLayer(routes={"/case": case}))
        with request_scope(replay_scope()):
            async for step in executor.execute("/case(x)!go"):
                if isinstance(step, Traced) and isinstance(step.payload, LogData):
                    logs.append(step.payload)

    assert _capture_attributes(executor.last_summary()) == {"capture.replay": COPY}
    (line,) = _lines(logs)
    assert line.attributes["capture.replay"] == COPY


@pytest.mark.asyncio
async def test_a_replay_run_keeps_the_cache_counters_beside_its_attribute() -> None:
    summary, _logs, failure = await _run(Gateway(replay_steps=[chat("done")]), replay_scope())

    assert failure is None
    attributes = _attributes(summary)
    assert attributes["capture.replay"] == COPY
    assert attributes["cache.hits"] == 1  # a replayed answer is accounted as a hit
    assert not [k for k in attributes if k.startswith("capture.partial.") or k == "capture.status"]


@pytest.mark.asyncio
async def test_a_replay_run_reads_its_tool_results_from_the_copy_end_to_end() -> None:
    gateway = Gateway(
        replay_steps=[tool_call("web_search", {"query": "q"}), chat("done")],
        tool_lookup=lambda _r: httpx.Response(200, json={"result": "r"}),
    )

    summary, _logs, failure = await _run(gateway, replay_scope())

    assert failure is None
    assert set(gateway.paths()) == {REPLAY_CHAT, TOOL_LOOKUP}
    assert _attributes(summary)["capture.replay"] == COPY


@pytest.mark.asyncio
async def test_two_concurrent_runs_keep_their_own_tally() -> None:
    complete, partial = await asyncio.gather(
        _run(Gateway([chat("a", stored())]), capture_scope()),
        _run(Gateway([chat("a")]), capture_scope()),
    )

    assert _attributes(complete[0])["capture.status"] == "complete"
    assert _attributes(partial[0])["capture.status"] == "partial"
