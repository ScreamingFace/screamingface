"""`sf.evaluate(pinned_cache=…)` / `sf.evaluate(score_id=…)`: replay a published run (OME-1613).

FEATURE: OME-1613 (spec §2–§5) — the published score is found, every argument is checked before
any run, the run replays from the pinned cache at $0, the result is judged against the published
numbers, and an exact replay is recorded on the board.
STORY: as a researcher, I replay a published run with one id and learn whether it reproduces; as
its owner, I replay a private one; with only a url4 and seed, I replay an unsubmitted capture.

The Engine is the `_Replayer` fake from `test_reproduce`; the board is `httpx.MockTransport`.
Every assertion is on parsed fields or error codes, never on message text.
"""

from __future__ import annotations

import json
import warnings
from typing import Any

import httpx
import pytest
from test_client_run import REPLAY_URL4, _engine, _ForbiddenTransport
from test_leaderboards import SCORE_ID, SCOREBOARD_URL, _score_response
from test_reproduce import COPY, OLD_COPY, RECORDED, _AsyncReplayer, _Replayer
from url4 import build, expr, render, src, text

import screamingface as sf
from screamingface._evaluation.url4 import _candidate_text
from screamingface._replay import replay_async, replay_sync

LOOKUP_PATH = f"/v1/public/scores/by-pinned-cache/{COPY}"
PUBLIC_PATH = f"/v1/public/scores/{SCORE_ID}"
GATED_PATH = f"/v1/scores/{SCORE_ID}"
RECORD_PATH = f"/v1/scores/{SCORE_ID}/reproductions"


def _lookup(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "score_id": SCORE_ID,
        "benchmark_id": "draco",
        "benchmark_revision": "fixture-revision",
        "url4_expression": REPLAY_URL4,
        "answer_seed": 7,
        "score": 1.0,
        "total_questions": 1,
        "capture_status": "complete",
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def _score(**overrides: object) -> dict[str, object]:
    payload = {
        **_score_response(),
        "url4_expression": REPLAY_URL4,
        "score": 1.0,
        "total_questions": 1,
        "benchmark_revision": "fixture-revision",
        "frozen_copy_id": COPY,
        "capture_status": "complete",
        "answer_seed": 7,
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


class _Board:
    """Serves the lookup, the public and gated score reads, and records reproduction POSTs."""

    def __init__(
        self,
        *,
        lookup: dict[str, object] | None = None,
        public: dict[str, object] | None = None,
        gated: dict[str, object] | None = None,
        record: int = 201,
    ) -> None:
        self.lookup = lookup
        self.public = public
        self.gated = gated
        self.record = record
        self.requests: list[tuple[str, str]] = []
        self.posted: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        answers = {LOOKUP_PATH: self.lookup, PUBLIC_PATH: self.public, GATED_PATH: self.gated}
        if request.method == "POST" and request.url.path == RECORD_PATH:
            self.posted.append(json.loads(request.read()))
            return httpx.Response(self.record, json=RECORDED)
        body = answers.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=body)


def _client(transport: object, board: _Board) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(board),
        run_transport=transport,  # type: ignore[arg-type]
    )


def _async_client(transport: object, board: _Board) -> sf.AsyncClient:
    return sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(board),
        run_transport=transport,  # type: ignore[arg-type]
    )


def _replay(client: sf.Client, **arguments: Any) -> sf.Report:
    values: dict[str, Any] = {
        "pinned_cache": None,
        "score_id": None,
        "url4": None,
        "answer_seed": None,
        "record_reproduction": True,
        "on_event": None,
        "progress": False,
    }
    values.update(arguments)
    return replay_sync(client, **values)


# --- the happy path ---------------------------------------------------------------------------


def test_a_pinned_cache_replay_is_exact_and_recorded() -> None:
    engine = _Replayer()
    board = _Board(lookup=_lookup())

    with _client(engine, board) as client:
        report = _replay(client, pinned_cache=COPY)

    (result,) = report.candidates
    assert result.reproduction is not None
    assert (result.reproduction.outcome, result.reproduction.recorded) == ("exact", True)
    assert engine.candidate is not None
    assert (engine.candidate.replay_frozen_copy, engine.candidate.capture) == (COPY, False)
    assert engine.candidate.answer_seed == 7
    assert board.requests[0] == ("GET", LOOKUP_PATH)
    assert [body["frozen_copy_id"] for body in board.posted] == [COPY]


