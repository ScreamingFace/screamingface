"""`evaluate(replay=...)` asks for a grant, then runs (E14, OME-1307, RP-16 to RP-19).

FEATURE: OME-1307 (E14) reproducible submissions. The SDK half of contract C6 (the grant request),
C1 (the grant rides the engine start request) and the `replay` block of C4. One
`httpx.MockTransport` fakes the Scoreboard and one fakes the engine (D7 X-20): no network, no
`apps/` import.

INVARIANT: the grant request is the FIRST call of a pinned run. A pin that does not resolve spends
nothing, and a Scoreboard that cannot answer never falls back to a plain run (RP-E5).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from datetime import UTC, datetime
from inspect import signature
from typing import Any, Literal
from uuid import UUID

import httpx
import pytest
from test_answer_seed_report import _seed_capable_engine
from test_draco_vertical_slice import _AsyncFakeTransport, _FakeTransport
from test_draco_vertical_slice import _engine as _draco_engine
from test_engine_contract import URL4 as CANDIDATE_URL4
from test_submit_cache_version import (
    SCORE_ID as SUBMITTED_SCORE_ID,
)
from test_submit_cache_version import (
    TRACE_ID,
    _candidate,
    _score_response,
)

import screamingface as sf
from screamingface import _default_client
from screamingface._core.ports import _ReplayBinding, _ReplayCounts, _RunOutcome
from screamingface._engine.transport import _start_async, _start_sync
from screamingface._evaluation.model import (
    _compiled_candidate,
    _compiled_operation,
    _with_answer_seed,
    _with_replay,
)
from screamingface._scoreboard.replay_pin import parse_replay_pin

SCOREBOARD_URL = "https://scoreboard.example"
ENGINE_URL = "https://engine.example"
GRANT = "eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0.eyJzdWIiOiJhIn0.c2ln"
RESULT_ID = UUID("3f0c5d0e-6f0b-4d75-a1f1-0c6f0b7d2a10")
SCORE_ID = UUID("af95892d-7438-4ac3-9b47-5e06f62c8251")
VERSION_ID = UUID("9b2c5f52-3c0a-4a37-8a54-6c3f1c1c5b11")
EXPIRES_AT = "2026-09-30T00:00:00Z"
PIN = f"result:{RESULT_ID}"
RECIPE = sf.Model("anthropic/claude-haiku-4-5", name="haiku")
OTHER_RECIPE = sf.Model("anthropic/claude-haiku-4-5", name="other")
TOKEN = "cap-token"
URL4 = "(@)!'go'"

Reply = httpx.Response | Exception


def _grant_body(**over: object) -> dict[str, object]:
    return {
        "grant": GRANT,
        "result_id": str(RESULT_ID),
        "score_id": str(SCORE_ID),
        "cache_version_id": str(VERSION_ID),
        "expires_at": EXPIRES_AT,
        **over,
    }


def _grant_response(**over: object) -> httpx.Response:
    return httpx.Response(200, json=_grant_body(**over))


class _Scoreboard:
    """A scripted Scoreboard that records every request and the order of its calls."""

    def __init__(self, reply: Reply | None = None, events: list[str] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._reply: Reply = _grant_response() if reply is None else reply
        self._events = events

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._events is not None:
            self._events.append("grant")
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


class _Engine:
    """The draco engine fake, counting every call so a test can assert none was made."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return _draco_engine(request)


