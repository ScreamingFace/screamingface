"""Freeze the cache version, then submit with the receipt (E14, OME-1307, SC-18 to SC-20).

FEATURE: OME-1307 (E14) reproducible submissions. The SDK half of contract C2a (freeze) and C4
(submit + receipt). One `httpx.MockTransport` fakes the engine and one fakes the Scoreboard (D7
X-20): no network, no `apps/` import, and no real sleep (the adapters get recording fakes).
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import httpx
import pytest
from url4 import expr, render, src, text

import screamingface as sf
from screamingface import _default_client
from screamingface._engine.cache_versions import AsyncEngineCacheVersions, EngineCacheVersions
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import _compiled_operation
from screamingface._scoreboard.leaderboards import AsyncLeaderboards, Leaderboards, _decode_score
from screamingface.errors import AuthenticationError, EngineUnavailableError

SCOREBOARD_URL = "https://scoreboard.example"
ENGINE_URL = "https://engine.example"
SUBMITTED_AT = "2026-08-08T12:30:00Z"
SCORE_ID = "af95892d-7438-4ac3-9b47-5e06f62c8251"
RESULT_ID = "3f0c5d0e-6f0b-4d75-a1f1-0c6f0b7d2a10"
CV_ID = "9b2c5f52-3c0a-4a37-8a54-6c3f1c1c5b11"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
RECEIPT = "eyJhbGciOiJFZERTQSJ9.e30.c2ln"
SHA = "a" * 64
RUN_ID = "run-fusion-alpha"

Mode = Literal["sync", "async"]
Wiring = Literal["fakes", "real", "bare"]
MODES: tuple[Mode, ...] = ("sync", "async")
Reply = httpx.Response | Exception
Submit = Callable[..., Awaitable[sf.LeaderboardScore]]


def _linked_url4() -> str:
    candidate = compile_candidate(sf.Model("openrouter/model")).url4
    assert candidate is not None
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("/benchmarks/draco/revision-1/cases", name="rows", weight=0.0),
            intent=text("$rows"),
        )
    )


def _score_response(**extra: object) -> dict[str, object]:
    return {
        "id": SCORE_ID,
        "version": 1,
        "benchmark_id": "draco",
        "spec_id": "fusion/alpha",
        "url4_expression": _linked_url4(),
        "submitted_by": "researcher@example.com",
        "submitted_at": SUBMITTED_AT,
        "score": 0.5,
        "total_questions": 2,
        "correct_questions": 1,
        "ran_with_providers": ["openrouter", "gemini-cli"],
        "ran_at_local": "2026-08-08T12:00:00Z",
        "client_name": "screamingface",
        "client_version": "0.1.0",
        "client_platform": "darwin",
        "verified_by_screamingface": False,
        "metadata": {"benchmark_revision": "fixture-revision"},
        **extra,
    }


def _candidate(trace_id: str | None = TRACE_ID, run_id: str = RUN_ID) -> sf.CandidateResult:
    def case(case_id: int, score: float) -> sf.CaseResult:
        return sf.CaseResult(
            case_id=case_id,
            input=f"Question {case_id}",
            output=f"Answer {case_id}",
            finish_reason="stop",
            grade=sf.CaseGrade(method="fixture", score=score, metrics={}, checks=()),
            failures=(),
            metadata={},
        )

    def member(name: str, model: str) -> sf.MemberResult:
        return sf.MemberResult(
            operation_id=f"op-{name}",
            name=name,
            kind="model",
            models=(model,),
            failures=(),
            duration_ms=1,
            usage=sf.Usage(),
        )

    return sf.CandidateResult(
        benchmark=sf.BenchmarkInfo(id="draco", revision="fixture-revision", case_count=2),
        run_id=run_id,
        started_at=datetime(2026, 8, 8, 11, 59, tzinfo=UTC),
        completed_at=datetime(2026, 8, 8, 12, tzinfo=UTC),
        name="fusion/alpha",
        kind="fusion",
        url4="(@)!'fusion alpha'",
        models=("openrouter/model-a", "gemini-cli/model-b"),
        operations=(
            _compiled_operation(id="op-a", kind="model", label="a", depends_on=()),
            _compiled_operation(id="op-b", kind="model", label="b", depends_on=()),
        ),
        score=0.5,
        coverage=1.0,
        metrics={"accuracy": 0.5},
        cases=(case(1, 1.0), case(2, 0.0)),
        members=(member("a", "openrouter/model-a"), member("b", "gemini-cli/model-b")),
        failures=(),
        usage=sf.Usage(),
        trace_id=trace_id,
    )


def _freeze_body(**over: object) -> dict[str, object]:
    return {
        "receipt": RECEIPT,
        "cache_version_id": CV_ID,
        "entry_count": 412,
        "call_count": 420,
        "missing_count": 8,
        "coverage_status": "partial",
        "archive_sha256": SHA,
        **over,
    }


def _frozen(status: int = 201) -> httpx.Response:
    return httpx.Response(status, json=_freeze_body())


def _stored(**extra: object) -> httpx.Response:
    return httpx.Response(201, json=_score_response(**extra))


class _Fake:
    """A scripted server. Every request goes into the ONE `calls` list shared by both fakes."""

    def __init__(self, name: str, calls: list[str], *replies: Reply) -> None:
        self.name = name
        self.calls = calls
        self.requests: list[httpx.Request] = []
        self.bodies: list[Any] = []
        self.timeouts: list[dict[str, float | None]] = []
        self._replies = list(replies)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{self.name} {request.method} {request.url.path}")
        self.requests.append(request)
        self.bodies.append(json.loads(request.read()) if request.content else None)
        self.timeouts.append(dict(request.extensions["timeout"]))
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if isinstance(reply, Exception):
            raise reply
        # WHY a copy: a Response stream is consumed by the first client that reads it, and one
        # scripted reply can serve two calls.
        return httpx.Response(reply.status_code, content=reply.content, headers=reply.headers)


class _Wire:
    def __init__(self, engine: list[Reply], board: list[Reply]) -> None:
        self.calls: list[str] = []
        self.waits: list[float] = []
        self.engine = _Fake("engine", self.calls, *engine)
        self.board = _Fake("scoreboard", self.calls, *board)

    def engine_calls(self) -> int:
        return len(self.engine.requests)


def _wire_sync(client: sf.Client, wire: _Wire, wiring: Wiring) -> None:
    if wiring == "fakes":
        # WHY replace: the client binds `time.sleep` when it builds the adapter.
        client.leaderboards = Leaderboards(
            client._scoreboard_request,
            client._scoreboard_url,
            freezer=EngineCacheVersions(
                client._http_request, sleep=wire.waits.append, jitter=lambda: 2.0
            ),
            sleep=wire.waits.append,
        )
    elif wiring == "bare":
        client.leaderboards = Leaderboards(client._scoreboard_request, client._scoreboard_url)


def _wire_async(client: sf.AsyncClient, wire: _Wire, wiring: Wiring) -> None:
    async def sleep(seconds: float) -> None:
        wire.waits.append(seconds)

    if wiring == "fakes":
        client.leaderboards = AsyncLeaderboards(
            client._scoreboard_request,
            client._scoreboard_url,
            freezer=AsyncEngineCacheVersions(client._http_request, sleep=sleep, jitter=lambda: 2.0),
            sleep=sleep,
        )
    elif wiring == "bare":
        client.leaderboards = AsyncLeaderboards(client._scoreboard_request, client._scoreboard_url)


@asynccontextmanager
async def _session(mode: Mode, wire: _Wire, *, wiring: Wiring = "fakes") -> AsyncIterator[Submit]:
    """One client per test, so a second `submit` can reuse the first one's receipt (SC-20).

    `wiring="real"` keeps the wiring of `Client.__init__` (rows that need no sleep).
    `wiring="bare"` builds a `Leaderboards` with no freezer.
    """
    if mode == "sync":
        with sf.Client(
            engine_url=ENGINE_URL,
            scoreboard_url=SCOREBOARD_URL,
            http_transport=httpx.MockTransport(wire.engine),
            scoreboard_transport=httpx.MockTransport(wire.board),
        ) as client:
            _wire_sync(client, wire, wiring)

            async def submit_sync(candidate: sf.CandidateResult, **kwargs: Any) -> Any:
                return client.leaderboards.submit(candidate, **kwargs)

            yield submit_sync
        return
    async with sf.AsyncClient(
        engine_url=ENGINE_URL,
        scoreboard_url=SCOREBOARD_URL,
        http_transport=httpx.MockTransport(wire.engine),
        scoreboard_transport=httpx.MockTransport(wire.board),
    ) as async_client:
        _wire_async(async_client, wire, wiring)

        async def submit_async(candidate: sf.CandidateResult, **kwargs: Any) -> Any:
            return await async_client.leaderboards.submit(candidate, **kwargs)

        yield submit_async


# --- row 1: freeze first, then submit with the receipt ----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sc18_submit_freezes_then_submits_with_receipt(mode: Mode) -> None:
    wire = _Wire([_frozen()], [_stored()])

    async with _session(mode, wire, wiring="real") as submit:
        score = await submit(_candidate(), paper_url="https://arxiv.org/abs/2609.01234")

    assert wire.calls == ["engine POST /v1/cache-versions", "scoreboard POST /v1/scores"]
    assert wire.engine.bodies == [{"trace_id": TRACE_ID}]
    posted = wire.board.bodies[0]
    assert posted["cache_version_receipt"] == RECEIPT
    assert posted["trace_id"] == TRACE_ID
    assert posted["paper_url"] == "https://arxiv.org/abs/2609.01234"
    assert wire.board.requests[0].headers["Idempotency-Key"] == RUN_ID
    assert score.cache_version_warning is None
    # INVARIANT: the client never sends a version field of its own; the receipt is the only way.
    assert "cache_version_id" not in posted
    assert "cache_version" not in posted


# --- row 2: the C4 block ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sc18_submit_decodes_reported_result_and_notices(mode: Mode) -> None:
    wire = _Wire(
        [_frozen()],
        [
            _stored(
                reported_result={
                    "id": RESULT_ID,
                    "is_original": False,
                    "reporter": "ana@example.com",
                    "cache_version": {
                        "id": CV_ID,
                        "sha256": SHA,
                        "entry_count": 412,
                        "call_count": 420,
                        "coverage_status": "complete",
                    },
                    "publication_state": "private",
                },
                reported_results_count=2,
                notices=[{"code": "clustered_under", "score_id": SCORE_ID}],
            )
        ],
    )

    async with _session(mode, wire) as submit:
        score = await submit(_candidate())

    assert score.reported_result == sf.LeaderboardReportedResult(
        id=UUID(RESULT_ID),
        is_original=False,
        reporter="ana@example.com",
        cache_version=sf.LeaderboardCacheVersion(
            id=UUID(CV_ID),
            sha256=SHA,
            entry_count=412,
            call_count=420,
            coverage_status="complete",
        ),
        publication_state="private",
    )
    assert score.reported_results_count == 2
    assert score.notices == (
        sf.LeaderboardNotice(code="clustered_under", details={"score_id": SCORE_ID}),
    )
    assert score.notices[0].details["score_id"] == SCORE_ID


# --- row 3: SC-19, a failed freeze never stops the submit -------------------------------------

_PARAMS_SC19: list[tuple[str, list[Reply], str]] = [
    ("timeout", [httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow")], "timeout"),
    ("unreachable", [httpx.ConnectError("down"), httpx.ConnectError("down")], "unreachable"),
    (
        "404_coded",
        [httpx.Response(404, json={"code": "trace_not_captured"})],
        "trace_not_captured",
    ),
    (
        "413_detail_coded",
        [httpx.Response(413, json={"detail": {"code": "cache_version_too_large"}})],
        "cache_version_too_large",
    ),
    ("503_twice", [httpx.Response(503), httpx.Response(503)], "http_503"),
    ("500_no_retry", [httpx.Response(500)], "http_500"),
    (
        "missing_receipt",
        [httpx.Response(201, json={"cache_version_id": CV_ID})],
        "invalid_response",
    ),
    ("bad_code_text", [httpx.Response(404, json={"code": "Bad Code!"})], "http_404"),
    ("not_json", [httpx.Response(200, content=b"<html>")], "invalid_response"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("engine", "reason"),
    [(engine, reason) for _, engine, reason in _PARAMS_SC19],
    ids=[name for name, _, _ in _PARAMS_SC19],
)
async def test_sc19_freeze_failure_submits_without_version_and_warns(
    mode: Mode,
    engine: list[Reply],
    reason: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wire = _Wire(engine, [_stored()])

    with caplog.at_level(logging.WARNING):
        async with _session(mode, wire) as submit:
            score = await submit(_candidate())

    assert score.cache_version_warning == f"cache_version_unavailable: {reason}"
    posted = wire.board.bodies[0]
    assert "cache_version_receipt" not in posted
    assert "trace_id" not in posted
    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert f"cache_version_unavailable: {reason} (run_id={RUN_ID})" in lines
    # INVARIANT: no trace id and no receipt reach a log line.
    assert all(TRACE_ID not in line and RECEIPT not in line for line in lines)


# WHY a second table and not more rows in the first: the first table is the prior contract and
# stays untouched (append-only). These rows are the errors that are not `httpx.TransportError`.
_PARAMS_SC19_NOT_TRANSPORT: list[tuple[str, list[Reply], str]] = [
    ("decoding_error", [httpx.DecodingError("bad gzip")], "unreachable"),
    ("too_many_redirects", [httpx.TooManyRedirects("loop")], "unreachable"),
    (
        "engine_authentication_error",
        [AuthenticationError("Access login timed out", code="access_login_timeout")],
        "engine_auth_failed",
    ),
    (
        "engine_unavailable_error",
        [EngineUnavailableError("no Access discovery", engine_url=ENGINE_URL)],
        "unreachable",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("engine", "reason"),
    [(engine, reason) for _, engine, reason in _PARAMS_SC19_NOT_TRANSPORT],
    ids=[name for name, _, _ in _PARAMS_SC19_NOT_TRANSPORT],
)
async def test_sc19_an_engine_failure_that_is_not_a_transport_error_submits_and_warns(
    mode: Mode,
    engine: list[Reply],
    reason: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wire = _Wire(engine, [_stored()])

    with caplog.at_level(logging.WARNING):
        async with _session(mode, wire) as submit:
            score = await submit(_candidate())

    assert wire.calls[-1] == "scoreboard POST /v1/scores"
    assert score.cache_version_warning == f"cache_version_unavailable: {reason}"
    posted = wire.board.bodies[0]
    assert "cache_version_receipt" not in posted
    assert "trace_id" not in posted
    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert f"cache_version_unavailable: {reason} (run_id={RUN_ID})" in lines


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "failure",
    [
        httpx.DecodingError("bad gzip"),
        httpx.TooManyRedirects("loop"),
        AuthenticationError("Access login timed out", code="access_login_timeout"),
        EngineUnavailableError("no Access discovery", engine_url=ENGINE_URL),
    ],
    ids=["decoding_error", "too_many_redirects", "authentication_error", "engine_unavailable"],
)
async def test_sc19_an_engine_failure_that_is_not_a_transport_error_is_not_retried(
    mode: Mode, failure: Exception
) -> None:
    # INVARIANT: only a transport error or a C2a retry status earns the one retry; these
    # failures are not transient network faults, so a second call would only repeat them.
    wire = _Wire([failure], [_stored()])

    async with _session(mode, wire) as submit:
        await submit(_candidate())

    assert wire.engine_calls() == 1
    assert wire.waits == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sc19_a_result_with_no_trace_submits_with_no_engine_call(
    mode: Mode, caplog: pytest.LogCaptureFixture
) -> None:
    wire = _Wire([_frozen()], [_stored()])

    with caplog.at_level(logging.WARNING):
        async with _session(mode, wire) as submit:
            score = await submit(_candidate(trace_id=None))

    assert wire.calls == ["scoreboard POST /v1/scores"]
    assert score.cache_version_warning == "cache_version_unavailable: no_trace"
    assert "trace_id" not in wire.board.bodies[0]
    assert "cache_version_receipt" not in wire.board.bodies[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sc19_a_leaderboards_with_no_freezer_submits_and_warns(mode: Mode) -> None:
    wire = _Wire([_frozen()], [_stored()])

    async with _session(mode, wire, wiring="bare") as submit:
        score = await submit(_candidate())

    assert wire.calls == ["scoreboard POST /v1/scores"]
    assert score.cache_version_warning == "cache_version_unavailable: freeze_unconfigured"


# --- row 4: SC-20, the receipt survives a name error ------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sc20_resubmit_after_name_error_reuses_the_receipt(mode: Mode) -> None:
    taken = httpx.Response(
        409, json={"detail": {"code": "system_name_taken", "suggested_name": "x-2"}}
    )
    wire = _Wire([_frozen()], [taken, _stored()])

    async with _session(mode, wire) as submit:
        with pytest.raises(sf.LeaderboardError) as caught:
            await submit(_candidate())
        score = await submit(_candidate())

    assert caught.value.code == "system_name_taken"
    assert caught.value.status == 409
    assert caught.value.permanent is True
    assert caught.value.hint is None
    assert wire.engine_calls() == 1
    assert [body["cache_version_receipt"] for body in wire.board.bodies] == [RECEIPT, RECEIPT]
    assert wire.board.bodies[0]["trace_id"] == wire.board.bodies[1]["trace_id"] == TRACE_ID
    assert score.cache_version_warning is None
    # A 409 that is not a 5xx is never re-sent inside one submit (SC-E2).
    assert len(wire.board.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sc20_an_uncoded_409_keeps_the_retry_hint_and_is_not_permanent(mode: Mode) -> None:
    wire = _Wire([_frozen()], [httpx.Response(409, json={"detail": "race"})])

    async with _session(mode, wire) as submit:
        with pytest.raises(sf.LeaderboardError) as caught:
            await submit(_candidate())

    assert caught.value.code == "score_submission_conflict"
    assert caught.value.permanent is False
    assert caught.value.hint == "Retry the submission."


# --- row 5: the freeze retries once -----------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "failure",
    [httpx.Response(502), httpx.Response(503), httpx.Response(504), httpx.ConnectError("reset")],
    ids=["502", "503", "504", "connect_error"],
)
async def test_sc18_freeze_retries_once_on_502_503_504_and_connection_error(
    mode: Mode, failure: Reply
) -> None:
    wire = _Wire([failure, _frozen()], [_stored()])

    async with _session(mode, wire) as submit:
        score = await submit(_candidate())

    assert wire.engine_calls() == 2
    assert wire.waits == [2.0]
    assert wire.board.bodies[0]["cache_version_receipt"] == RECEIPT
    assert score.cache_version_warning is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sc18_freeze_never_retries_a_status_outside_the_retry_set(mode: Mode) -> None:
    wire = _Wire([httpx.Response(429)], [_stored()])

    async with _session(mode, wire) as submit:
        score = await submit(_candidate())

    assert wire.engine_calls() == 1
    assert wire.waits == []
    assert score.cache_version_warning == "cache_version_unavailable: http_429"


def test_the_default_freeze_jitter_stays_inside_one_to_three_seconds() -> None:
    from screamingface._engine.cache_versions import _jitter

    assert all(1.0 <= _jitter() <= 3.0 for _ in range(200))


# --- row 6: the freeze timeout ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sc18_freeze_uses_a_60_second_timeout(mode: Mode) -> None:
    wire = _Wire([_frozen()], [_stored()])

    async with _session(mode, wire, wiring="real") as submit:
        await submit(_candidate())

    assert wire.engine.timeouts[0]["read"] == 60.0
    assert wire.engine.timeouts[0]["connect"] == 60.0
    # The submit keeps its own 30 s (C4).
    assert wire.board.timeouts[0]["read"] == 30.0


# --- row 7: the submit retries ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (httpx.Response(503), 503, "scoreboard_contract_error"),
        (httpx.Response(500), 500, "scoreboard_contract_error"),
        (httpx.ConnectError("down"), None, "scoreboard_unreachable"),
    ],
    ids=["503", "500", "connect_error"],
)
async def test_sc18_submit_retries_twice_on_5xx_or_connection_error_then_raises(
    mode: Mode, failure: Reply, status: int | None, code: str
) -> None:
    wire = _Wire([_frozen()], [failure])

    async with _session(mode, wire) as submit:
        with pytest.raises(sf.LeaderboardError) as caught:
            await submit(_candidate())

    assert caught.value.status == status
    assert caught.value.code == code
    assert len(wire.board.requests) == 3
    assert len(wire.waits) == 2
    assert 0.5 <= wire.waits[0] <= 0.625
    assert 1.0 <= wire.waits[1] <= 1.25
    # The receipt rode every re-send: one freeze, three identical bodies.
    assert wire.engine_calls() == 1
    assert {json.dumps(body, sort_keys=True) for body in wire.board.bodies} == {
        json.dumps(wire.board.bodies[0], sort_keys=True)
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sc18_submit_succeeds_after_one_503(mode: Mode) -> None:
    wire = _Wire([_frozen()], [httpx.Response(503), _stored()])

    async with _session(mode, wire) as submit:
        score = await submit(_candidate())

    assert len(wire.board.requests) == 2
    assert len(wire.waits) == 1
    assert 0.5 <= wire.waits[0] <= 0.625
    assert score.id == UUID(SCORE_ID)


# --- row 8: a 4xx is never re-sent ------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (
            httpx.Response(409, json={"detail": {"code": "cache_version_already_bound"}}),
            "cache_version_already_bound",
        ),
        (
            httpx.Response(
                422, json={"detail": {"code": "invalid_cache_version_receipt", "reason": "x"}}
            ),
            "invalid_cache_version_receipt",
        ),
        (
            httpx.Response(403, json={"detail": {"code": "cache_version_not_yours"}}),
            "cache_version_not_yours",
        ),
    ],
    ids=["409", "422", "403"],
)
async def test_sc18_submit_never_retries_a_4xx(mode: Mode, reply: Reply, code: str) -> None:
    wire = _Wire([_frozen()], [reply])

    async with _session(mode, wire) as submit:
        with pytest.raises(sf.LeaderboardError) as caught:
            await submit(_candidate())

    assert len(wire.board.requests) == 1
    assert wire.waits == []
    assert caught.value.code == code
    assert caught.value.permanent is True


# --- rows 9 and 10: revision_of ---------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sc18_submit_sends_revision_of_only_when_given(mode: Mode) -> None:
    wire = _Wire([_frozen()], [_stored()])

    async with _session(mode, wire) as submit:
        await submit(_candidate(), revision_of="  kevins-best ")
        await submit(_candidate())

    assert wire.board.bodies[0]["revision_of"] == "kevins-best"
    assert "revision_of" not in wire.board.bodies[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("bad", "error"),
    [("", ValueError), ("  ", ValueError), (5, TypeError)],
    ids=["empty", "blank", "int"],
)
async def test_sc18_invalid_revision_of_raises_before_any_call(
    mode: Mode, bad: object, error: type[Exception]
) -> None:
    wire = _Wire([_frozen()], [_stored()])

    async with _session(mode, wire) as submit:
        with pytest.raises(error, match="revision_of must be"):
            await submit(_candidate(), revision_of=bad)

    assert wire.calls == []


# --- row 11: the module facade ----------------------------------------------------------------


def test_sc18_facade_submit_passes_revision_of(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeLeaderboards:
        def submit(self, candidate_result: object, **kwargs: object) -> str:
            calls.append(kwargs)
            return "submitted"

    class FakeClient:
        leaderboards = FakeLeaderboards()

    monkeypatch.setattr(_default_client, "_client", FakeClient())
    candidate = _candidate()

    assert sf.leaderboards.submit(candidate, revision_of="kevins-best") == "submitted"
    assert calls[-1] == {"authors": None, "revision_of": "kevins-best"}
    assert sf.leaderboards.submit(candidate, paper_url="https://a.example/p", revision_of="x") == (
        "submitted"
    )
    assert calls[-1] == {"authors": None, "paper_url": "https://a.example/p", "revision_of": "x"}
    # A keyword the caller did not give is not forwarded (a board before E14 stays valid).
    assert sf.leaderboards.submit(candidate) == "submitted"
    assert calls[-1] == {"authors": None}

    monkeypatch.setattr(_default_client, "_client", None)


# --- coverage pass: the receipt cache ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_an_unavailable_freeze_is_not_cached_so_a_resubmit_tries_again(mode: Mode) -> None:
    wire = _Wire([httpx.Response(404, json={"code": "trace_not_captured"}), _frozen()], [_stored()])

    async with _session(mode, wire) as submit:
        first = await submit(_candidate())
        second = await submit(_candidate())

    assert wire.engine_calls() == 2
    assert first.cache_version_warning == "cache_version_unavailable: trace_not_captured"
    assert second.cache_version_warning is None
    assert "cache_version_receipt" not in wire.board.bodies[0]
    assert wire.board.bodies[1]["cache_version_receipt"] == RECEIPT


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_the_receipt_key_is_the_run_and_the_trace_together(mode: Mode) -> None:
    other_trace = "00f92f3577b34da6a3ce929d0e0e4736"
    wire = _Wire([_frozen()], [_stored()])

    async with _session(mode, wire) as submit:
        await submit(_candidate())
        await submit(_candidate(trace_id=other_trace))
        await submit(_candidate(trace_id=other_trace))

    assert wire.engine.bodies == [{"trace_id": TRACE_ID}, {"trace_id": other_trace}]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_the_receipt_cache_is_bounded_and_drops_the_oldest(mode: Mode) -> None:
    wire = _Wire([_frozen()], [_stored()])

    async with _session(mode, wire) as submit:
        for index in range(33):
            await submit(_candidate(run_id=f"run-{index}"))
        assert wire.engine_calls() == 33
        await submit(_candidate(run_id="run-32"))  # newest: still cached
        assert wire.engine_calls() == 33
        await submit(_candidate(run_id="run-0"))  # oldest: dropped, so it freezes again
        assert wire.engine_calls() == 34


# --- coverage pass: the freeze adapter decode -------------------------------------------------

_BAD_FREEZE_BODIES: list[tuple[str, object]] = [
    ("not_an_object", ["receipt"]),
    ("blank_receipt", _freeze_body(receipt="  ")),
    ("receipt_not_text", _freeze_body(receipt=5)),
    ("bad_uuid", _freeze_body(cache_version_id="nope")),
    ("uuid_not_text", _freeze_body(cache_version_id=7)),
    ("bool_count", _freeze_body(entry_count=True)),
    ("negative_count", _freeze_body(call_count=-1)),
    ("float_count", _freeze_body(missing_count=1.5)),
    ("missing_count_key", {k: v for k, v in _freeze_body().items() if k != "missing_count"}),
    ("bad_coverage", _freeze_body(coverage_status="full")),
    ("short_digest", _freeze_body(archive_sha256="abc")),
    ("upper_digest", _freeze_body(archive_sha256="A" * 64)),
    ("digest_not_text", _freeze_body(archive_sha256=None)),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("body"), [body for _, body in _BAD_FREEZE_BODIES], ids=[n for n, _ in _BAD_FREEZE_BODIES]
)
async def test_sc19_a_freeze_body_that_breaks_c2a_is_invalid_response(
    mode: Mode, body: object
) -> None:
    wire = _Wire([httpx.Response(201, json=body)], [_stored()])

    async with _session(mode, wire) as submit:
        score = await submit(_candidate())

    assert score.cache_version_warning == "cache_version_unavailable: invalid_response"
    assert "cache_version_receipt" not in wire.board.bodies[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("status", [200, 201])
async def test_sc18_a_200_re_freeze_is_accepted_like_a_201(mode: Mode, status: int) -> None:
    wire = _Wire([_frozen(status)], [_stored()])

    async with _session(mode, wire) as submit:
        score = await submit(_candidate())

    assert wire.board.bodies[0]["cache_version_receipt"] == RECEIPT
    assert score.cache_version_warning is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (httpx.Response(422, json={"code": "invalid_freeze_request"}), "invalid_freeze_request"),
        (httpx.Response(401, json={"detail": "nope"}), "http_401"),
        (httpx.Response(403, content=b"<html>"), "http_403"),
        (httpx.Response(429, json=["x"]), "http_429"),
        (httpx.Response(413, json={"code": "  ", "detail": {"code": "too_big"}}), "too_big"),
        (httpx.Response(404, json={"code": "x" * 65}), "http_404"),
        (httpx.Response(404, json={"code": 5}), "http_404"),
    ],
    ids=["engine_problem", "detail_text", "html", "json_array", "blank_then_detail", "long", "int"],
)
async def test_sc19_the_freeze_reason_is_a_safe_token_or_the_http_status(
    mode: Mode, reply: httpx.Response, reason: str
) -> None:
    wire = _Wire([reply], [_stored()])

    async with _session(mode, wire) as submit:
        score = await submit(_candidate())

    assert score.cache_version_warning == f"cache_version_unavailable: {reason}"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_a_freeze_that_times_out_then_gets_a_503_reports_the_last_reason(mode: Mode) -> None:
    wire = _Wire([httpx.ReadTimeout("slow"), httpx.Response(503)], [_stored()])

    async with _session(mode, wire) as submit:
        score = await submit(_candidate())

    assert wire.waits == [2.0]
    assert score.cache_version_warning == "cache_version_unavailable: http_503"


# --- coverage pass: input checks and decoding -------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_a_bad_authors_value_raises_before_the_freeze(mode: Mode) -> None:
    wire = _Wire([_frozen()], [_stored()])

    async with _session(mode, wire) as submit:
        with pytest.raises(ValueError, match="authors"):
            await submit(_candidate(), authors=[])

    assert wire.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_a_board_before_e14_decodes_with_the_new_fields_at_their_defaults(mode: Mode) -> None:
    wire = _Wire([_frozen()], [_stored()])

    async with _session(mode, wire) as submit:
        score = await submit(_candidate())

    assert score.reported_result is None
    assert score.reported_results_count is None
    assert score.notices == ()
    assert score.cache_version_warning is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_null_c4_blocks_decode_like_absent_ones(mode: Mode) -> None:
    wire = _Wire(
        [_frozen()], [_stored(reported_result=None, reported_results_count=None, notices=None)]
    )

    async with _session(mode, wire) as submit:
        score = await submit(_candidate())

    assert (score.reported_result, score.reported_results_count, score.notices) == (None, None, ())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_an_unknown_notice_code_never_breaks_a_stored_submit(mode: Mode) -> None:
    wire = _Wire(
        [_frozen()],
        [_stored(notices=[{"code": "brand_new_notice", "owner": "ana", "nested": {"a": [1, 2]}}])],
    )

    async with _session(mode, wire) as submit:
        score = await submit(_candidate())

    (notice,) = score.notices
    assert notice.code == "brand_new_notice"
    assert notice.details["owner"] == "ana"
    with pytest.raises(TypeError):
        notice.details["owner"] = "bruno"  # type: ignore[index]


_BAD_C4_BLOCKS: list[tuple[str, dict[str, object]]] = [
    (
        "state",
        {"reported_result": {"id": RESULT_ID, "is_original": True, "publication_state": "x"}},
    ),
    ("count_zero", {"reported_results_count": 0}),
    ("count_text", {"reported_results_count": "2"}),
    ("notices_object", {"notices": {"code": "x"}}),
    ("notice_no_code", {"notices": [{"score_id": SCORE_ID}]}),
    ("notice_not_object", {"notices": ["x"]}),
    ("result_not_object", {"reported_result": "x"}),
    ("result_bad_id", {"reported_result": {"id": "nope", "is_original": True}}),
    ("result_flag", {"reported_result": {"id": RESULT_ID, "is_original": "yes"}}),
    (
        "version_coverage",
        {
            "reported_result": {
                "id": RESULT_ID,
                "is_original": True,
                "cache_version": {
                    "id": CV_ID,
                    "sha256": SHA,
                    "entry_count": 1,
                    "call_count": 1,
                    "coverage_status": "full",
                },
            }
        },
    ),
    (
        "version_sha",
        {
            "reported_result": {
                "id": RESULT_ID,
                "is_original": True,
                "cache_version": {
                    "id": CV_ID,
                    "sha256": "abc",
                    "entry_count": 1,
                    "call_count": 1,
                    "coverage_status": "partial",
                },
            }
        },
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("extra"), [e for _, e in _BAD_C4_BLOCKS], ids=[n for n, _ in _BAD_C4_BLOCKS]
)
async def test_a_malformed_c4_block_is_an_invalid_leaderboard_response(
    mode: Mode, extra: dict[str, object]
) -> None:
    wire = _Wire([_frozen()], [_stored(**extra)])

    async with _session(mode, wire) as submit:
        with pytest.raises(sf.LeaderboardError) as caught:
            await submit(_candidate())

    assert caught.value.code == "invalid_leaderboard"


def test_a_reported_result_with_no_cache_version_and_no_state_is_valid() -> None:
    result = sf.LeaderboardReportedResult(
        id=UUID(RESULT_ID),
        is_original=True,
        reporter=None,
        cache_version=None,
        publication_state=None,
    )

    assert result.cache_version is None
    assert result.publication_state is None


@pytest.mark.parametrize("state", ["private", "requested", "published", "failed", "withdrawn"])
def test_every_publication_state_of_the_erd_is_accepted(state: str) -> None:
    result = sf.LeaderboardReportedResult(
        id=UUID(RESULT_ID),
        is_original=True,
        reporter="ana",
        cache_version=None,
        publication_state=state,
    )

    assert result.publication_state == state


def _result(**over: Any) -> sf.LeaderboardReportedResult:
    fields: dict[str, Any] = {
        "id": UUID(RESULT_ID),
        "is_original": True,
        "reporter": None,
        "cache_version": None,
        "publication_state": None,
        **over,
    }
    return sf.LeaderboardReportedResult(**fields)


def _version(**over: Any) -> sf.LeaderboardCacheVersion:
    fields: dict[str, Any] = {
        "id": UUID(CV_ID),
        "sha256": SHA,
        "entry_count": 0,
        "call_count": 0,
        "coverage_status": "complete",
        **over,
    }
    return sf.LeaderboardCacheVersion(**fields)


@pytest.mark.parametrize(
    ("build", "error"),
    [
        (lambda: _result(id="x"), TypeError),
        (lambda: _result(is_original=1), TypeError),
        (lambda: _result(cache_version="x"), TypeError),
        (lambda: _result(publication_state="draft"), ValueError),
        (lambda: _result(reporter="  "), ValueError),
        (lambda: _version(id="x"), TypeError),
        (lambda: _version(sha256="ABC"), ValueError),
        (lambda: _version(entry_count=-1), ValueError),
        (lambda: _version(call_count=True), ValueError),
        (lambda: _version(coverage_status="full"), ValueError),
        (lambda: sf.LeaderboardNotice(code=" ", details={}), ValueError),
    ],
    ids=[
        "id",
        "flag",
        "version_type",
        "state",
        "reporter",
        "version_id",
        "sha",
        "entries",
        "calls_bool",
        "coverage",
        "notice_code",
    ],
)
def test_the_new_public_values_refuse_a_bad_field(
    build: Callable[[], object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        build()


def _score(**over: Any) -> sf.LeaderboardScore:
    return replace(_decode_score(_score_response()), **over)


@pytest.mark.parametrize(
    "over",
    [
        {"reported_result": "x"},
        {"reported_results_count": 0},
        {"notices": ("x",)},
        {"notices": "x"},
        {"cache_version_warning": "  "},
    ],
    ids=["result", "count", "notice_item", "notices_text", "warning"],
)
def test_a_score_refuses_a_bad_e14_field(over: dict[str, Any]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _score(**over)


def test_the_local_warning_is_not_part_of_score_equality() -> None:
    assert _score(cache_version_warning="cache_version_unavailable: timeout") == _score()
