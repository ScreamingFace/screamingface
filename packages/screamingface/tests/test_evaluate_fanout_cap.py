"""The Candidate fan-out follows the Engine's per-caller cap (OME-1314, spec D3).

FEATURE: an Evaluation with 2+ Candidates runs as many at once as the SF Engine admits for the
caller (`GET /v1/limits`). A single Candidate reads no cap, and an older Engine keeps 8.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, cast

import httpx
import pytest
from test_client_run import _AsyncReplayTransport, _engine, _ReplayTransport
from test_evaluation_outcome import valid_outcome
from test_live_candidate_progress import candidate

import screamingface as sf
from screamingface._evaluation.runner import (
    _MAX_CANDIDATES_IN_FLIGHT,
    _caller_cap_async,
    _caller_cap_sync,
    _run_candidates_async,
    _run_candidates_sync,
)


class _PeakSync:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def run(self, selected: Any, on_event: object) -> Any:
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        return valid_outcome(selected.name)

    def cancel_active(self) -> None:
        pass


class _PeakAsync:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    async def run(self, selected: Any, on_event: object) -> Any:
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return valid_outcome(selected.name)

    async def cancel_active(self) -> None:
        pass


def _cands(n: int) -> tuple[Any, ...]:
    return tuple(candidate(f"c{i:02d}") for i in range(n))


def test_sync_fanout_follows_a_raised_cap() -> None:
    t = _PeakSync()
    result = _run_candidates_sync(cast(Any, t), _cands(30), None, cap=24)
    assert len(result) == 30
    assert 8 < t.peak <= 24


def test_sync_fanout_follows_a_small_cap() -> None:
    t = _PeakSync()
    _run_candidates_sync(cast(Any, t), _cands(30), None, cap=3)
    assert t.peak == 3


def test_sync_fanout_defaults_to_eight() -> None:
    t = _PeakSync()
    _run_candidates_sync(cast(Any, t), _cands(30), None)
    assert t.peak <= _MAX_CANDIDATES_IN_FLIGHT == 8
    assert t.peak > 3


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", [24, 3])
async def test_async_fanout_follows_the_cap(cap: int) -> None:
    t = _PeakAsync()
    await _run_candidates_async(cast(Any, t), _cands(30), None, cap=cap)
    assert t.peak == cap


@pytest.mark.asyncio
async def test_async_fanout_defaults_to_eight() -> None:
    t = _PeakAsync()
    await _run_candidates_async(cast(Any, t), _cands(30), None)
    assert t.peak == 8


def test_one_candidate_reads_no_cap() -> None:
    def loader() -> int:
        raise AssertionError("must not be called")

    assert _caller_cap_sync(_cands(1), loader) == 8
    assert _caller_cap_sync(_cands(5), None) == 8


def test_two_candidates_read_the_cap_once() -> None:
    calls: list[int] = []

    def loader() -> int:
        calls.append(1)
        return 24

    assert _caller_cap_sync(_cands(2), loader) == 24
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_one_candidate_reads_no_cap_async() -> None:
    async def loader() -> int:
        raise AssertionError("must not be called")

    assert await _caller_cap_async(_cands(1), loader) == 8
    assert await _caller_cap_async(_cands(5), None) == 8


@pytest.mark.asyncio
async def test_two_candidates_read_the_cap_once_async() -> None:
    calls: list[int] = []

    async def loader() -> int:
        calls.append(1)
        return 24

    assert await _caller_cap_async(_cands(2), loader) == 24
    assert len(calls) == 1


def _limits_handler(paths: list[str]) -> Any:
    def h(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/limits":
            return httpx.Response(200, json={"caller_inflight_cap": 24})
        return _engine(request)

    return h


def test_client_reads_the_cap_once_for_two_candidates() -> None:
    paths: list[str] = []
    with sf.Client(
        http_transport=httpx.MockTransport(_limits_handler(paths)),
        run_transport=_ReplayTransport(),
    ) as client:
        report = client.evaluate(
            [sf.Model("provider/opus", name="one"), sf.Model("provider/opus", name="two")],
            benchmark="draco",
            progress=False,
        )
    assert len(report.candidates) == 2
    assert paths.count("/v1/limits") == 1


def test_client_reads_no_cap_for_one_candidate() -> None:
    paths: list[str] = []
    with sf.Client(
        http_transport=httpx.MockTransport(_limits_handler(paths)),
        run_transport=_ReplayTransport(),
    ) as client:
        client.evaluate(sf.Model("provider/opus", name="one"), benchmark="draco", progress=False)
    assert paths.count("/v1/limits") == 0


@pytest.mark.asyncio
async def test_async_client_reads_the_cap_once_for_two_candidates() -> None:
    paths: list[str] = []
    client = sf.AsyncClient(
        http_transport=httpx.MockTransport(_limits_handler(paths)),
        run_transport=_AsyncReplayTransport(),
    )
    try:
        report = await client.evaluate(
            [sf.Model("provider/opus", name="one"), sf.Model("provider/opus", name="two")],
            benchmark="draco",
            progress=False,
        )
    finally:
        await client.aclose()
    assert len(report.candidates) == 2
    assert paths.count("/v1/limits") == 1


@pytest.mark.asyncio
async def test_async_client_reads_no_cap_for_one_candidate() -> None:
    paths: list[str] = []
    client = sf.AsyncClient(
        http_transport=httpx.MockTransport(_limits_handler(paths)),
        run_transport=_AsyncReplayTransport(),
    )
    try:
        await client.evaluate(
            sf.Model("provider/opus", name="one"), benchmark="draco", progress=False
        )
    finally:
        await client.aclose()
    assert paths.count("/v1/limits") == 0


def test_old_engine_without_limits_still_evaluates() -> None:
    def old_engine(request: httpx.Request) -> httpx.Response:
        return _engine(request)

    with sf.Client(
        http_transport=httpx.MockTransport(old_engine),
        run_transport=_ReplayTransport(),
    ) as client:
        report = client.evaluate(
            [sf.Model("provider/opus", name="one"), sf.Model("provider/opus", name="two")],
            benchmark="draco",
            progress=False,
        )
    assert len(report.candidates) == 2


class _PeakReplay(_ReplayTransport):
    """A replay transport that records how many Candidate runs overlap."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def run(self, candidate: Any, on_event: object) -> Any:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.05)
        with self._lock:
            self.active -= 1
        return super().run(candidate, on_event)