class _RecordingTransport(_FakeTransport):
    """`_FakeTransport` that records the Candidates, the order of its runs and injects counters."""

    def __init__(
        self,
        events: list[str] | None = None,
        counts: _ReplayCounts | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.candidates: list[Any] = []
        self._events = events
        self._counts = counts
        self._error = error

    def run(self, candidate: Any, on_event: object) -> _RunOutcome:
        self.candidates.append(candidate)
        if self._events is not None:
            self._events.append("run")
        if self._error is not None:
            raise self._error
        outcome = super().run(candidate, on_event)
        return dataclasses.replace(outcome, replay_counts=self._counts)


class _AsyncRecordingTransport(_AsyncFakeTransport):
    def __init__(
        self,
        events: list[str] | None = None,
        counts: _ReplayCounts | None = None,
    ) -> None:
        super().__init__()
        self.candidates: list[Any] = []
        self._events = events
        self._counts = counts

    async def run(self, candidate: Any, on_event: object) -> _RunOutcome:
        self.candidates.append(candidate)
        if self._events is not None:
            self._events.append("run")
        outcome = await super().run(candidate, on_event)
        return dataclasses.replace(outcome, replay_counts=self._counts)


def _sync_client(
    scoreboard: Callable[[httpx.Request], httpx.Response],
    transport: _RecordingTransport,
    engine: Callable[[httpx.Request], httpx.Response] = _draco_engine,
) -> sf.Client:
    return sf.Client(
        engine_url=ENGINE_URL,
        scoreboard_url=SCOREBOARD_URL,
        http_transport=httpx.MockTransport(engine),
        scoreboard_transport=httpx.MockTransport(scoreboard),
        run_transport=transport,
    )


def _async_client(
    scoreboard: Callable[[httpx.Request], httpx.Response],
    transport: _AsyncRecordingTransport,
    engine: Callable[[httpx.Request], httpx.Response] = _draco_engine,
) -> sf.AsyncClient:
    return sf.AsyncClient(
        engine_url=ENGINE_URL,
        scoreboard_url=SCOREBOARD_URL,
        http_transport=httpx.MockTransport(engine),
        scoreboard_transport=httpx.MockTransport(scoreboard),
        run_transport=transport,
    )


def _evaluate(client: sf.Client, **options: Any) -> sf.Report:
    return client.evaluate(RECIPE, benchmark="draco", limit=1, progress=False, **options)


async def _evaluate_async(client: sf.AsyncClient, **options: Any) -> sf.Report:
    return await client.evaluate(RECIPE, benchmark="draco", limit=1, progress=False, **options)


# --- RP-16: the grant comes first, then the run ------------------------------------------------


def test_rp16_evaluate_replay_requests_grant_then_runs() -> None:
    events: list[str] = []
    scoreboard = _Scoreboard(events=events)
    transport = _RecordingTransport(events=events)

    with _sync_client(scoreboard, transport) as client:
        _evaluate(client, replay=PIN)

    assert len(scoreboard.requests) == 1
    request = scoreboard.requests[0]
    assert (request.method, request.url.path) == ("POST", "/v1/replay-grants")
    assert json.loads(request.content) == {"pin": PIN, "benchmark_id": "draco"}
    assert events == ["grant", "run"]
    binding = transport.candidates[0].replay
    assert binding.grant == GRANT
    assert (binding.result_id, binding.score_id, binding.cache_version_id) == (
        RESULT_ID,
        SCORE_ID,
        VERSION_ID,
    )
    assert binding.expires_at == datetime(2026, 9, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_rp16_evaluate_replay_requests_grant_then_runs_async() -> None:
    events: list[str] = []
    scoreboard = _Scoreboard(events=events)
    transport = _AsyncRecordingTransport(events=events)
    client = _async_client(scoreboard, transport)

    try:
        await _evaluate_async(client, replay=PIN)
    finally:
        await client.aclose()

    assert len(scoreboard.requests) == 1
    assert json.loads(scoreboard.requests[0].content) == {"pin": PIN, "benchmark_id": "draco"}
    assert events == ["grant", "run"]
    assert transport.candidates[0].replay.grant == GRANT


def _binding() -> _ReplayBinding:
    return _ReplayBinding(
        grant=GRANT,
        result_id=RESULT_ID,
        score_id=SCORE_ID,
        cache_version_id=VERSION_ID,
        expires_at=datetime(2026, 9, 30, tzinfo=UTC),
        pinned_baseline_result_id=None,
    )


def test_rp16_a_seed_and_a_grant_ride_one_candidate_whichever_is_stamped_first() -> None:
    """INVARIANT: neither stamp drops the other, so the run keeps its sitting AND its version."""
    base = _compiled_candidate(
        name="sample",
        kind="model",
        models=["provider/model"],
        url4=CANDIDATE_URL4,
        operations=[_compiled_operation(id="op", kind="model", label="Model", depends_on=())],
    )
    binding = _binding()

    seeded_then_bound = _with_replay(_with_answer_seed(base, 7), binding)
    bound_then_seeded = _with_answer_seed(_with_replay(base, binding), 7)

    for stamped in (seeded_then_bound, bound_then_seeded):
        assert stamped.answer_seed == 7
        assert stamped.replay is binding
        assert (stamped.name, stamped.url4, stamped.models) == (base.name, base.url4, base.models)
    assert base.replay is None
    assert base.answer_seed is None


def test_rp16_a_seeded_pinned_run_sends_both_on_its_candidate() -> None:
    transport = _RecordingTransport()

    with _sync_client(_Scoreboard(), transport, _seed_capable_engine) as client:
        _evaluate(client, replay=PIN, answer_seed=7)

    assert transport.candidates[0].answer_seed == 7
    assert transport.candidates[0].replay.grant == GRANT


def test_rp16_a_run_without_a_pin_asks_for_no_grant_and_carries_none() -> None:
    scoreboard = _Scoreboard()
    transport = _RecordingTransport()

    with _sync_client(scoreboard, transport) as client:
        result = _evaluate(client)

    assert scoreboard.requests == []
    assert transport.candidates[0].replay is None
    assert result.candidates.only.replay is None


def test_rp16_the_grant_never_shows_in_a_repr() -> None:
    binding = _ReplayBinding(
        grant=GRANT,
        result_id=RESULT_ID,
        score_id=SCORE_ID,
        cache_version_id=VERSION_ID,
        expires_at=datetime(2026, 9, 30, tzinfo=UTC),
        pinned_baseline_result_id=None,
    )

    assert GRANT not in repr(binding)


def test_rp16_the_pin_is_sent_stripped_and_unchanged_in_case() -> None:
    scoreboard = _Scoreboard()
    transport = _RecordingTransport()

    with _sync_client(scoreboard, transport) as client:
        _evaluate(client, replay="  Opus-5.5@r2  ")

    assert json.loads(scoreboard.requests[0].content)["pin"] == "Opus-5.5@r2"


def _recording_http(seen: list[httpx.Request]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            202,
            headers={"Preference-Applied": "respond-async", "Location": "/runs/1"},
        )

    return httpx.Client(transport=httpx.MockTransport(handle), base_url="https://engine.test")


def test_rp16_start_request_carries_the_grant_only_when_bound() -> None:
    seen: list[httpx.Request] = []
    http = _recording_http(seen)

    _start_sync(http, TOKEN, URL4, replay_grant=GRANT)
    _start_sync(http, TOKEN, URL4)

    assert seen[0].headers["X-SF-Cache-Replay"] == GRANT
    assert "X-SF-Cache-Replay" not in seen[1].headers


@pytest.mark.asyncio
async def test_rp16_start_request_carries_the_grant_only_when_bound_async() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            202,
            headers={"Preference-Applied": "respond-async", "Location": "/runs/1"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="https://engine.test"
    ) as http:
        await _start_async(http, TOKEN, URL4, replay_grant=GRANT)
        await _start_async(http, TOKEN, URL4)

    assert seen[0].headers["X-SF-Cache-Replay"] == GRANT
    assert "X-SF-Cache-Replay" not in seen[1].headers


def test_rp16_the_grant_rides_the_start_request_only_never_the_query() -> None:
    """D7 X-5: the header rides `GET /?q=`. The grant is never part of the url4 query."""
    seen: list[httpx.Request] = []

    _start_sync(_recording_http(seen), TOKEN, URL4, replay_grant=GRANT)

    assert seen[0].url.params["q"] == URL4
    assert GRANT not in str(seen[0].url)


@pytest.mark.parametrize(
    ("counts", "coverage"),
    [
        (_ReplayCounts(420, 0, 0), "complete"),
        (_ReplayCounts(412, 8, 0), "partial"),
        (None, "unknown"),
    ],
)
def test_rp16_report_carries_the_replay_block(
    counts: _ReplayCounts | None, coverage: Literal["complete", "partial", "unknown"]
) -> None:
    transport = _RecordingTransport(counts=counts)

    with _sync_client(_Scoreboard(), transport) as client:
        result = _evaluate(client, replay=PIN)

    replay = result.candidates.only.replay
    assert replay is not None
    assert (replay.result_id, replay.cache_version_id) == (RESULT_ID, VERSION_ID)
    assert replay.coverage == coverage
    assert replay.pinned_baseline_result_id is None
    if counts is None:
        assert (replay.hits, replay.misses, replay.repeated_key_collapses) == (None, None, None)
    else:
        assert (replay.hits, replay.misses, replay.repeated_key_collapses) == (
            counts.hits,
            counts.misses,
            counts.repeated_key_collapses,
        )
    block = result.candidates.only.to_dict()["replay"]
    assert block == {
        "result_id": str(RESULT_ID),
        "cache_version_id": str(VERSION_ID),
        "hits": None if counts is None else counts.hits,
        "misses": None if counts is None else counts.misses,
        "repeated_key_collapses": None if counts is None else counts.repeated_key_collapses,
        "coverage": coverage,
        "pinned_baseline_result_id": None,
    }
    assert json.loads(result.to_json())["candidates"][0]["replay"] == block


def test_rp16_report_without_a_binding_serializes_replay_as_null() -> None:
    """Stable key, null value: the report always names `replay` (report.py convention)."""
    with _sync_client(_Scoreboard(), _RecordingTransport()) as client:
        result = _evaluate(client)

    assert result.candidates.only.to_dict()["replay"] is None


def test_rp16_a_date_pin_names_its_resolved_baseline_result() -> None:
    """OD-8: `pinned_baseline_result_id` is the resolved result for a `date` pin only."""
    transport = _RecordingTransport(counts=_ReplayCounts(5, 0, 0))

    with _sync_client(_Scoreboard(), transport) as client:
        dated = _evaluate(client, replay="kevins-best@2026-09-01")
        named = _evaluate(client, replay="kevins-best")
        revised = _evaluate(client, replay="kevins-best@r2")

    assert dated.candidates.only.replay is not None
    assert dated.candidates.only.replay.pinned_baseline_result_id == RESULT_ID
    assert named.candidates.only.replay is not None
    assert named.candidates.only.replay.pinned_baseline_result_id is None
    assert revised.candidates.only.replay is not None
    assert revised.candidates.only.replay.pinned_baseline_result_id is None


@pytest.mark.parametrize("bad", [True, "x", 1.5, -1])
def test_rp16_the_record_refuses_a_count_that_is_not_a_natural_number(bad: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        sf.ReplayProvenance(
            result_id=RESULT_ID,
            cache_version_id=VERSION_ID,
            hits=bad,  # type: ignore[arg-type]
            misses=0,
            repeated_key_collapses=0,
            pinned_baseline_result_id=None,
        )


def test_rp16_the_record_refuses_a_replay_that_is_not_a_provenance() -> None:
    original = _candidate()
    fields = {name: getattr(original, name) for name in signature(sf.CandidateResult).parameters}
    fields["replay"] = {"result_id": str(RESULT_ID)}

    with pytest.raises(TypeError):
        sf.CandidateResult(**fields)


# --- RP-16: the grant is checked before any run ------------------------------------------------


def test_rp16_oversize_grant_is_refused_before_any_run() -> None:
    scoreboard = _Scoreboard(_grant_response(grant="g" * 2049))
    transport = _RecordingTransport()

    with (
        _sync_client(scoreboard, transport) as client,
        pytest.raises(sf.LeaderboardError) as caught,
    ):
        _evaluate(client, replay=PIN)

    assert caught.value.code == "invalid_replay_grant"
    assert caught.value.permanent is True
    assert transport.candidates == []


def test_rp16_a_grant_of_exactly_the_limit_is_accepted() -> None:
    """The limit is bytes, not characters: 2,048 ASCII bytes pass."""
    transport = _RecordingTransport()

    with _sync_client(_Scoreboard(_grant_response(grant="g" * 2048)), transport) as client:
        _evaluate(client, replay=PIN)

    assert len(transport.candidates[0].replay.grant.encode()) == 2048


def test_rp16_the_grant_limit_counts_utf8_bytes() -> None:
    """1,025 two-byte characters are 2,050 bytes although only 1,025 characters long."""
    scoreboard = _Scoreboard(_grant_response(grant="é" * 1025))
    transport = _RecordingTransport()

    with (
        _sync_client(scoreboard, transport) as client,
        pytest.raises(sf.LeaderboardError) as caught,
    ):
        _evaluate(client, replay=PIN)

    assert caught.value.code == "invalid_replay_grant"
    assert transport.candidates == []


@pytest.mark.parametrize("grant", [None, "", "   ", 5])
def test_rp16_a_missing_or_blank_grant_is_refused_before_any_run(grant: object) -> None:
    transport = _RecordingTransport()

    with (
        _sync_client(_Scoreboard(_grant_response(grant=grant)), transport) as client,
        pytest.raises(sf.LeaderboardError) as caught,
    ):
        _evaluate(client, replay=PIN)

    assert caught.value.code == "invalid_replay_grant"
    assert transport.candidates == []


@pytest.mark.parametrize(
    "over",
    [
        {"result_id": "not-a-uuid"},
        {"score_id": None},
        {"cache_version_id": 5},
        {"expires_at": "2026-09-30T00:00:00"},
        {"expires_at": "tomorrow"},
        {"expires_at": None},
    ],
)
def test_rp16_a_malformed_grant_body_is_refused_before_any_run(over: dict[str, object]) -> None:
    transport = _RecordingTransport()

    with (
        _sync_client(_Scoreboard(_grant_response(**over)), transport) as client,
        pytest.raises(sf.LeaderboardError) as caught,
    ):
        _evaluate(client, replay=PIN)

    assert caught.value.code == "invalid_leaderboard"
    assert transport.candidates == []


def test_rp16_a_grant_reply_that_is_not_an_object_is_refused_before_any_run() -> None:
    transport = _RecordingTransport()

    with (
        _sync_client(_Scoreboard(httpx.Response(200, json=["grant"])), transport) as client,
        pytest.raises(sf.LeaderboardError) as caught,
    ):
        _evaluate(client, replay=PIN)

    assert caught.value.code == "invalid_leaderboard"
    assert transport.candidates == []


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (404, {"detail": "unknown pin"}, "replay_pin_not_found"),
        (410, {}, "cache_version_withdrawn"),
        (422, {"detail": "bad pin"}, "invalid_replay_pin"),
        (
            422,
            {"detail": {"code": "replay_benchmark_mismatch", "message": "other benchmark"}},
            "replay_benchmark_mismatch",
        ),
        (
            404,
            {"detail": {"code": "replay_pin_not_found", "message": "no such system"}},
            "replay_pin_not_found",
        ),
        (401, {}, "scoreboard_contract_error"),
        (403, {}, "scoreboard_contract_error"),
    ],
)
def test_rp16_grant_errors_are_typed_and_nothing_runs(
    status: int, body: dict[str, object], code: str
) -> None:
    transport = _RecordingTransport()

    with (
        _sync_client(_Scoreboard(httpx.Response(status, json=body)), transport) as client,
        pytest.raises(sf.LeaderboardError) as caught,
    ):
        _evaluate(client, replay=PIN)

    assert not isinstance(caught.value, sf.ReplayUnavailable)
    assert caught.value.code == code
    assert caught.value.permanent is True
    assert caught.value.status == status
    assert transport.candidates == []


def test_rp16_grant_request_uses_a_10_second_timeout() -> None:
    scoreboard = _Scoreboard()

    with _sync_client(scoreboard, _RecordingTransport()) as client:
        _evaluate(client, replay=PIN)

    assert scoreboard.requests[0].extensions["timeout"]["read"] == 10.0


@pytest.mark.asyncio
async def test_rp16_grant_request_uses_a_10_second_timeout_async() -> None:
    scoreboard = _Scoreboard()
    client = _async_client(scoreboard, _AsyncRecordingTransport())

    try:
        await _evaluate_async(client, replay=PIN)
    finally:
        await client.aclose()

    assert scoreboard.requests[0].extensions["timeout"]["read"] == 10.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (404, {"detail": "unknown pin"}, "replay_pin_not_found"),
        (410, {}, "cache_version_withdrawn"),
        (
            422,
            {"detail": {"code": "replay_benchmark_mismatch", "message": "other benchmark"}},
            "replay_benchmark_mismatch",
        ),
    ],
)
async def test_rp16_grant_errors_are_typed_and_nothing_runs_async(
    status: int, body: dict[str, object], code: str
) -> None:
    transport = _AsyncRecordingTransport()
    client = _async_client(_Scoreboard(httpx.Response(status, json=body)), transport)

    try:
        with pytest.raises(sf.LeaderboardError) as caught:
            await _evaluate_async(client, replay=PIN)
    finally:
        await client.aclose()

    assert caught.value.code == code
    assert caught.value.permanent is True
    assert transport.candidates == []


