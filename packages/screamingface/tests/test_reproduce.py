"""`sf.reproduce`: run a submitted score again from its cache version (E14 B5, R1-R11, R16, R20).

FEATURE: OME-1307 — `Client.reproduce(score)` runs the score's own url4 with its answer seed from
the cache version stored with it, judges the result against the stored numbers, and records an exact
reproduction on the board.
STORY: as someone who reads a leaderboard result, I rerun exactly that submission at no provider
cost and record that it reproduced, so I can trust and cite it. When it does not, I learn why.

The Engine (B3) and the board (B4) are faked: the run transport is a fake whose summary and result
are set per test, and the board is `httpx.MockTransport`.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from _isolation_engine import RunPlan, isolation_engine
from test_client_run import (
    REPLAY_URL4,
    _engine,
    _ForbiddenTransport,
    _ReplayTransport,
)
from test_leaderboards import SCORE_ID, SCOREBOARD_URL, _score_response

import screamingface as sf
from screamingface import _default_client
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.url4 import evaluate_url4_sync
from screamingface._reproduction import Reproduction, _classify
from screamingface.errors import EngineUnavailableError

LABEL = "cr-0123456789ab"
OLD_LABEL = "cr-aaaaaaaaaaaa"
RUN_ID = "replay-run"


def _score(**overrides: object) -> sf.LeaderboardScore:
    values: dict[str, Any] = {
        "id": UUID(SCORE_ID),
        "version": 1,
        "benchmark_id": "draco",
        "spec_id": "fusion/alpha",
        "url4": REPLAY_URL4,
        "submitted_by": "researcher@example.com",
        "submitted_at": datetime(2026, 10, 6, tzinfo=UTC),
        "score": 1.0,
        "total_questions": 1,
        "correct_questions": None,
        "ran_with_providers": ("openrouter",),
        "ran_at_local": None,
        "client_name": "screamingface",
        "client_version": "0.1.0",
        "client_platform": "darwin",
        "verified_by_screamingface": False,
        "metadata": None,
        "cache_revision": LABEL,
        "reproducible": "complete",
        "answer_seed": 7,
        "benchmark_revision": "fixture-revision",
    }
    return sf.LeaderboardScore(**{**values, **overrides})


def _failed_case(case_id: int, code: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "case_id": case_id,
        "input": f"Question {case_id}",
        "output": None,
        "finish_reason": None,
        "refusal": None,
        "stop_reason": None,
        "rounds_executed": None,
        "grade": None,
        "failures": [
            {
                "stage": "candidate",
                "code": code,
                "message": "a refusal",
                "retryable": False,
                "case_id": case_id,
                "metadata": {},
            }
        ],
        "metadata": {},
    }


def _failure(code: str) -> dict[str, Any]:
    return {
        "stage": "candidate",
        "code": code,
        "message": "the run failed",
        "retryable": False,
        "case_id": None,
        "metadata": {},
    }


class _Replayer(_ReplayTransport):
    """The replay fake: its result and its summary are set per test.

    `cases` is a list of `(case_id, failure_code)`; a None code is a scored case. By default the
    run is honoured, so its summary names the label the Candidate asked for.
    """

    def __init__(
        self,
        *,
        cases: Sequence[tuple[int, str | None]] = ((1, None),),
        score: float | None | str = "auto",
        benchmark_revision: str = "fixture-revision",
        failures: Sequence[dict[str, Any]] = (),
        honoured: bool = True,
    ) -> None:
        super().__init__()
        self._cases = cases
        self._score = score
        self._benchmark_revision = benchmark_revision
        self._failures = failures
        self._honoured = honoured
        self.runs = 0

    def run(self, candidate: Any, on_event: object) -> _RunOutcome:
        self.runs += 1
        outcome = super().run(candidate, on_event)
        assert outcome.result_body is not None
        body = json.loads(outcome.result_body)
        scored = copy.deepcopy(body["cases"][0])
        cases = [
            {**copy.deepcopy(scored), "case_id": case_id, "failures": []}
            if code is None
            else _failed_case(case_id, code)
            for case_id, code in self._cases
        ]
        scored_count = sum(1 for _, code in self._cases if code is None)
        body["cases"] = cases
        body["case_count"] = len(cases)
        body["benchmark_revision"] = self._benchmark_revision
        body["coverage"] = round(scored_count / len(cases), 4)
        body["score"] = (1.0 if scored_count else None) if self._score == "auto" else self._score
        if body["score"] is None:
            body["metrics"] = {}
        body["failures"] = list(self._failures)
        return replace(
            outcome,
            run_id=RUN_ID,
            result_body=json.dumps(body),
            cache_replay=candidate.cache_replay if self._honoured else None,
        )


class _AsyncReplayer(_Replayer):
    async def run(self, candidate: Any, on_event: object) -> _RunOutcome:  # type: ignore[override]
        return super().run(candidate, on_event)

    async def cancel_active(self) -> None:  # type: ignore[override]
        pass

    async def close(self) -> None:  # type: ignore[override]
        pass


class _AsyncForbidden:
    """An async run transport that fails the test when it is asked to run anything."""

    async def run(self, candidate: object, on_event: object) -> _RunOutcome:
        pytest.fail("a score that cannot be replayed started a run")

    async def cancel_active(self) -> None:
        pass

    async def close(self) -> None:
        pass


class _Board:
    """The scoreboard fake: serves one score and records every reproduction POST."""

    def __init__(
        self,
        *,
        record: Callable[[httpx.Request], httpx.Response] | None = None,
        score: dict[str, object] | None = None,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self._record = record or (lambda _: httpx.Response(201, json=RECORDED))
        self._score = score or _board_score()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST":
            return self._record(request)
        return httpx.Response(200, json=self._score)

    @property
    def posts(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "POST"]


RECORDED = {
    "id": "7c2e5b1a-0d44-4a60-9c3e-1d2f3a4b5c6d",
    "score_id": SCORE_ID,
    "reproduced_by": "reader@example.com",
    "reproduced_at": "2026-10-07T09:00:00Z",
    "run_id": RUN_ID,
    "cache_revision": LABEL,
    "client_version": "0.2.0",
}


def _board_score(**overrides: object) -> dict[str, object]:
    return {
        **_score_response(),
        "url4_expression": REPLAY_URL4,
        "score": 1.0,
        "total_questions": 1,
        "benchmark_revision": "fixture-revision",
        "cache_revision": LABEL,
        "reproducible": "complete",
        "answer_seed": 7,
        **overrides,
    }


def _client(transport: object, board: _Board | None = None) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(board or _Board()),
        run_transport=transport,  # type: ignore[arg-type]
    )


def _result(**changes: Any) -> sf.CandidateResult:
    report = evaluate_url4_sync(_Replayer(**changes), REPLAY_URL4, None, False)
    return report.candidates[0]


# --- R20 CHAR: one complete url4 loads the same cases -------------------------------------------


def test_two_runs_of_one_complete_url4_load_the_same_case_ids() -> None:
    first = _Replayer(cases=((3, None), (9, None)))
    second = _Replayer(cases=((3, None), (9, None)))

    ids = [
        [
            case.case_id
            for case in evaluate_url4_sync(fake, REPLAY_URL4, None, False).candidates[0].cases
        ]
        for fake in (first, second)
    ]

    assert ids[0] == ids[1] == [3, 9]
    assert first.candidate is not None and second.candidate is not None
    assert first.candidate.url4 == second.candidate.url4


# --- TDD #15: a score that cannot be replayed starts no run -------------------------------------


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"reproducible": "partial", "cache_revision": None}, "partial"),
        ({"reproducible": "partial"}, "partial"),
        ({"reproducible": None, "cache_revision": None}, "unknown"),
        # Q4: a `complete` score with no revision names nothing to replay from, and a run without
        # the header would be a paid run. An empty run therefore reads as unknown (accepted limit).
        ({"reproducible": "complete", "cache_revision": None}, "unknown"),
    ],
)
def test_a_partial_or_unknown_score_is_not_reproducible_and_starts_no_run(
    overrides: dict[str, object], reason: str
) -> None:
    board = _Board()
    with _client(_ForbiddenTransport(), board) as client:
        reproduction = client.reproduce(_score(**overrides))

    assert reproduction == Reproduction(outcome="not_reproducible", reason=reason)
    assert board.requests == []


@pytest.mark.asyncio
async def test_the_async_client_refuses_a_partial_score_without_running() -> None:
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(_Board()),
        run_transport=_AsyncForbidden(),
    )
    async with client:
        reproduction = await client.reproduce(_score(reproducible="partial"))

    assert (reproduction.outcome, reproduction.reason) == ("not_reproducible", "partial")


# --- TDD #16 / #20: the run is the score's own url4 and seed, replayed from its label -----------


def test_reproduce_runs_the_score_url4_with_its_seed_and_label_and_no_benchmark_or_limit() -> None:
    transport = _Replayer()
    with _client(transport) as client:
        reproduction = client.reproduce(_score())

    assert reproduction.outcome == "exact"
    candidate = transport.candidate
    assert candidate is not None
    assert candidate.url4 == REPLAY_URL4
    assert candidate.answer_seed == 7
    assert candidate.cache_replay == LABEL


def test_an_old_label_is_sent_verbatim() -> None:
    # R5: the replay uses the label stored with the score, not the gateway's current one.
    transport = _Replayer()
    with _client(transport) as client:
        reproduction = client.reproduce(_score(cache_revision=OLD_LABEL))

    assert reproduction.outcome == "exact"
    assert transport.candidate is not None
    assert transport.candidate.cache_replay == OLD_LABEL


def test_a_score_without_a_seed_replays_unseeded() -> None:
    transport = _Replayer()
    with _client(transport) as client:
        client.reproduce(_score(answer_seed=None))

    assert transport.candidate is not None
    assert transport.candidate.answer_seed is None


@pytest.mark.parametrize("how", ["uuid", "text"])
def test_a_score_id_is_fetched_from_the_board_first(how: str) -> None:
    board = _Board()
    transport = _Replayer()
    selected: UUID | str = UUID(SCORE_ID) if how == "uuid" else SCORE_ID
    with _client(transport, board) as client:
        reproduction = client.reproduce(selected)

    assert reproduction.outcome == "exact"
    assert board.requests[0].method == "GET"
    assert board.requests[0].url.path == f"/v1/scores/{SCORE_ID}"


def test_an_unknown_score_id_raises_as_get_score_does() -> None:
    client = sf.Client(
        engine_url="https://engine.example",
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(
            lambda _: httpx.Response(404, json={"detail": "x"})
        ),
        run_transport=_ForbiddenTransport(),  # type: ignore[arg-type]
    )

    with client, pytest.raises(sf.LeaderboardError) as raised:
        client.reproduce(SCORE_ID)

    assert raised.value.code == "unknown_score"


# --- TDD #17: the outcome table -----------------------------------------------------------------


def test_an_exact_replay_is_exact() -> None:
    assert _classify(_score(), _result()) == ("exact", None, ())


def test_a_replay_miss_names_the_cases_that_missed() -> None:
    result = _result(
        cases=((1, None), (2, "replay_cache_miss"), (3, "replay_cache_miss")), score=0.5
    )

    assert _classify(_score(total_questions=3), result) == ("failed", "cache_miss", (2, 3))


def test_an_unknown_cache_revision_is_its_own_reason() -> None:
    result = _result(cases=((1, "unknown_cache_revision"),), score=None)

    assert _classify(_score(), result) == ("failed", "unknown_cache_revision", ())


def test_a_candidate_level_failure_is_run_failed() -> None:
    result = _result(failures=[_failure("candidate_failed")])

    assert _classify(_score(), result) == ("failed", "run_failed", ())


def test_a_replay_code_outranks_a_run_failure() -> None:
    result = _result(
        cases=((1, "replay_cache_miss"),), score=None, failures=[_failure("candidate_failed")]
    )

    assert _classify(_score(), result)[:2] == ("failed", "cache_miss")


def test_a_changed_benchmark_revision_fails_before_the_score_is_compared() -> None:
    result = _result(benchmark_revision="newer-revision", score=0.25)

    assert _classify(_score(), result) == ("failed", "benchmark_revision_changed", ())


@pytest.mark.parametrize(
    ("result_changes", "stored"),
    [
        ({"score": 0.75}, {}),
        # One case more than the stored count: the same score, a different exam.
        ({"cases": ((1, None), (2, None))}, {"total_questions": 1}),
    ],
)
def test_a_different_score_or_case_count_is_score_differs(
    result_changes: dict[str, Any], stored: dict[str, Any]
) -> None:
    assert _classify(_score(**stored), _result(**result_changes)) == ("failed", "score_differs", ())


def test_the_score_is_compared_exactly() -> None:
    # R2 / K7: one ulp is a different result. The board never rounds it into agreement.
    assert _classify(_score(score=1.0), _result(score=1.0000000000000002))[1] == "score_differs"


def test_a_stored_score_without_a_benchmark_revision_cannot_match() -> None:
    # The plan compares revisions literally; an older board that omits it is never an exact match.
    assert _classify(_score(benchmark_revision=None), _result())[1] == "benchmark_revision_changed"


def test_the_client_returns_the_classified_failure_with_its_result_and_records_nothing() -> None:
    board = _Board()
    transport = _Replayer(cases=((1, "replay_cache_miss"),), score=None)
    with _client(transport, board) as client:
        reproduction = client.reproduce(_score())

    assert (reproduction.outcome, reproduction.reason) == ("failed", "cache_miss")
    assert reproduction.missed_cases == (1,)
    assert reproduction.result is not None
    assert (reproduction.recorded, reproduction.record_error) == (False, None)
    assert board.posts == []


# --- TDD #23 (SDK half): an Engine that did not replay -----------------------------------------


def test_a_summary_that_does_not_state_the_replay_is_replay_unsupported() -> None:
    board = _Board()
    with _client(_Replayer(honoured=False), board) as client:
        reproduction = client.reproduce(_score())

    assert reproduction == Reproduction(outcome="failed", reason="replay_unsupported")
    assert board.posts == []


def test_a_missing_start_echo_stops_the_run_and_is_replay_unsupported() -> None:
    # The real transport against a stub Engine that never echoes `X-Cache-Replay`: the older Engine.
    plans = {REPLAY_URL4: RunPlan()}
    board = _Board()
    with isolation_engine(plans) as engine:
        client = sf.Client(
            engine_url=engine.url,
            scoreboard_url=SCOREBOARD_URL,
            scoreboard_transport=httpx.MockTransport(board),
        )
        with client:
            reproduction = client.reproduce(_score())

        assert reproduction == Reproduction(outcome="failed", reason="replay_unsupported")
        assert len(engine.state.deleted) == 1, "the unacknowledged run was stopped"
    assert board.posts == []


def test_other_run_errors_propagate_as_they_do_from_evaluate() -> None:
    class _Down(_Replayer):
        def run(self, candidate: Any, on_event: object) -> _RunOutcome:
            raise EngineUnavailableError("down", engine_url="https://engine.example")

    with _client(_Down()) as client, pytest.raises(EngineUnavailableError):
        client.reproduce(_score())


# --- TDD #18: an exact replay is recorded once --------------------------------------------------


def test_an_exact_replay_is_recorded_once() -> None:
    board = _Board()
    with _client(_Replayer(), board) as client:
        reproduction = client.reproduce(_score())

    assert reproduction.outcome == "exact"
    assert (reproduction.recorded, reproduction.record_error) == (True, None)
    assert reproduction.result is not None
    (post,) = board.posts
    assert post.url.path == f"/v1/scores/{SCORE_ID}/reproductions"
    body = json.loads(post.read())
    assert {key: body[key] for key in ("run_id", "score", "total_questions", "cache_revision")} == {
        "run_id": RUN_ID,
        "score": 1.0,
        "total_questions": 1,
        "cache_revision": LABEL,
    }
    assert body["client"]["name"] == "screamingface"


def test_record_false_runs_and_judges_but_posts_nothing() -> None:
    board = _Board()
    with _client(_Replayer(), board) as client:
        reproduction = client.reproduce(_score(), record=False)

    assert reproduction.outcome == "exact"
    assert (reproduction.recorded, reproduction.record_error) == (False, None)
    assert board.posts == []


# --- TDD #19: a failed record keeps the exact outcome -------------------------------------------


@pytest.mark.parametrize(
    ("response", "text"),
    [
        (
            httpx.Response(409, json={"detail": {"code": "not_reproducible", "message": "m"}}),
            "not_reproducible: m",
        ),
        (
            httpx.Response(409, json={"detail": {"code": "run_id_conflict", "message": "m"}}),
            "run_id_conflict: m",
        ),
        (httpx.Response(409, json={"detail": "the board changed visibility"}), "visibility"),
        (
            httpx.Response(422, json={"detail": {"code": "not_exact", "message": "m"}}),
            "not_exact: m",
        ),
        (httpx.Response(401, json={"detail": "no identity"}), "no identity"),
        (httpx.Response(403, json={"detail": "untrusted peer"}), "untrusted peer"),
        (httpx.Response(503, json={"detail": "store unavailable"}), "store unavailable"),
    ],
)
def test_a_refused_record_keeps_exact_and_sets_record_error(
    response: httpx.Response, text: str
) -> None:
    board = _Board(record=lambda _: response)
    with _client(_Replayer(), board) as client:
        reproduction = client.reproduce(_score())

    assert reproduction.outcome == "exact"
    assert reproduction.recorded is False
    assert reproduction.record_error is not None
    assert text in reproduction.record_error


def test_an_unreachable_board_keeps_exact_and_does_not_raise() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    board = _Board(record=down)
    with _client(_Replayer(), board) as client:
        reproduction = client.reproduce(_score())

    assert (reproduction.outcome, reproduction.recorded) == ("exact", False)
    assert reproduction.record_error


# --- the async twin -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_async_client_reproduces_judges_and_records() -> None:
    board = _Board()
    transport = _AsyncReplayer()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(board),
        run_transport=transport,  # type: ignore[arg-type]
    )
    async with client:
        exact = await client.reproduce(SCORE_ID)
        missed = await client.reproduce(_score(), record=False)

    assert (exact.outcome, exact.recorded) == ("exact", True)
    assert missed.outcome == "exact"
    assert transport.candidate is not None
    assert (transport.candidate.cache_replay, transport.candidate.answer_seed) == (LABEL, 7)
    assert len(board.posts) == 1


@pytest.mark.asyncio
async def test_the_async_client_classifies_a_miss_and_survives_a_refused_record() -> None:
    missing = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(_Board()),
        run_transport=_AsyncReplayer(cases=((4, "replay_cache_miss"),), score=None),  # type: ignore[arg-type]
    )
    async with missing:
        miss = await missing.reproduce(_score())
    refused = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(
            _Board(record=lambda _: httpx.Response(422, json={"detail": "x"}))
        ),
        run_transport=_AsyncReplayer(),  # type: ignore[arg-type]
    )
    async with refused:
        kept = await refused.reproduce(_score())
    unsupported = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(_Board()),
        run_transport=_AsyncReplayer(honoured=False),  # type: ignore[arg-type]
    )
    async with unsupported:
        old = await unsupported.reproduce(_score())

    assert (miss.reason, miss.missed_cases) == ("cache_miss", (4,))
    assert (kept.outcome, kept.recorded) == ("exact", False)
    assert kept.record_error is not None
    assert old.reason == "replay_unsupported"


# --- the public face ----------------------------------------------------------------------------


def test_sf_reproduce_is_the_function_not_the_module() -> None:
    # The module is `_reproduction` so that loading it can never replace `sf.reproduce`.
    assert callable(sf.reproduce)
    assert not hasattr(sf.reproduce, "__path__")


def test_sf_reproduce_passes_through_to_the_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[object, bool]] = []
    sentinel = Reproduction(outcome="not_reproducible", reason="unknown")

    class _Fake:
        def reproduce(self, score: object, *, record: bool = True) -> Reproduction:
            seen.append((score, record))
            return sentinel

    monkeypatch.setattr(_default_client, "default_client", lambda: _Fake())

    assert sf.reproduce("score-id") is sentinel
    assert sf.reproduce("score-id", record=False) is sentinel
    assert seen == [("score-id", True), ("score-id", False)]


def test_reproduction_is_exported_frozen_with_defaults() -> None:
    reproduction = sf.Reproduction(outcome="exact")

    assert reproduction == Reproduction(outcome="exact")
    assert (reproduction.reason, reproduction.missed_cases, reproduction.result) == (None, (), None)
    assert (reproduction.recorded, reproduction.record_error) == (False, None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        reproduction.outcome = "failed"  # type: ignore[misc]
