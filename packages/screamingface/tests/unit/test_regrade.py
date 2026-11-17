"""`Client.regrade(score_id)`: move a published entry onto its Benchmark's current revision.

FEATURE: OME-1909 — a Benchmark's revision moved (its grading changed), so its old entries stop
ranking. A re-grader rebuilds the entry's url4 against the current catalogue (the Benchmark part
only; the Candidate part stays byte-identical), replays it from the entry's pinned cache with the
entry's own answer seed, and posts the result to `POST /v1/scores/{source}/regrades`.
STORY: as a ScreamingFace team member, I re-grade an old entry at no Candidate cost, and the new
entry is credited to its original submitter.

INVARIANT: no path here makes a Candidate model call. Every refusal (an unreadable score, a capture
that cannot be replayed, a revision that is current or not listed) happens before a run; a run with
any cache miss submits nothing; a re-grade is never judged as a reproduction nor recorded as one.

The Engine run is the `_Replayer` fake from `test_reproduce` (it records the Candidate it was
asked to run); the Engine catalogue and the board are `httpx.MockTransport` fakes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import UUID

import httpx
import pytest
from test_client_run import FUSION_CANDIDATE_URL4, _ForbiddenTransport
from test_leaderboards import SCORE_ID, SCOREBOARD_URL, _score_response
from test_reproduce import COPY, _AsyncReplayer, _Replayer
from url4 import RelExpr, build, expr, render, src, text

import screamingface as sf
from screamingface import _reproduction
from screamingface._core.ports import _RunOutcome
from screamingface._engine.catalog_contract import _benchmark_entry, _decode_benchmark
from screamingface._engine.transport import _start_async, _start_sync
from screamingface._evaluation.benchmark import _decode_benchmark_resource
from screamingface._evaluation.linking import _prepare_benchmark
from screamingface._evaluation.url4 import _candidate_text
from screamingface.errors import ExecutionError, LeaderboardError, PlanningError, ReproductionError

CASE_COUNT = 3
OLD_REVISION = "old-revision"
NEW_REVISION = "new-revision"
NEW_SCORE_ID = "3c9a1e57-2b4d-4f6a-8e1c-7d5b9a0c2e14"
PUBLIC_PATH = f"/v1/public/scores/{SCORE_ID}"
GATED_PATH = f"/v1/scores/{SCORE_ID}"
REGRADE_PATH = f"/v1/scores/{SCORE_ID}/regrades"


def _benchmark_url4(count: int, revision: str) -> str:
    """A Benchmark whose url4 names its revision and Case count, as the Engine's protocol does."""

    return render(
        expr(
            src(
                RelExpr(
                    path=f"/benchmarks/draco/{revision}/cases",
                    context="question",
                    intent=text("$candidate"),
                ),
                name="answer",
                weight=0.0,
            ),
            src(
                RelExpr(path="/provider/judge", context="$answer", intent=text("Grade.")),
                name="grade",
                weight=0.0,
            ),
            intent=text(f"aggregate:{count}"),
        )
    )


def _linked(benchmark_url4: str) -> str:
    """The evaluation url4 the SDK runs: the Benchmark bound to the Fusion Candidate."""

    return _prepare_benchmark(benchmark_url4).bind(FUSION_CANDIDATE_URL4).url4


# A Fusion entry (two members plus a synthesiser), published on the old revision.
PUBLISHED_URL4: str = _linked(_benchmark_url4(CASE_COUNT, OLD_REVISION))
REGRADED_URL4: str = _linked(_benchmark_url4(CASE_COUNT, NEW_REVISION))