# --- RP-19: a Scoreboard that cannot answer stops the run --------------------------------------

# WHY factories: one `httpx.Response` cannot be read by both the sync and the async twin.
_DOWN: list[Callable[[], Reply]] = [
    lambda: httpx.ConnectError("refused"),
    lambda: httpx.ReadTimeout("slow"),
    lambda: httpx.Response(500, json={"detail": "boom"}),
    lambda: httpx.Response(503, json={"detail": "busy"}),
]


@pytest.mark.parametrize("reply", _DOWN, ids=["connect", "timeout", "500", "503"])
def test_rp19_scoreboard_down_raises_replay_unavailable(reply: Callable[[], Reply]) -> None:
    scoreboard = _Scoreboard(reply())
    transport = _RecordingTransport()

    with (
        _sync_client(scoreboard, transport) as client,
        pytest.raises(sf.ReplayUnavailable) as caught,
    ):
        _evaluate(client, replay=PIN)

    assert isinstance(caught.value, sf.LeaderboardError)
    assert caught.value.retryable is True
    assert caught.value.code == "replay_unavailable"
    assert caught.value.__cause__ is not None
    assert len(scoreboard.requests) == 1
    assert transport.candidates == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", _DOWN, ids=["connect", "timeout", "500", "503"])
async def test_rp19_scoreboard_down_raises_replay_unavailable_async(
    reply: Callable[[], Reply],
) -> None:
    scoreboard = _Scoreboard(reply())
    transport = _AsyncRecordingTransport()
    client = _async_client(scoreboard, transport)

    try:
        with pytest.raises(sf.ReplayUnavailable) as caught:
            await _evaluate_async(client, replay=PIN)
    finally:
        await client.aclose()

    assert caught.value.retryable is True
    assert len(scoreboard.requests) == 1
    assert transport.candidates == []


