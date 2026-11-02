"""`evaluate(..., use_cache=False)`: one run opted out of the request cache (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a researcher, I keep the cache on by default and turn it off for one evaluation when I
want fresh model calls.

Pinned here: every `evaluate` door takes `use_cache=True` by default; `False` is stamped on every
compiled Candidate, Recipes and raw URL4, sync and async, and `sf.evaluate` forwards it; the start
request carries `Cache-Control: no-cache` only for an opted-out run, beside the other start
headers; and the transport reads the flag from the Candidate it is given.
"""

from __future__ import annotations

import inspect
from typing import Any

import httpx
import pytest
from test_answer_seed_report import _CandidateRecordingTransport
from test_client_run import REPLAY_URL4, _AsyncReplayTransport, _engine, _ReplayTransport
from test_draco_vertical_slice import _AsyncFakeTransport
from test_draco_vertical_slice import _engine as _draco_engine

import screamingface as sf
from screamingface import _default_client
from screamingface._core.ports import _RunOutcome
from screamingface._engine import transport as transport_module
from screamingface._engine.trace import new_trace_context
from screamingface._engine.transport import Url4CloudTransport, _start_async, _start_sync
from screamingface._evaluation.model import _with_capture, _without_cache

TOKEN = "cap-token"
URL4 = "(@)!'go'"


def _http(seen: list[httpx.Request]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            202, headers={"Preference-Applied": "respond-async", "Location": "/runs/1"}
        )

    return httpx.Client(transport=httpx.MockTransport(handle), base_url="https://engine.test")


def _async_http(seen: list[httpx.Request]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            202, headers={"Preference-Applied": "respond-async", "Location": "/runs/1"}
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="https://engine.test")


# --- the start header -----------------------------------------------------------------------------


def test_an_opted_out_start_sends_cache_control_no_cache() -> None:
    # WHY the standard field: the Engine collapses `no-cache` to `use-cache: false` on every model
    # call of the run (cache_intent.py), and the report shows them as `bypass` / `opted_out`.
    seen: list[httpx.Request] = []

    _start_sync(_http(seen), TOKEN, URL4, answer_seed=7, capture=True, use_cache=False)

    assert seen[0].headers["Cache-Control"] == "no-cache"
    assert seen[0].headers["X-Capture"] == "true"
    assert seen[0].headers["X-Answer-Seed"] == "7"


def test_a_default_start_sends_no_cache_control() -> None:
    # The Engine's default is to use the cache, so saying nothing is saying yes.
    seen: list[httpx.Request] = []

    _start_sync(_http(seen), TOKEN, URL4)
    _start_sync(_http(seen), TOKEN, URL4, use_cache=True)

    assert all("Cache-Control" not in request.headers for request in seen)


@pytest.mark.asyncio
async def test_the_async_start_sends_it_only_when_opted_out() -> None:
    seen: list[httpx.Request] = []

    async with _async_http(seen) as http:
        await _start_async(http, TOKEN, URL4, use_cache=False)
        await _start_async(http, TOKEN, URL4)

    assert seen[0].headers["Cache-Control"] == "no-cache"
    assert "Cache-Control" not in seen[1].headers


def test_the_transport_reads_use_cache_from_the_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    from _isolation_engine import candidate

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(transport_module, "_start_sync", lambda *_a, **kw: calls.append(kw))
    transport = Url4CloudTransport("https://engine.test")
    try:
        transport._start_run(TOKEN, _without_cache(candidate("plain")), new_trace_context(), None)
        transport._start_run(TOKEN, candidate("plain"), new_trace_context(), None)
    finally:
        transport.close()

    assert [call["use_cache"] for call in calls] == [False, True]


# --- the Candidate --------------------------------------------------------------------------------


def test_a_compiled_candidate_uses_the_cache_by_default_and_the_stamp_keeps_the_rest() -> None:
    from _isolation_engine import candidate

    plain = _with_capture(candidate("plain"))
    opted_out = _without_cache(plain)

    assert plain.use_cache is True
    assert opted_out.use_cache is False
    assert (opted_out.capture, opted_out.url4) == (plain.capture, plain.url4)


# --- the evaluate doors ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", [sf.Client.evaluate, sf.AsyncClient.evaluate, sf.evaluate])
def test_every_evaluate_door_takes_use_cache_on_by_default(target: object) -> None:
    parameters = inspect.signature(target).parameters  # type: ignore[arg-type]

    assert parameters["use_cache"].default is True


@pytest.mark.parametrize("use_cache", [True, False])
def test_the_url4_path_stamps_use_cache(use_cache: bool) -> None:
    transport = _ReplayTransport()
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    ) as client:
        client.evaluate(REPLAY_URL4, progress=False, capture=False, use_cache=use_cache)

    assert transport.candidate is not None
    assert transport.candidate.use_cache is use_cache


@pytest.mark.asyncio
async def test_the_async_url4_path_stamps_use_cache() -> None:
    transport = _AsyncReplayTransport()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    )

    await client.evaluate(REPLAY_URL4, progress=False, capture=False, use_cache=False)
    await client.aclose()

    assert transport.candidate is not None
    assert transport.candidate.use_cache is False


def test_the_recipe_path_stamps_use_cache_on_every_compiled_candidate() -> None:
    transport = _CandidateRecordingTransport()
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_draco_engine),
        run_transport=transport,
    ) as client:
        for use_cache in (True, False):
            client.evaluate(
                sf.Model("anthropic/claude-haiku-4-5", name="haiku"),
                benchmark="draco",
                limit=1,
                capture=False,
                use_cache=use_cache,
            )

    assert [c.use_cache for c in transport.candidates] == [True, False]


class _AsyncCandidateRecording(_AsyncFakeTransport):
    def __init__(self) -> None:
        super().__init__()
        self.candidates: list[Any] = []

    async def run(self, candidate: Any, on_event: object) -> _RunOutcome:
        self.candidates.append(candidate)
        return await super().run(candidate, on_event)


@pytest.mark.asyncio
async def test_the_async_recipe_path_stamps_use_cache() -> None:
    transport = _AsyncCandidateRecording()
    async with sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_draco_engine),
        run_transport=transport,
    ) as client:
        await client.evaluate(
            sf.Model("anthropic/claude-haiku-4-5", name="haiku"),
            benchmark="draco",
            limit=1,
            capture=False,
            use_cache=False,
        )

    assert [c.use_cache for c in transport.candidates] == [False]


@pytest.mark.parametrize("bad", [None, 0, 1, "false"])
def test_use_cache_must_be_a_bool(bad: object) -> None:
    with (
        sf.Client(
            engine_url="https://engine.example",
            http_transport=httpx.MockTransport(_engine),
            run_transport=_ReplayTransport(),
        ) as client,
        pytest.raises(TypeError, match="use_cache"),
    ):
        client.evaluate(REPLAY_URL4, progress=False, use_cache=bad)  # type: ignore[arg-type]


class _RecordingDefaultClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def evaluate(self, *_args: object, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "report"


def test_module_level_evaluate_forwards_use_cache_on_both_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _RecordingDefaultClient()
    monkeypatch.setattr(_default_client, "default_client", lambda: fake)

    sf.evaluate(REPLAY_URL4, use_cache=False)
    sf.evaluate(sf.Model("provider/opus"), benchmark="draco", use_cache=False)
    sf.evaluate(REPLAY_URL4)

    assert [kwargs["use_cache"] for kwargs in fake.calls] == [False, False, True]