def _source(**overrides: object) -> dict[str, object]:
    """The source score as the board serves it; a None override drops the field."""

    payload: dict[str, object] = {
        **_score_response(),
        "url4_expression": PUBLISHED_URL4,
        "score": 0.5,
        "total_questions": CASE_COUNT,
        "benchmark_revision": OLD_REVISION,
        "frozen_copy_id": COPY,
        "capture_status": "complete",
        "answer_seed": 7,
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def _created() -> dict[str, object]:
    """The new entry the board answers a re-grade with: credited to the source's submitter."""

    return _source(
        id=NEW_SCORE_ID,
        url4_expression=REGRADED_URL4,
        benchmark_revision=NEW_REVISION,
        frozen_copy_id=None,
        capture_status=None,
        score=1.0,
    )


class _Catalog:
    """The Engine's `/v1/benchmarks/draco` at the new revision, listing what it re-grades from."""

    def __init__(self, *, regradable_from: list[str] | None = None) -> None:
        # None: an Engine that predates the field and sends no key at all.
        self.regradable_from = regradable_from
        self.limits: list[int | None] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/benchmarks/draco"
        raw: str | None = request.url.params.get("limit")
        limit: int | None = None if raw is None else int(raw)
        self.limits.append(limit)
        count: int = CASE_COUNT if limit is None else limit
        body: dict[str, object] = {
            "schema": "screamingface.benchmark.v1",
            "id": "draco",
            "title": "DRACO",
            "description": "Fixture DRACO Benchmark.",
            "revision": NEW_REVISION,
            "case_count": CASE_COUNT,
            "selected_case_count": count,
            "url4": _benchmark_url4(count, NEW_REVISION),
        }
        if self.regradable_from is not None:
            body["regradable_from"] = self.regradable_from
        return httpx.Response(200, json=body)


class _Board:
    """Serves the source score's public and gated reads, and records every POST."""

    def __init__(
        self,
        *,
        public: dict[str, object] | None = None,
        gated: dict[str, object] | None = None,
        regrade: httpx.Response | None = None,
    ) -> None:
        self.public = public
        self.gated = gated
        self.regrade = regrade or httpx.Response(201, json=_created())
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.posts.append((request.url.path, json.loads(request.read())))
            # Any other POST (a reproduction record) is answered 500, so it cannot pass unseen.
            return (
                self.regrade
                if request.url.path == REGRADE_PATH
                else httpx.Response(500, json={"detail": "unexpected POST"})
            )
        body = {PUBLIC_PATH: self.public, GATED_PATH: self.gated}.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=body)


def _client(engine: object, catalog: _Catalog, board: _Board) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(catalog),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(board),
        run_transport=engine,  # type: ignore[arg-type]
    )


def _new_revision_replayer(**arguments: Any) -> _Replayer:
    """The Engine replaying all three Cases from the copy, reporting the new revision."""

    values: dict[str, Any] = {
        "cases": ((1, None), (2, None), (3, None)),
        "benchmark_revision": NEW_REVISION,
    }
    values.update(arguments)
    return _Replayer(**values)


@pytest.fixture(autouse=True)
def _never_judged_as_a_reproduction(monkeypatch: pytest.MonkeyPatch) -> None:
    """INVARIANT: a re-grade is not a reproduction; the verdict seam must never be reached."""

    def _refuse(*_: object) -> None:
        pytest.fail("a re-grade called the reproduction verdict")

    monkeypatch.setattr(_reproduction, "_classify", _refuse)


# --- the run ------------------------------------------------------------------------------------


def test_regrade_rebuilds_only_the_benchmark_part_of_a_fusion_url4() -> None:
    engine = _new_revision_replayer()
    catalog = _Catalog(regradable_from=[OLD_REVISION])

    with _client(engine, catalog, _Board(public=_source())) as client:
        client.regrade(SCORE_ID, progress=False)

    assert engine.candidate is not None
    # The Candidate part (two members plus a synthesiser) is the published text, byte for byte.
    assert _candidate_text(build(engine.candidate.url4)) == FUSION_CANDIDATE_URL4
    assert _candidate_text(build(engine.candidate.url4)) == _candidate_text(build(PUBLISHED_URL4))
    # Only the Benchmark part moved: the run is the current catalogue's url4, bound to it.
    assert engine.candidate.url4 == REGRADED_URL4
    assert engine.candidate.url4 != PUBLISHED_URL4
    # The current resource is read once, at the published Case count.
    assert catalog.limits == [CASE_COUNT]