def test_record_reproduction_false_records_nothing() -> None:
    board = _Board(lookup=_lookup())

    with _client(_Replayer(), board) as client:
        report = _replay(client, pinned_cache=COPY, record_reproduction=False)

    reproduction = report.candidates[0].reproduction
    assert reproduction is not None
    assert (reproduction.outcome, reproduction.recorded) == ("exact", False)
    assert board.posted == []


def test_a_failed_replay_is_not_recorded_and_says_why() -> None:
    board = _Board(lookup=_lookup(score=0.5))

    with _client(_Replayer(), board) as client:
        report = _replay(client, pinned_cache=COPY)

    reproduction = report.candidates[0].reproduction
    assert reproduction is not None
    assert (reproduction.outcome, reproduction.reason) == ("failed", "score_differs")
    assert board.posted == []


def test_a_copy_miss_names_the_missed_cases() -> None:
    engine = _Replayer(cases=((1, None), (2, "frozen_copy_miss")))
    board = _Board(lookup=_lookup(total_questions=2))

    with _client(engine, board) as client:
        report = _replay(client, pinned_cache=COPY)

    reproduction = report.candidates[0].reproduction
    assert reproduction is not None
    assert (reproduction.outcome, reproduction.reason) == ("failed", "frozen_copy_miss")
    assert reproduction.missed_cases == (2,)


def test_a_record_failure_never_fails_the_replay() -> None:
    board = _Board(lookup=_lookup(), record=503)

    with _client(_Replayer(), board) as client:
        report = _replay(client, pinned_cache=COPY)

    reproduction = report.candidates[0].reproduction
    assert reproduction is not None
    assert (reproduction.outcome, reproduction.recorded) == ("exact", False)
    assert reproduction.record_error is not None


# --- seeds with a published score (spec §4a rows 1-6) -------------------------------------------


@pytest.mark.parametrize(
    ("board_seed", "passed", "stamped"),
    [(7, None, 7), (7, 7, 7), (None, None, None), (0, None, 0)],
    ids=["row1-board-seed", "row2-same-seed", "row4-no-seed", "row6-zero-is-a-seed"],
)
def test_the_replay_uses_the_published_seed(
    board_seed: int | None, passed: int | None, stamped: int | None
) -> None:
    engine = _Replayer()
    lookup = _lookup()
    lookup.pop("answer_seed")
    if board_seed is not None:
        lookup["answer_seed"] = board_seed

    with _client(engine, _Board(lookup=lookup)) as client:
        _replay(client, pinned_cache=COPY, answer_seed=passed)

    assert engine.candidate is not None
    assert engine.candidate.answer_seed == stamped


@pytest.mark.parametrize(
    ("board_seed", "passed"),
    [(7, 3), (None, 3)],
    ids=["row3-other-seed", "row5-seed-for-a-seedless-run"],
)
def test_a_seed_that_disagrees_fails_before_any_run(board_seed: int | None, passed: int) -> None:
    lookup = _lookup()
    lookup.pop("answer_seed")
    if board_seed is not None:
        lookup["answer_seed"] = board_seed

    with _client(_ForbiddenTransport(), _Board(lookup=lookup)) as client:
        with pytest.raises(ValueError):
            _replay(client, pinned_cache=COPY, answer_seed=passed)


# --- the recipe (spec §3, Q2) -----------------------------------------------------------------


def test_the_same_recipe_with_other_spacing_is_accepted() -> None:
    engine = _Replayer()
    spaced = f"  {REPLAY_URL4}\n"

    with _client(engine, _Board(lookup=_lookup())) as client:
        _replay(client, pinned_cache=COPY, url4=spaced)

    assert engine.runs == 1