def test_rp19_the_error_names_the_scoreboard_and_carries_the_status() -> None:
    with (
        _sync_client(_Scoreboard(httpx.Response(503, json={})), _RecordingTransport()) as client,
        pytest.raises(sf.ReplayUnavailable) as caught,
    ):
        _evaluate(client, replay=PIN)

    assert caught.value.scoreboard_url == SCOREBOARD_URL
    assert caught.value.status == 503


# --- RP-18: a malformed pin fails before any call ----------------------------------------------

_MALFORMED: list[tuple[object, type[Exception]]] = [
    ("", ValueError),
    ("  ", ValueError),
    (5, TypeError),
    ("result:not-a-uuid", ValueError),
    ("score:", ValueError),
    ("Kevin Best", ValueError),
    ("-bad", ValueError),
    ("a" * 65, ValueError),
    ("kevins-best@r0", ValueError),
    ("kevins-best@r-1", ValueError),
    ("kevins-best@rx", ValueError),
    ("kevins-best@2026-13-01", ValueError),
    ("kevins-best@2026-09-01T10:00:00", ValueError),
    ("kevins@best@r1", ValueError),
]


@pytest.mark.parametrize(("pin", "error"), _MALFORMED)
def test_rp18_malformed_pin_raises_before_any_call(pin: object, error: type[Exception]) -> None:
    scoreboard = _Scoreboard()
    engine = _Engine()
    transport = _RecordingTransport()

    with _sync_client(scoreboard, transport, engine) as client, pytest.raises(error):
        _evaluate(client, replay=pin)

    assert scoreboard.requests == []
    assert engine.requests == []
    assert transport.candidates == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("pin", "error"), _MALFORMED)
