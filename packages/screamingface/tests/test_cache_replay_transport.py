"""The run start carries `X-Cache-Replay` and checks the Engine's echo (E14 B5, K3, R24).

FEATURE: OME-1307 — a replay names the cache version it must answer from in a start header, as the
answer seed does. An Engine that honours it echoes the label on the start response. An older Engine
ignores the header and would run the Candidate as a paid run, so the Client stops a run whose start
carries no matching echo, before it spends anything more.
STORY: as someone who reproduces a score, a run that does not replay from the cache is stopped, not
paid for.
"""

from __future__ import annotations

import httpx
import pytest
from _isolation_engine import RunPlan, candidate, isolation_engine, url4_of

from screamingface._engine.transport import (
    AsyncUrl4CloudTransport,
    Url4CloudTransport,
    _start_async,
    _start_sync,
)
from screamingface._evaluation.model import _with_cache_replay
from screamingface.errors import ExecutionError

TOKEN = "cap-token"
URL4 = "(@)!'go'"
LABEL = "cr-0123456789ab"
OTHER = "cr-ba9876543210"


def _http(seen: list[httpx.Request], *, echo: str | None = LABEL) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        headers = {"Preference-Applied": "respond-async", "Location": "/runs/1"}
        if echo is not None:
            headers["X-Cache-Replay"] = echo
        return httpx.Response(202, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handle), base_url="https://engine.test")


def _async_http(seen: list[httpx.Request], *, echo: str | None = LABEL) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        headers = {"Preference-Applied": "respond-async", "Location": "/runs/1"}
        if echo is not None:
            headers["X-Cache-Replay"] = echo
        return httpx.Response(202, headers=headers)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="https://engine.test")


# --- the header --------------------------------------------------------------------------------


def test_a_replay_start_sends_the_label_beside_the_seed() -> None:
    seen: list[httpx.Request] = []

    _start_sync(_http(seen), TOKEN, URL4, answer_seed=7, cache_replay=LABEL)

    assert seen[0].headers["X-Cache-Replay"] == LABEL
    assert seen[0].headers["X-Answer-Seed"] == "7"


def test_a_normal_start_sends_no_replay_header_and_checks_no_echo() -> None:
    seen: list[httpx.Request] = []

    _start_sync(_http(seen, echo=None), TOKEN, URL4)

    assert "X-Cache-Replay" not in seen[0].headers


@pytest.mark.asyncio
async def test_the_async_start_sends_the_header_only_for_a_replay() -> None:
    seen: list[httpx.Request] = []

    async with _async_http(seen) as http:
        await _start_async(http, TOKEN, URL4, cache_replay=LABEL)
    async with _async_http(seen, echo=None) as http:
        await _start_async(http, TOKEN, URL4)

    assert seen[0].headers["X-Cache-Replay"] == LABEL
    assert "X-Cache-Replay" not in seen[1].headers


# --- the echo (R24) ----------------------------------------------------------------------------


@pytest.mark.parametrize("echo", [None, OTHER, ""])
def test_a_missing_or_mismatched_echo_is_replay_unsupported(echo: str | None) -> None:
    with pytest.raises(ExecutionError) as raised:
        _start_sync(_http([], echo=echo), TOKEN, URL4, cache_replay=LABEL)

    assert raised.value.code == "replay_unsupported"


def test_a_matching_echo_lets_the_run_start() -> None:
    _start_sync(_http([], echo=LABEL), TOKEN, URL4, cache_replay=LABEL)


@pytest.mark.asyncio
@pytest.mark.parametrize("echo", [None, OTHER])
async def test_the_async_start_checks_the_echo_too(echo: str | None) -> None:
    async with _async_http([], echo=echo) as http:
        with pytest.raises(ExecutionError) as raised:
            await _start_async(http, TOKEN, URL4, cache_replay=LABEL)

    assert raised.value.code == "replay_unsupported"


# --- the stop: this run only, over the existing path -------------------------------------------


def test_the_transport_stops_a_replay_run_that_was_not_acknowledged() -> None:
    plans = {url4_of("replay"): RunPlan()}
    with isolation_engine(plans) as engine:
        transport = Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            with pytest.raises(ExecutionError) as raised:
                transport.run(_with_cache_replay(candidate("replay"), LABEL), None)
        finally:
            transport.close()

    assert raised.value.code == "replay_unsupported"
    # The stub never echoes, so it is the older Engine: the run it took is stopped, by its own
    # capability.
    assert engine.state.deleted == [engine.state.capability_of(url4_of("replay"))]


@pytest.mark.asyncio
async def test_the_async_transport_stops_a_replay_run_that_was_not_acknowledged() -> None:
    plans = {url4_of("replay"): RunPlan()}
    with isolation_engine(plans) as engine:
        transport = AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            with pytest.raises(ExecutionError) as raised:
                await transport.run(_with_cache_replay(candidate("replay"), LABEL), None)
        finally:
            await transport.close()

    assert raised.value.code == "replay_unsupported"
    assert engine.state.deleted == [engine.state.capability_of(url4_of("replay"))]


def test_a_normal_run_is_never_stopped_for_a_missing_echo() -> None:
    plans = {url4_of("normal"): RunPlan()}
    with isolation_engine(plans) as engine:
        transport = Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            transport.run(candidate("normal"), None)
        finally:
            transport.close()

    assert engine.state.deleted == []