@pytest.mark.parametrize("url4", ["/benchmarks/other/revision/run()", "(@ not url4"])
def test_another_or_broken_recipe_fails_before_any_run(url4: str) -> None:
    with _client(_ForbiddenTransport(), _Board(lookup=_lookup())) as client:
        with pytest.raises(ValueError):
            _replay(client, pinned_cache=COPY, url4=url4)


# --- captures that cannot be replayed (Q14) -------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"capture_status": "partial"}, "partial"),
        ({"capture_status": None}, "unknown"),
        ({"benchmark_revision": None}, "unknown"),
    ],
)
def test_a_capture_that_cannot_be_replayed_raises_before_any_run(
    overrides: dict[str, object], reason: str
) -> None:
    with _client(_ForbiddenTransport(), _Board(lookup=_lookup(**overrides))) as client:
        with pytest.raises(sf.ReproductionError) as caught:
            _replay(client, pinned_cache=COPY)

    assert caught.value.code == "not_reproducible"
    assert caught.value.reproduction.reason == reason


def test_an_engine_that_ignores_the_replay_raises_replay_unsupported() -> None:
    with _client(_Replayer(honoured=False), _Board(lookup=_lookup())) as client:
        with pytest.raises(sf.ReproductionError) as caught, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _replay(client, pinned_cache=COPY)

    assert caught.value.code == "replay_unsupported"
    assert caught.value.reproduction.outcome == "failed"


# --- score_id (spec §2, Q3, Q8) -----------------------------------------------------------------


def test_a_score_id_alone_reads_the_public_score_and_its_copy() -> None:
    engine = _Replayer()
    board = _Board(public=_score())

    with _client(engine, board) as client:
        report = _replay(client, score_id=SCORE_ID)

    assert ("GET", LOOKUP_PATH) not in board.requests
    assert board.requests[0] == ("GET", PUBLIC_PATH)
    assert engine.candidate is not None
    assert engine.candidate.replay_frozen_copy == COPY
    reproduction = report.candidates[0].reproduction
    assert reproduction is not None and reproduction.outcome == "exact"


def test_a_private_score_is_read_through_the_gated_route() -> None:
    board = _Board(gated=_score())

    with _client(_Replayer(), board) as client:
        report = _replay(client, score_id=SCORE_ID)

    assert board.requests[:2] == [("GET", PUBLIC_PATH), ("GET", GATED_PATH)]
    reproduction = report.candidates[0].reproduction
    assert reproduction is not None and reproduction.outcome == "exact"


def test_a_score_id_whose_copy_differs_fails_before_any_run() -> None:
    board = _Board(public=_score(frozen_copy_id=OLD_COPY))

    with _client(_ForbiddenTransport(), board) as client:
        with pytest.raises(ValueError):
            _replay(client, score_id=SCORE_ID, pinned_cache=COPY)


# --- no published score (S4, spec §4a rows 7-11) ------------------------------------------------


def test_an_unsubmitted_capture_replays_with_no_verdict() -> None:
    engine = _Replayer()
    board = _Board()

    with _client(engine, board) as client:
        report = _replay(client, pinned_cache=COPY, url4=REPLAY_URL4, answer_seed=7)

    assert report.candidates[0].reproduction is None
    assert engine.candidate is not None
    assert (engine.candidate.replay_frozen_copy, engine.candidate.answer_seed) == (COPY, 7)
    assert board.posted == []


def test_an_unsubmitted_capture_without_a_url4_fails_before_any_run() -> None:
    with _client(_ForbiddenTransport(), _Board()) as client:
        with pytest.raises(ValueError):
            _replay(client, pinned_cache=COPY)


def test_every_case_missing_on_the_s4_path_warns_about_the_seed() -> None:
    engine = _Replayer(cases=((1, "frozen_copy_miss"), (2, "frozen_copy_miss")), score=None)

    with _client(engine, _Board()) as client:
        with pytest.warns(sf.EvaluationWarning) as caught:
            _replay(client, pinned_cache=COPY, url4=REPLAY_URL4, answer_seed=7)

    assert len(caught) == 1