async def test_rp18_malformed_pin_raises_before_any_call_async(
    pin: object, error: type[Exception]
) -> None:
    scoreboard = _Scoreboard()
    engine = _Engine()
    transport = _AsyncRecordingTransport()
    client = _async_client(scoreboard, transport, engine)

    try:
        with pytest.raises(error):
            await _evaluate_async(client, replay=pin)
    finally:
        await client.aclose()

    assert scoreboard.requests == []
    assert engine.requests == []
    assert transport.candidates == []


@pytest.mark.parametrize("pin", [None, b"kevins-best", ["kevins-best"]])
def test_rp18_a_pin_that_is_not_text_is_a_type_error(pin: object) -> None:
    """`replay=None` means no replay to `evaluate`, so the grammar check is tested directly."""
    with pytest.raises(TypeError, match="replay must be a pin string"):
        parse_replay_pin(pin)


def test_rp18_the_error_names_the_pin_and_the_reason() -> None:
    with pytest.raises(ValueError, match=r"invalid replay pin 'kevins-best@r0': .+"):
        parse_replay_pin("kevins-best@r0")


_VALID: list[tuple[str, str, str]] = [
    (f"result:{RESULT_ID}", f"result:{RESULT_ID}", "result"),
    (f"score:{SCORE_ID}", f"score:{SCORE_ID}", "score"),
    ("kevins-best", "kevins-best", "name"),
    ("Opus-5.5", "Opus-5.5", "name"),
    ("  kevins-best  ", "kevins-best", "name"),
    ("kevins-best@r2", "kevins-best@r2", "revision"),
    ("kevins-best@r123456789", "kevins-best@r123456789", "revision"),
    ("kevins-best@2026-09-01", "kevins-best@2026-09-01", "date"),
    ("kevins-best@2026-09-01T10:00:00+02:00", "kevins-best@2026-09-01T10:00:00+02:00", "date"),
    ("kevins-best@2026-09-01T10:00:00Z", "kevins-best@2026-09-01T10:00:00Z", "date"),
]