def test_regrade_replays_with_the_published_seed_and_pinned_cache_and_never_captures() -> None:
    engine = _new_revision_replayer()
    board = _Board(public=_source(answer_seed=0))

    with _client(engine, _Catalog(regradable_from=[OLD_REVISION]), board) as client:
        client.regrade(SCORE_ID, progress=False)

    assert engine.runs == 1
    assert engine.candidate is not None
    # 0 is a seed (a `is not None` check), and a seed that is not the captured one misses the copy.
    assert engine.candidate.answer_seed == 0
    assert engine.candidate.replay_frozen_copy == COPY
    assert engine.candidate.capture is False
    assert engine.candidate.replay_live_judge is None
    # Nothing is recorded as a reproduction; the only POST is the re-grade itself.
    assert [path for path, _ in board.posts] == [REGRADE_PATH]


def test_regrade_posts_to_the_regrades_route_of_the_source_score() -> None:
    board = _Board(public=_source())

    with _client(_new_revision_replayer(), _Catalog(regradable_from=[OLD_REVISION]), board) as c:
        created = c.regrade(UUID(SCORE_ID), progress=False)

    ((path, body),) = board.posts
    assert path == REGRADE_PATH
    # The normal submission body, built from the replayed result at the new revision.
    assert body["benchmark_id"] == "draco"
    assert body["url4_expression"] == REGRADED_URL4
    assert body["total_questions"] == CASE_COUNT
    assert body["metadata"]["benchmark_revision"] == NEW_REVISION
    # WHY no authors: the board credits the source's submitter and authors, not the re-grader.
    assert "authors" not in body
    assert isinstance(created, sf.LeaderboardScore)
    assert created.id == UUID(NEW_SCORE_ID)
    assert created.benchmark_revision == NEW_REVISION


@pytest.mark.parametrize("stage", ["candidate", "grading"])
def test_one_cache_miss_refuses_the_whole_regrade_and_submits_nothing(stage: str) -> None:
    engine = _StagedMiss(stage, cases=((1, None), (2, "frozen_copy_miss"), (3, None)))
    board = _Board(public=_source())

    with _client(engine, _Catalog(regradable_from=[OLD_REVISION]), board) as client:
        with pytest.raises(ExecutionError) as caught:
            client.regrade(SCORE_ID, progress=False)

    assert caught.value.code == "regrade_incomplete"
    assert caught.value.permanent is True
    # No partial score: two of three Cases replayed, and still nothing reaches the board.
    assert board.posts == []


class _StagedMiss(_Replayer):
    """The replay fake, its failed Cases' failures moved to one stage (a judge call missing)."""

    def __init__(self, stage: str, **arguments: Any) -> None:
        super().__init__(benchmark_revision=NEW_REVISION, **arguments)
        self._stage = stage

    def run(self, candidate: Any, on_event: object) -> _RunOutcome:
        outcome = super().run(candidate, on_event)
        assert outcome.result_body is not None
        body: dict[str, Any] = json.loads(outcome.result_body)
        for case in body["cases"]:
            for failure in case["failures"]:
                failure["stage"] = self._stage
        return replace(outcome, result_body=json.dumps(body))


# --- refusals before any run ------------------------------------------------------------------


def test_regrade_refuses_an_entry_already_on_the_current_revision() -> None:
    board = _Board(public=_source(benchmark_revision=NEW_REVISION))

    with _client(_ForbiddenTransport(), _Catalog(regradable_from=[OLD_REVISION]), board) as c:
        with pytest.raises(PlanningError) as caught:
            c.regrade(SCORE_ID)

    assert caught.value.code == "already_current"
    assert board.posts == []