@pytest.mark.parametrize(
    "cases",
    [((1, None), (2, "frozen_copy_miss")), ((1, None),)],
    ids=["some-cases-missed", "nothing-missed"],
)
def test_no_seed_warning_unless_every_case_missed(
    cases: tuple[tuple[int, str | None], ...],
) -> None:
    with _client(_Replayer(cases=cases), _Board()) as client:
        with warnings.catch_warnings():
            warnings.simplefilter("error", sf.EvaluationWarning)
            _replay(client, pinned_cache=COPY, url4=REPLAY_URL4)


def test_a_published_score_never_gets_the_s4_warning() -> None:
    engine = _Replayer(cases=((1, "frozen_copy_miss"),), score=None)

    with _client(engine, _Board(lookup=_lookup())) as client:
        with warnings.catch_warnings():
            warnings.simplefilter("error", sf.EvaluationWarning)
            report = _replay(client, pinned_cache=COPY)

    reproduction = report.candidates[0].reproduction
    assert reproduction is not None and reproduction.reason == "frozen_copy_miss"


# --- arguments ---------------------------------------------------------------------------------


def test_a_malformed_pinned_cache_fails_before_any_request() -> None:
    board = _Board()

    with _client(_ForbiddenTransport(), board) as client:
        with pytest.raises(ValueError):
            _replay(client, pinned_cache="not-a-uuid")

    assert board.requests == []


def test_a_replay_needs_a_pinned_cache_or_a_score_id() -> None:
    with _client(_ForbiddenTransport(), _Board()) as client:
        with pytest.raises(TypeError):
            _replay(client)


# --- INVARIANT: a replay never runs without the replay header -----------------------------------


@pytest.mark.parametrize(
    "arguments",
    [
        {"pinned_cache": COPY},
        {"score_id": SCORE_ID},
        {"pinned_cache": COPY, "url4": REPLAY_URL4},
    ],
)
def test_every_replay_path_sends_the_pinned_cache(arguments: dict[str, Any]) -> None:
    engine = _Replayer()
    board = _Board(lookup=_lookup(), public=_score())

    with _client(engine, board) as client:
        _replay(client, **arguments)

    assert engine.candidate is not None
    assert engine.candidate.replay_frozen_copy == COPY
    assert engine.candidate.capture is False


# --- async ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_async_replay_matches_the_sync_replay() -> None:
    board = _Board(lookup=_lookup())

    async with _async_client(_AsyncReplayer(), board) as client:
        report = await replay_async(
            client,
            pinned_cache=COPY,
            score_id=None,
            url4=None,
            answer_seed=None,
            record_reproduction=True,
            on_event=None,
            progress=False,
        )

    reproduction = report.candidates[0].reproduction
    assert reproduction is not None
    assert (reproduction.outcome, reproduction.recorded) == ("exact", True)


# --- review fixes 3 and 4 ---------------------------------------------------------------------


def test_the_s4_warning_points_at_the_callers_line() -> None:
    engine = _Replayer(cases=((1, "frozen_copy_miss"),), score=None)

    with _client(engine, _Board()) as client:
        with pytest.warns(sf.EvaluationWarning) as caught:
            client.evaluate(pinned_cache=COPY, url4=REPLAY_URL4, progress=False)

    assert [warning.filename for warning in caught] == [__file__]


def test_the_embedded_recipe_is_compared_as_a_parsed_recipe_too() -> None:
    engine = _Replayer()
    candidate = _candidate_text(build(REPLAY_URL4))
    spaced = render(
        expr(
            src(text(f"  {candidate}  "), name="candidate", weight=0.0),
            src("fixture", name="result", weight=0.0),
            intent=text("$result"),
        )
    )
    assert spaced != REPLAY_URL4

    with _client(engine, _Board(lookup=_lookup())) as client:
        _replay(client, pinned_cache=COPY, url4=spaced)

    assert engine.runs == 1


def test_a_published_url4_that_does_not_parse_is_a_value_error() -> None:
    with _client(_ForbiddenTransport(), _Board(lookup=_lookup(url4_expression="(@ broken"))) as c:
        with pytest.raises(ValueError):
            _replay(c, pinned_cache=COPY, url4=REPLAY_URL4)