@pytest.mark.parametrize(("pin", "text", "kind"), _VALID)
def test_rp18_valid_pin_forms_parse(pin: str, text: str, kind: str) -> None:
    parsed = parse_replay_pin(pin)

    assert (parsed.text, parsed.kind) == (text, kind)


# WHY these forms: the SDK grammar mirrors the Scoreboard parser (`pins.py` and `names.py` under
# `apps/scoreboard/src/scoreboard/core/registry/`, D7 X-21). The plan text of section 4.1 was looser
# than the merged parser in the first four places. The two must accept and refuse the same forms.
_PARITY_REFUSALS = [
    "kevins-best@r1234567890",  # the Scoreboard caps a revision at nine digits
    "kevins-best@2026-W01-1",  # an ISO week date is not a date pin
    "\N{KELVIN SIGN}evins-best",  # lowercases to ASCII `k`; the Scoreboard refuses non-ASCII first
    "kevins-best\n@r1",  # `$` would let a newline pass; the Scoreboard uses a full match
    "kevins-best@",  # an empty qualifier
]


@pytest.mark.parametrize("pin", _PARITY_REFUSALS)
def test_rp18_forms_the_scoreboard_refuses_are_refused_here_too(pin: str) -> None:
    with pytest.raises(ValueError, match="invalid replay pin"):
        parse_replay_pin(pin)