@pytest.mark.parametrize(
    "regradable_from",
    [[], ["another-revision"], None],
    ids=["empty", "other-revision", "older-engine-sends-no-key"],
)
def test_regrade_refuses_a_revision_the_benchmark_does_not_list(
    regradable_from: list[str] | None,
) -> None:
    board = _Board(public=_source())

    with _client(_ForbiddenTransport(), _Catalog(regradable_from=regradable_from), board) as c:
        with pytest.raises(PlanningError) as caught:
            c.regrade(SCORE_ID)

    assert caught.value.code == "not_regradable"
    assert board.posts == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"capture_status": "partial"}, "partial"),
        ({"frozen_copy_id": None, "capture_status": None}, "unknown"),
        ({"benchmark_revision": None}, "unknown"),
    ],
    ids=["partial-capture", "no-pinned-cache", "no-revision"],
)
def test_regrade_refuses_a_partial_capture_before_any_run(
    overrides: dict[str, object], reason: str
) -> None:
    catalog = _Catalog(regradable_from=[OLD_REVISION])
    board = _Board(public=_source(**overrides))

    with _client(_ForbiddenTransport(), catalog, board) as client:
        with pytest.raises(ReproductionError) as caught:
            client.regrade(SCORE_ID)

    assert caught.value.code == "not_reproducible"
    assert caught.value.reproduction.reason == reason
    # Refused from the score alone: not even the catalogue is read.
    assert catalog.limits == []
    assert board.posts == []


def test_a_private_score_the_caller_cannot_read_is_refused() -> None:
    # The public read and the gated read both answer 404: a private score of someone else.
    catalog = _Catalog(regradable_from=[OLD_REVISION])
    board = _Board()

    with _client(_ForbiddenTransport(), catalog, board) as client:
        with pytest.raises(LeaderboardError) as caught:
            client.regrade(SCORE_ID)

    # The board's own 404, never a silent skip.
    assert (caught.value.code, caught.value.status) == ("unknown_score", 404)
    assert catalog.limits == []
    assert board.posts == []


# --- the live-judge header --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("live_judge", "sent"),
    [(None, None), ("all", "all"), (["3", "1", "1"], "1,3"), ((" 12 ",), "12")],
    ids=["not-asked", "all", "ids-sorted-unique", "trimmed"],
)
def test_live_judge_sends_the_header_only_when_asked(live_judge: Any, sent: str | None) -> None:
    engine = _new_revision_replayer()

    with _client(engine, _Catalog(regradable_from=[OLD_REVISION]), _Board(public=_source())) as c:
        c.regrade(SCORE_ID, live_judge=live_judge, progress=False)

    assert engine.candidate is not None
    # The canonical text the Engine echoes back: `all`, or the sorted unique ids.
    assert engine.candidate.replay_live_judge == sent
    assert engine.candidate.replay_frozen_copy == COPY


@pytest.mark.parametrize(
    ("live_judge", "error"),
    [
        ([], ValueError),
        ([""], ValueError),
        (["1", " "], ValueError),
        (["ALL"], ValueError),
        (["all", "3"], ValueError),
        (["1,2"], ValueError),
        ("3", TypeError),
        ([3], TypeError),
        ("ALL", TypeError),
    ],
)
def test_a_malformed_live_judge_is_refused_before_any_request(
    live_judge: Any, error: type[Exception]
) -> None:
    catalog = _Catalog(regradable_from=[OLD_REVISION])
    board = _Board(public=_source())

    with _client(_ForbiddenTransport(), catalog, board) as client:
        with pytest.raises(error):
            client.regrade(SCORE_ID, live_judge=live_judge)

    assert catalog.limits == []


TOKEN = "cap-token"
START_URL4 = "(@)!'go'"


def _start_http(seen: list[httpx.Request], *, live_echo: str | None) -> httpx.Client:
    """An Engine start route that honours the copy and echoes `live_echo`, or no live set."""

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        headers: dict[str, str] = {
            "Preference-Applied": "respond-async",
            "Location": "/runs/1",
            "X-Replay-Frozen-Copy": COPY,
        }
        if live_echo is not None:
            headers["X-Replay-Live-Judge"] = live_echo
        return httpx.Response(202, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handle), base_url="https://engine.test")