class _AsyncPeakReplay(_AsyncReplayTransport):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.peak = 0

    async def run(self, candidate: Any, on_event: object) -> Any:
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        return await super().run(candidate, on_event)


def _cap_engine(cap: int) -> Any:
    def h(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/limits":
            return httpx.Response(200, json={"caller_inflight_cap": cap})
        return _engine(request)

    return h


def _six_models() -> list[sf.Model]:
    return [sf.Model("provider/opus", name=f"m{i}") for i in range(6)]


def test_the_engine_cap_reaches_the_fanout_through_evaluate() -> None:
    """The whole path, not each piece: the cap the Client reads is the one the pool uses. A
    dropped `cap=` between `evaluate_sync` and the pool would fall back to 8 and fail here."""
    transport = _PeakReplay()
    with sf.Client(
        http_transport=httpx.MockTransport(_cap_engine(3)), run_transport=transport
    ) as client:
        report = client.evaluate(_six_models(), benchmark="draco", progress=False)
    assert len(report.candidates) == 6
    assert transport.peak == 3


@pytest.mark.asyncio
async def test_the_engine_cap_reaches_the_fanout_through_evaluate_async() -> None:
    transport = _AsyncPeakReplay()
    client = sf.AsyncClient(
        http_transport=httpx.MockTransport(_cap_engine(3)), run_transport=transport
    )
    try:
        report = await client.evaluate(_six_models(), benchmark="draco", progress=False)
    finally:
        await client.aclose()
    assert len(report.candidates) == 6
    assert transport.peak == 3