# --- RP-17: one Candidate only -----------------------------------------------------------------


def test_rp17_multi_candidate_with_pin_raises_before_any_call() -> None:
    scoreboard = _Scoreboard()
    engine = _Engine()
    transport = _RecordingTransport()

    with _sync_client(scoreboard, transport, engine) as client, pytest.raises(ValueError):
        client.evaluate(
            [RECIPE, OTHER_RECIPE], benchmark="draco", limit=1, progress=False, replay="kevins-best"
        )

    assert scoreboard.requests == []
    assert engine.requests == []
    assert transport.candidates == []


@pytest.mark.asyncio
async def test_rp17_multi_candidate_with_pin_raises_before_any_call_async() -> None:
    scoreboard = _Scoreboard()
    engine = _Engine()
    transport = _AsyncRecordingTransport()
    client = _async_client(scoreboard, transport, engine)

    try:
        with pytest.raises(ValueError):
            await client.evaluate(
                [RECIPE, OTHER_RECIPE],
                benchmark="draco",
                limit=1,
                progress=False,
                replay="kevins-best",
            )
    finally:
        await client.aclose()

    assert scoreboard.requests == []
    assert engine.requests == []
    assert transport.candidates == []


def test_rp17_a_list_of_one_recipe_is_accepted() -> None:
    transport = _RecordingTransport()

    with _sync_client(_Scoreboard(), transport) as client:
        client.evaluate([RECIPE], benchmark="draco", limit=1, progress=False, replay=PIN)

    assert len(transport.candidates) == 1


# --- RP-16: the other doors --------------------------------------------------------------------


def test_rp16_raw_url4_with_replay_raises_type_error() -> None:
    scoreboard = _Scoreboard()
    transport = _RecordingTransport()

    with _sync_client(scoreboard, transport) as client, pytest.raises(TypeError, match="replay"):
        client.evaluate(URL4, progress=False, replay=PIN)  # type: ignore[call-overload]

    assert scoreboard.requests == []
    assert transport.candidates == []


@pytest.mark.asyncio
async def test_rp16_raw_url4_with_replay_raises_type_error_async() -> None:
    scoreboard = _Scoreboard()
    transport = _AsyncRecordingTransport()
    client = _async_client(scoreboard, transport)

    try:
        with pytest.raises(TypeError, match="replay"):
            await client.evaluate(URL4, progress=False, replay=PIN)  # type: ignore[call-overload]
    finally:
        await client.aclose()

    assert scoreboard.requests == []
    assert transport.candidates == []