def test_the_start_sends_the_live_judge_header_beside_the_copy_only_when_asked() -> None:
    seen: list[httpx.Request] = []

    _start_sync(
        _start_http(seen, live_echo="1,3"),
        TOKEN,
        START_URL4,
        replay_frozen_copy=COPY,
        replay_live_judge="1,3",
    )
    _start_sync(_start_http(seen, live_echo=None), TOKEN, START_URL4, replay_frozen_copy=COPY)

    assert seen[0].headers["X-Replay-Live-Judge"] == "1,3"
    assert seen[0].headers["X-Replay-Frozen-Copy"] == COPY
    assert "X-Replay-Live-Judge" not in seen[1].headers


@pytest.mark.parametrize("echo", [None, "1", "all"], ids=["older-engine", "other-ids", "other"])
def test_an_engine_that_does_not_echo_the_live_judges_is_refused(echo: str | None) -> None:
    # WHY refused (OME-1909): an older Engine ignores the header and replays every judge, so the
    # "re-judge" would silently hand back the old grades. The code is the replay one, so the
    # transport stops the run it just started, as it does for an unacknowledged copy.
    with pytest.raises(ExecutionError) as caught:
        _start_sync(
            _start_http([], live_echo=echo),
            TOKEN,
            START_URL4,
            replay_frozen_copy=COPY,
            replay_live_judge="1,3",
        )

    assert caught.value.code == "replay_unsupported"


@pytest.mark.asyncio
async def test_the_async_start_checks_the_live_judge_echo_too() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            headers={
                "Preference-Applied": "respond-async",
                "Location": "/runs/1",
                "X-Replay-Frozen-Copy": COPY,
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="https://engine.test"
    ) as http:
        with pytest.raises(ExecutionError) as caught:
            await _start_async(
                http, TOKEN, START_URL4, replay_frozen_copy=COPY, replay_live_judge="all"
            )

    assert caught.value.code == "replay_unsupported"


# --- the board's refusals ---------------------------------------------------------------------


def test_a_second_regrade_of_one_source_names_the_existing_regrade() -> None:
    existing = "9d8c7b6a-5f4e-4d3c-8b2a-1f0e9d8c7b6a"
    refusal = httpx.Response(
        409,
        json={
            "detail": {
                "code": "already_regraded",
                "message": "this score has already been re-graded",
                "existing_score_id": existing,
            }
        },
    )
    board = _Board(public=_source(), regrade=refusal)

    with _client(_new_revision_replayer(), _Catalog(regradable_from=[OLD_REVISION]), board) as c:
        with pytest.raises(LeaderboardError) as caught:
            c.regrade(SCORE_ID, progress=False)

    # A batch caller treats this source as done: the re-grade it would have made exists.
    assert caught.value.code == "already_regraded"
    assert caught.value.existing_score_id == UUID(existing)
    assert caught.value.permanent is True


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (403, "regrade_unavailable"),
        (403, "not_allowed"),
        (409, "not_current_revision"),
        (409, "already_on_board"),
        (422, "different_benchmark"),
    ],
)
def test_the_boards_coded_refusals_keep_their_codes(status: int, code: str) -> None:
    refusal = httpx.Response(status, json={"detail": {"code": code, "message": "refused"}})
    board = _Board(public=_source(), regrade=refusal)

    with _client(_new_revision_replayer(), _Catalog(regradable_from=[OLD_REVISION]), board) as c:
        with pytest.raises(LeaderboardError) as caught:
            c.regrade(SCORE_ID, progress=False)

    assert (caught.value.code, caught.value.status) == (code, status)
    assert caught.value.existing_score_id is None
    assert caught.value.permanent is True