class _RecordingClient:
    """Stand in for the lazy default Client, capturing one `evaluate` call's kwargs."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def evaluate(self, *args: Any, **kwargs: Any) -> str:
        self.calls.append((args, kwargs))
        return "report"


def test_rp16_facade_passes_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient()
    monkeypatch.setattr(_default_client, "default_client", lambda: client)

    sf.evaluate(RECIPE, benchmark="draco", replay=PIN)
    sf.evaluate("url4://an/expression", replay=PIN)  # type: ignore[call-overload]
    sf.evaluate(RECIPE, benchmark="draco")

    assert client.calls[0][1]["replay"] == PIN
    assert client.calls[1][1]["replay"] == PIN
    assert client.calls[2][1].get("replay") is None


# --- RP-16: the submit carries the replay block ------------------------------------------------


def _replayed(
    counts: tuple[int | None, int | None, int | None],
    baseline: UUID | None = SCORE_ID,
) -> sf.CandidateResult:
    original = _candidate()
    fields = {name: getattr(original, name) for name in signature(sf.CandidateResult).parameters}
    fields["replay"] = sf.ReplayProvenance(
        result_id=RESULT_ID,
        cache_version_id=VERSION_ID,
        hits=counts[0],
        misses=counts[1],
        repeated_key_collapses=counts[2],
        pinned_baseline_result_id=baseline,
    )
    return sf.CandidateResult(**fields)


def _submitting_client(scoreboard: list[httpx.Request], engine: list[httpx.Request]) -> sf.Client:
    def board(request: httpx.Request) -> httpx.Response:
        scoreboard.append(request)
        return httpx.Response(201, json=_score_response())

    def gateway(request: httpx.Request) -> httpx.Response:
        engine.append(request)
        return httpx.Response(500)

    return sf.Client(
        engine_url=ENGINE_URL,
        scoreboard_url=SCOREBOARD_URL,
        http_transport=httpx.MockTransport(gateway),
        scoreboard_transport=httpx.MockTransport(board),
    )


def test_rp16_submit_sends_the_replay_block() -> None:
    scoreboard: list[httpx.Request] = []

    with _submitting_client(scoreboard, []) as client:
        score = client.leaderboards.submit(_replayed((412, 8, 3)))

    assert score.id == UUID(SUBMITTED_SCORE_ID)
    body = json.loads(scoreboard[-1].content)
    assert body["replay"] == {
        "result_id": str(RESULT_ID),
        "cache_version_id": str(VERSION_ID),
        "hits": 412,
        "misses": 8,
        "repeated_key_collapses": 3,
        "pinned_baseline_result_id": str(SCORE_ID),
    }


def test_rp16_submit_without_a_replay_sends_no_replay_key() -> None:
    """A board before E14 is `extra="forbid"`, so a plain submit must not carry the key."""
    scoreboard: list[httpx.Request] = []

    with _submitting_client(scoreboard, []) as client:
        client.leaderboards.submit(_candidate(trace_id=None))

    assert "replay" not in json.loads(scoreboard[-1].content)


def test_rp16_submit_sends_a_null_baseline_when_the_pin_was_not_a_date() -> None:
    scoreboard: list[httpx.Request] = []

    with _submitting_client(scoreboard, []) as client:
        client.leaderboards.submit(_replayed((1, 0, 0), baseline=None))

    assert json.loads(scoreboard[-1].content)["replay"]["pinned_baseline_result_id"] is None


@pytest.mark.parametrize("counts", [(None, 0, 0), (1, None, 0), (1, 0, None), (None, None, None)])
def test_rp16_submit_refuses_a_replay_run_without_counters(
    counts: tuple[int | None, int | None, int | None],
) -> None:
    scoreboard: list[httpx.Request] = []
    engine: list[httpx.Request] = []

    with (
        _submitting_client(scoreboard, engine) as client,
        pytest.raises(ValueError, match="no replay counters"),
    ):
        client.leaderboards.submit(_replayed(counts))

    assert scoreboard == []
    assert engine == []


@pytest.mark.asyncio
async def test_rp16_submit_sends_the_replay_block_async() -> None:
    scoreboard: list[httpx.Request] = []

    async def board(request: httpx.Request) -> httpx.Response:
        scoreboard.append(request)
        return httpx.Response(201, json=_score_response())

    client = sf.AsyncClient(
        engine_url=ENGINE_URL,
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(board),
    )
    try:
        await client.leaderboards.submit(_replayed((412, 8, 3)))
    finally:
        await client.aclose()

    assert json.loads(scoreboard[-1].content)["replay"]["hits"] == 412


def test_rp16_a_trace_id_still_rides_with_the_replay_block_only_via_a_receipt() -> None:
    """The replay block changes nothing about `trace_id`: it rides only with a receipt."""
    assert _replayed((1, 0, 0)).trace_id == TRACE_ID


# --- RP-16: a grant that expires mid-run fails the run once (D4, guard row) --------------------


def test_rp16_grant_that_expires_mid_run_fails_the_run_once() -> None:
    """D4: no refresh, no second run, no plain fallback. The engine's typed code reaches the caller.

    A one-Candidate run raises the transport error itself (`_evaluation/runner.py:538-539`; the
    `candidates_failed` wrapper of `outcome.py` is only for two or more Candidates), so the engine's
    `code` is the caller's `exc.code`.
    """
    scoreboard = _Scoreboard()
    engine_error = sf.ExecutionError(
        "replay grant expired", code="replay_grant_invalid", permanent=True
    )
    transport = _RecordingTransport(error=engine_error)

    with _sync_client(scoreboard, transport) as client, pytest.raises(sf.ExecutionError) as caught:
        _evaluate(client, replay=PIN)

    assert caught.value is engine_error
    assert caught.value.code == "replay_grant_invalid"
    assert caught.value.permanent is True
    assert len(scoreboard.requests) == 1
    assert len(transport.candidates) == 1