def test_a_visibility_change_mid_regrade_is_retryable() -> None:
    # A string `detail` on a 409: the board changed under the request; a retry sees one view.
    refusal = httpx.Response(409, json={"detail": "the board's visibility changed; retry"})
    board = _Board(public=_source(), regrade=refusal)

    with _client(_new_revision_replayer(), _Catalog(regradable_from=[OLD_REVISION]), board) as c:
        with pytest.raises(LeaderboardError) as caught:
            c.regrade(SCORE_ID, progress=False)

    assert caught.value.code == "regrade_conflict"
    assert caught.value.retryable is True


# --- the async twin -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_async_regrade_matches_the_sync_one() -> None:
    engine = _AsyncReplayer(
        cases=((1, None), (2, None), (3, None)), benchmark_revision=NEW_REVISION
    )
    board = _Board(public=_source())
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_Catalog(regradable_from=[OLD_REVISION])),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(board),
        run_transport=engine,  # type: ignore[arg-type]
    )

    async with client:
        created = await client.regrade(SCORE_ID, live_judge=["2"], progress=False)

    assert engine.candidate is not None
    assert engine.candidate.url4 == REGRADED_URL4
    assert (engine.candidate.replay_frozen_copy, engine.candidate.answer_seed) == (COPY, 7)
    assert engine.candidate.replay_live_judge == "2"
    assert [path for path, _ in board.posts] == [REGRADE_PATH]
    assert created.id == UUID(NEW_SCORE_ID)


@pytest.mark.asyncio
async def test_the_async_regrade_refuses_a_cache_miss_too() -> None:
    engine = _AsyncReplayer(
        cases=((1, None), (2, "frozen_copy_miss")), benchmark_revision=NEW_REVISION
    )
    board = _Board(public=_source())
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_Catalog(regradable_from=[OLD_REVISION])),
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(board),
        run_transport=engine,  # type: ignore[arg-type]
    )

    async with client:
        with pytest.raises(ExecutionError) as caught:
            await client.regrade(SCORE_ID, progress=False)

    assert caught.value.code == "regrade_incomplete"
    assert board.posts == []


# --- the catalogue field ----------------------------------------------------------------------


def _entry_row(**extra: object) -> dict[str, object]:
    """One catalogue listing row, as the Engine serves it."""

    return {
        "object": "benchmark",
        "id": "draco",
        "title": "DRACO",
        "description": "Fixture DRACO Benchmark.",
        "revision": NEW_REVISION,
        "case_count": CASE_COUNT,
        **extra,
    }


def test_the_catalogue_reads_the_revisions_a_benchmark_regrades_from() -> None:
    listed = _benchmark_entry(_entry_row(regradable_from=[OLD_REVISION]))
    # WHY absent is empty: an older Engine sends no key, and reads as "nothing regradable".
    older = _benchmark_entry(_entry_row())

    assert listed.regradable_from == (OLD_REVISION,)
    assert older.regradable_from == ()


@pytest.mark.parametrize("value", ["old-revision", [""], [3], {"old": True}])
def test_a_malformed_regradable_from_is_the_engines_contract_error(value: object) -> None:
    # The catalogue read by id wraps the entry decoder's refusal as the Engine's contract error.
    with pytest.raises(PlanningError) as listed:
        _decode_benchmark(_entry_row(regradable_from=value), "draco")
    assert listed.value.code == "invalid_catalogue"
    resource: dict[str, object] = {
        "schema": "screamingface.benchmark.v1",
        "id": "draco",
        "title": "DRACO",
        "description": "Fixture DRACO Benchmark.",
        "revision": NEW_REVISION,
        "case_count": CASE_COUNT,
        "url4": _benchmark_url4(CASE_COUNT, NEW_REVISION),
        "regradable_from": value,
    }
    with pytest.raises(PlanningError) as caught:
        _decode_benchmark_resource(resource, requested_id="draco", requested_limit=None)

    assert caught.value.code == "invalid_benchmark_resource"
