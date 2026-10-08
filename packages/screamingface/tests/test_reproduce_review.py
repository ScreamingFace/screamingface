"""B5 design-review round: realistic replay failures, the replay's own numbers, and the spine.

FEATURE: OME-1307 — what `reproduce` does with the outputs a real Engine gives. The Engine writes
its `capture.replay` statement in the run summary, but a copy it refuses (unknown, not sealed) may
fail the run with no summary at all. The replay failure codes in the result prove replay mode, so
they decide the outcome before the statement is required.
STORY: as someone who reproduces a score, a replay that missed the frozen copy says which cases
missed, and a run that never replayed is still refused. The one spine test runs submit, get_score
and reproduce against a stub Engine that honours replay and a board that stores what it is sent.
"""

from __future__ import annotations

import json
from dataclasses import fields
from http import HTTPStatus
from typing import Any

import httpx
import pytest
from _isolation_engine import RunPlan, isolation_engine
from test_client_run import REPLAY_URL4, _ReplayTransport
from test_leaderboards import SCORE_ID, SCOREBOARD_URL, _score_response
from test_reproduce import (
    COPY,
    RUN_ID,
    _AsyncReplayer,
    _Board,
    _client,
    _failure,
    _Replayer,
    _result,
    _score,
)

import screamingface as sf
from screamingface import _reproduction
from screamingface._engine.transport import AsyncUrl4CloudTransport
from screamingface._evaluation.model import Candidate, _stamped, _with_answer_seed
from screamingface._report_primitives import capture_status_value, is_declared_failure_code
from screamingface._reproduction import _classify
from screamingface.errors import ExecutionError

# --- finding 1: replay failure codes prove replay mode ------------------------------------------


def test_an_all_miss_replay_with_no_summary_is_frozen_copy_miss_with_its_case_ids() -> None:
    # The Engine fails every call before a provider and may write no summary, so `capture.replay`
    # is absent. The miss codes still say it was a replay.
    transport = _Replayer(
        cases=((4, "frozen_copy_miss"), (9, "frozen_copy_miss")), score=None, honoured=False
    )
    with _client(transport) as client:
        reproduction = client.reproduce(_score(total_questions=2))

    assert (reproduction.outcome, reproduction.reason) == ("failed", "frozen_copy_miss")
    assert reproduction.missed_cases == (4, 9)
    assert reproduction.result is not None


def test_an_unavailable_copy_with_no_summary_is_its_own_reason() -> None:
    # A copy that is unknown or not sealed fails every case before the first call.
    transport = _Replayer(
        cases=((1, "frozen_copy_unavailable"), (2, "frozen_copy_unavailable")),
        score=None,
        honoured=False,
    )
    with _client(transport) as client:
        reproduction = client.reproduce(_score(total_questions=2))

    assert (reproduction.outcome, reproduction.reason) == ("failed", "frozen_copy_unavailable")
    assert reproduction.missed_cases == ()


def test_no_summary_and_no_replay_codes_is_replay_unsupported() -> None:
    # A case that failed for another reason proves nothing: the run may have paid a provider.
    transport = _Replayer(cases=((1, "provider_error"),), score=None, honoured=False)
    with _client(transport) as client:
        reproduction = client.reproduce(_score())

    assert (reproduction.outcome, reproduction.reason) == ("failed", "replay_unsupported")
    assert reproduction.result is None


def test_a_candidate_level_replay_code_also_proves_replay_mode() -> None:
    transport = _Replayer(
        cases=((1, "provider_error"),),
        score=None,
        failures=[_failure("frozen_copy_unavailable")],
        honoured=False,
    )
    with _client(transport) as client:
        reproduction = client.reproduce(_score())

    assert (reproduction.outcome, reproduction.reason) == ("failed", "frozen_copy_unavailable")


def test_the_url4_path_returns_a_replay_failure_and_refuses_a_plain_one() -> None:
    from screamingface._evaluation.url4 import evaluate_url4_sync

    missed = _Replayer(cases=((1, "frozen_copy_miss"),), score=None, honoured=False)
    report = evaluate_url4_sync(missed, REPLAY_URL4, None, False, replay_frozen_copy=COPY)
    assert report.candidates[0].cases[0].failures[0].code == "frozen_copy_miss"

    plain = _Replayer(honoured=False)
    with pytest.raises(ExecutionError) as raised:
        evaluate_url4_sync(plain, REPLAY_URL4, None, False, replay_frozen_copy=COPY)
    assert raised.value.code == "replay_unsupported"


def test_a_wrong_statement_beside_replay_codes_still_classifies_by_the_codes() -> None:
    class _Other(_Replayer):
        def run(self, candidate: Any, on_event: object) -> Any:
            from dataclasses import replace

            return replace(
                super().run(candidate, on_event),
                capture_replay="5e2a9c47-1d3b-4f60-8a7e-9c1b2d3e4f50",
            )

    with _client(_Other(cases=((1, "frozen_copy_miss"),), score=None)) as client:
        reproduction = client.reproduce(_score())

    assert (reproduction.outcome, reproduction.reason) == ("failed", "frozen_copy_miss")


@pytest.mark.asyncio
async def test_the_async_client_classifies_realistic_failures_the_same_way() -> None:
    def make(transport: _AsyncReplayer) -> sf.AsyncClient:
        return sf.AsyncClient(
            engine_url="https://engine.example",
            scoreboard_url=SCOREBOARD_URL,
            scoreboard_transport=httpx.MockTransport(_Board()),
            run_transport=transport,  # type: ignore[arg-type]
        )

    miss = make(_AsyncReplayer(cases=((7, "frozen_copy_miss"),), score=None, honoured=False))
    async with miss:
        missed = await miss.reproduce(_score())
    plain = make(_AsyncReplayer(cases=((1, "provider_error"),), score=None, honoured=False))
    async with plain:
        unsupported = await plain.reproduce(_score())

    assert (missed.reason, missed.missed_cases) == ("frozen_copy_miss", (7,))
    assert unsupported.reason == "replay_unsupported"


# --- finding 2: the record carries the replay's own numbers -------------------------------------


def test_the_record_posts_the_replays_numbers_not_the_stored_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the judgment to `exact` so the posted numbers are the only thing that can differ:
    # the replay scored 0.75 over 2 cases, the stored score is 1.0 over 1.
    monkeypatch.setattr(_reproduction, "_classify", lambda score, result: ("exact", None, ()))
    board = _Board()
    with _client(_Replayer(cases=((1, None), (2, None)), score=0.75), board) as client:
        reproduction = client.reproduce(_score())

    assert reproduction.recorded is True
    (post,) = board.posts
    body = json.loads(post.read())
    assert (body["score"], body["total_questions"]) == (0.75, 2)
    assert body["run_id"] == RUN_ID


# --- finding 3: a score with no benchmark revision starts no run --------------------------------


def test_a_score_without_a_benchmark_revision_is_unknown_and_starts_no_run() -> None:
    transport = _Replayer()
    board = _Board()
    with _client(transport, board) as client:
        reproduction = client.reproduce(_score(benchmark_revision=None))

    assert reproduction == sf.Reproduction(outcome="not_reproducible", reason="unknown")
    assert transport.runs == 0
    assert board.requests == []


# --- finding 4: one stamp that copies every field -----------------------------------------------


def test_a_stamp_copies_every_candidate_field_and_changes_only_what_it_names() -> None:
    candidate = _with_answer_seed(_candidate(), 7)

    stamped = _stamped(candidate, replay_frozen_copy=COPY)

    for field in fields(Candidate):
        expected = COPY if field.name == "replay_frozen_copy" else getattr(candidate, field.name)
        assert getattr(stamped, field.name) == expected, field.name
    assert stamped.answer_seed == 7
    assert candidate.replay_frozen_copy is None, "the original is not changed"


def _candidate() -> Candidate:
    transport = _ReplayTransport()
    from screamingface._evaluation.url4 import evaluate_url4_sync

    evaluate_url4_sync(transport, REPLAY_URL4, None, False)
    assert transport.candidate is not None
    return transport.candidate


# --- finding 5: one narrowing of the capture status ----------------------------------------


def test_the_capture_status_narrows_in_one_place() -> None:
    assert capture_status_value(None) is None
    assert capture_status_value("complete") == "complete"
    assert capture_status_value("partial") == "partial"
    for bad in ("maybe", True, 1, ""):
        with pytest.raises(ValueError, match="capture_status"):
            capture_status_value(bad)


# --- finding 6: the score argument is checked ---------------------------------------------------


@pytest.mark.parametrize("bad", [None, 7, 1.5, {"id": SCORE_ID}, b"id"])
def test_reproduce_refuses_anything_that_is_not_a_score_uuid_or_id(bad: object) -> None:
    transport = _Replayer()
    board = _Board()
    with _client(transport, board) as client, pytest.raises(TypeError, match="score"):
        client.reproduce(bad)  # type: ignore[arg-type]

    assert transport.runs == 0
    assert board.requests == []


@pytest.mark.asyncio
async def test_the_async_client_refuses_a_bad_score_argument_too() -> None:
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(_Board()),
        run_transport=_AsyncReplayer(),  # type: ignore[arg-type]
    )
    async with client:
        with pytest.raises(TypeError, match="score"):
            await client.reproduce(None)  # type: ignore[arg-type]


# --- finding 11: a long client version is dropped on the record only ----------------------------


def test_a_long_client_version_is_dropped_from_the_record_and_kept_on_submit() -> None:
    from test_leaderboards import _candidate_result, _sync_client

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    long_client = {"name": "screamingface", "version": "0.2.0+" + "x" * 64, "platform": "darwin"}
    short_client = {"name": "screamingface", "version": "0.2.0", "platform": "darwin"}
    with _sync_client(handler) as client:
        for info in (long_client, short_client):
            client.leaderboards._record_reproduction(
                SCORE_ID,
                run_id="r",
                score=0.5,
                total_questions=2,
                frozen_copy_id=COPY,
                client=info,
            )
        client.leaderboards.submit(_candidate_result())

    assert "version" not in json.loads(seen[0].read())["client"]
    assert json.loads(seen[1].read())["client"]["version"] == "0.2.0"
    assert "version" in json.loads(seen[2].read())["client"]


# --- finding 12: the outcome type is public -----------------------------------------------------


def test_reproduction_outcome_is_exported() -> None:
    assert "ReproductionOutcome" in sf.__all__
    assert sf.ReproductionOutcome.__value__ == _reproduction.ReproductionOutcome.__value__


# --- finding 13: a failed stop is told to the user ----------------------------------------------


def test_a_replay_that_could_not_be_stopped_says_the_run_may_still_be_running() -> None:
    plans = {REPLAY_URL4: RunPlan()}
    with isolation_engine(plans, delete_status=HTTPStatus.INTERNAL_SERVER_ERROR) as engine:
        client = sf.Client(
            engine_url=engine.url,
            scoreboard_url=SCOREBOARD_URL,
            scoreboard_transport=httpx.MockTransport(_Board()),
        )
        with client, pytest.warns(sf.EvaluationWarning, match="may still be running"):
            reproduction = client.reproduce(_score())

    assert (reproduction.outcome, reproduction.reason) == ("failed", "replay_unsupported")


def test_a_stopped_replay_raises_no_warning() -> None:
    import warnings

    plans = {REPLAY_URL4: RunPlan()}
    with isolation_engine(plans) as engine, warnings.catch_warnings():
        warnings.simplefilter("error")
        client = sf.Client(
            engine_url=engine.url,
            scoreboard_url=SCOREBOARD_URL,
            scoreboard_transport=httpx.MockTransport(_Board()),
        )
        with client:
            reproduction = client.reproduce(_score())

    assert reproduction.reason == "replay_unsupported"


@pytest.mark.asyncio
async def test_the_async_client_stops_and_reports_a_missing_echo() -> None:
    plans = {REPLAY_URL4: RunPlan()}
    with isolation_engine(plans) as engine:
        client = sf.AsyncClient(
            engine_url=engine.url,
            scoreboard_url=SCOREBOARD_URL,
            scoreboard_transport=httpx.MockTransport(_Board()),
        )
        async with client:
            reproduction = await client.reproduce(_score())

        assert (reproduction.outcome, reproduction.reason) == ("failed", "replay_unsupported")
        assert len(engine.state.deleted) == 1, "the unacknowledged run was stopped"


@pytest.mark.asyncio
async def test_the_async_transport_tells_when_the_stop_failed_too() -> None:
    plans = {REPLAY_URL4: RunPlan()}
    with isolation_engine(plans, delete_status=HTTPStatus.INTERNAL_SERVER_ERROR) as engine:
        transport = AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            with pytest.raises(ExecutionError) as raised:
                await transport.run(
                    _stamped(_candidate(), replay_frozen_copy=COPY),
                    None,
                )
        finally:
            await transport.close()

    assert raised.value.code == "replay_unsupported"
    assert "may still be running on the Engine" in str(raised.value)
    assert raised.value.hint is not None


# --- the spine: submit, get_score, reproduce ----------------------------------------------------


class _StoringBoard:
    """A board that stores the submitted score, serves it back, and records reproductions."""

    def __init__(self) -> None:
        self.stored: dict[str, Any] | None = None
        self.reproductions: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        route = (request.method, request.url.path)
        handlers = {
            ("POST", "/v1/scores"): lambda: self._submit(json.loads(request.read())),
            ("GET", f"/v1/scores/{SCORE_ID}"): self._serve,
            ("POST", f"/v1/scores/{SCORE_ID}/reproductions"): lambda: self._record(
                json.loads(request.read())
            ),
        }
        handler = handlers.get(route)
        return handler() if handler else httpx.Response(404, json={"detail": "not found"})

    def _serve(self) -> httpx.Response:
        assert self.stored is not None
        return httpx.Response(200, json={**self.stored, **self._count(len(self.reproductions))})

    @staticmethod
    def _count(count: int) -> dict[str, Any]:
        return {"reproduction_count": count} if count else {}

    def _submit(self, payload: dict[str, Any]) -> httpx.Response:
        keys = ("frozen_copy_id", "capture_status", "answer_seed")
        self.stored = {
            **_score_response(),
            "correct_questions": None,
            "url4_expression": payload["url4_expression"],
            "spec_id": payload["spec_id"],
            "benchmark_id": payload["benchmark_id"],
            "score": payload["score"],
            "total_questions": payload["total_questions"],
            "ran_with_providers": payload["ran_with_providers"],
            "metadata": payload["metadata"],
            "benchmark_revision": payload["metadata"]["benchmark_revision"],
            **{key: payload[key] for key in keys if key in payload},
        }
        return httpx.Response(201, json=self.stored)

    def _record(self, body: dict[str, Any]) -> httpx.Response:
        assert self.stored is not None
        exact = all(
            body[key] == self.stored[key] for key in ("score", "total_questions", "frozen_copy_id")
        )
        if not exact:
            return httpx.Response(422, json={"detail": {"code": "not_exact", "message": "x"}})
        self.reproductions.append(body)
        return httpx.Response(
            201,
            json={
                "id": "7c2e5b1a-0d44-4a60-9c3e-1d2f3a4b5c6d",
                "score_id": SCORE_ID,
                "reproduced_by": "reader@example.com",
                "reproduced_at": "2026-10-07T09:00:00Z",
                "run_id": body["run_id"],
                "frozen_copy_id": body["frozen_copy_id"],
                "client_version": None,
            },
        )


def _honouring_plan() -> RunPlan:
    """A stub Engine run that captures into `COPY` and, on a replay start, honours it."""
    body = json.loads(_ReplayTransport().run(None, None).result_body or "")  # type: ignore[arg-type]
    summary = {
        "cache.hits": 0,
        "cache.misses": 1,
        "cache.bypasses": 0,
        "capture.frozen_copy_id": COPY,
        "capture.status": "complete",
    }
    return RunPlan(honour_replay=True, summary=summary, result_body=json.dumps(body))


def _spine(board: _StoringBoard) -> tuple[Any, ...]:
    """Capture, submit, fetch and reproduce against the stub Engine; return what each step gave."""
    with isolation_engine({REPLAY_URL4: _honouring_plan()}) as engine:
        client = sf.Client(
            engine_url=engine.url,
            scoreboard_url=SCOREBOARD_URL,
            scoreboard_transport=httpx.MockTransport(board),
        )
        with client:
            (result,) = client.evaluate(
                REPLAY_URL4, answer_seed=7, capture=True, progress=False
            ).candidates
            submitted = client.leaderboards.submit(result)
            fetched = client.leaderboards.get_score(submitted.id)
            reproduction = client.reproduce(fetched)
            after = client.leaderboards.get_score(submitted.id)
        return (
            result,
            fetched,
            reproduction,
            after,
            dict(engine.state.replay_copies),
            list(engine.state.capture_starts),
        )


def test_submit_then_get_score_then_reproduce_is_exact_and_recorded() -> None:
    board = _StoringBoard()
    result, fetched, reproduction, after, copies, captures = _spine(board)

    # The original run asked to be captured, named its frozen copy, and the board stored it.
    assert len(captures) == 1
    assert (result.frozen_copy_id, result.capture_status) == (COPY, "complete")
    assert board.stored is not None
    stored = board.stored
    assert (stored["frozen_copy_id"], stored["capture_status"], stored["answer_seed"]) == (
        COPY,
        "complete",
        7,
    )
    assert (fetched.frozen_copy_id, fetched.answer_seed, fetched.reproduction_count) == (
        COPY,
        7,
        0,
    )
    # The reproduction was a replay: it started once with the copy id, and the first run did not.
    assert list(copies.values()) == [COPY]
    summary = (reproduction.outcome, reproduction.reason)
    assert (*summary, reproduction.recorded, reproduction.record_error) == (
        "exact",
        None,
        True,
        None,
    )
    # The board stored the replay's own run, and now counts it. A replay states only
    # `capture.replay`, so its result has no copy of its own: the copy id came from the capture run.
    (recorded,) = board.reproductions
    replayed = reproduction.result
    assert replayed is not None
    assert recorded["run_id"] == replayed.run_id != result.run_id
    assert (replayed.frozen_copy_id, replayed.capture_status) == (None, None)
    assert after.reproduction_count == 1


# --- the two frozen-copy codes (design §5.3, §7) ------------------------------------------------


@pytest.mark.parametrize("code", ["frozen_copy_miss", "frozen_copy_unavailable"])
def test_the_replay_codes_are_declared_in_the_sdk_mirror(code: str) -> None:
    assert is_declared_failure_code(code)


@pytest.mark.parametrize("old", ["replay_cache_miss", "unknown_cache_revision"])
def test_the_cache_revision_codes_no_longer_exist(old: str) -> None:
    assert not is_declared_failure_code(old)


def test_a_miss_outranks_an_unavailable_copy_in_the_check_order() -> None:
    result = _Replayer(cases=((3, "frozen_copy_miss"), (5, "frozen_copy_unavailable")), score=None)
    with _client(result) as client:
        reproduction = client.reproduce(_score(total_questions=2))

    assert (reproduction.outcome, reproduction.reason) == ("failed", "frozen_copy_miss")
    assert reproduction.missed_cases == (3,)


def test_an_unavailable_copy_outranks_a_run_failure_and_lists_no_missed_cases() -> None:
    transport = _Replayer(
        cases=((1, "frozen_copy_unavailable"),),
        score=None,
        failures=[_failure("candidate_failed")],
    )
    with _client(transport) as client:
        reproduction = client.reproduce(_score())

    assert (reproduction.outcome, reproduction.reason) == ("failed", "frozen_copy_unavailable")
    assert reproduction.missed_cases == ()
    assert reproduction.recorded is False


def test_a_complete_score_without_a_copy_id_starts_no_run() -> None:
    transport = _Replayer()
    with _client(transport) as client:
        reproduction = client.reproduce(_score(capture_status="complete", frozen_copy_id=None))

    assert reproduction == sf.Reproduction(outcome="not_reproducible", reason="unknown")
    assert transport.runs == 0


def test_a_replay_start_sends_the_copy_id_header_and_no_capture_header() -> None:
    # The real transport against a stub Engine that honours replay: `X-Replay-Frozen-Copy` goes
    # out, `X-Capture` never does (the Engine refuses both together).
    plans = {REPLAY_URL4: _honouring_plan()}
    with isolation_engine(plans) as engine:
        client = sf.Client(
            engine_url=engine.url,
            scoreboard_url=SCOREBOARD_URL,
            scoreboard_transport=httpx.MockTransport(_Board()),
        )
        with client:
            client.reproduce(_score(), record=False)

        assert list(engine.state.replay_copies.values()) == [COPY]
        assert engine.state.capture_starts == []


# --- a candidate-level failure with no case failures (design §7) --------------------------------


def test_a_candidate_level_unavailable_copy_with_scored_cases_is_its_own_reason() -> None:
    # The Engine refused the copy (unknown, not sealed) for the whole run: no case failed, and
    # there is no summary. The code proves replay mode, so the statement check lets it through.
    transport = _Replayer(failures=[_failure("frozen_copy_unavailable")], honoured=False)
    with _client(transport) as client:
        reproduction = client.reproduce(_score())

    assert (reproduction.outcome, reproduction.reason) == ("failed", "frozen_copy_unavailable")
    assert reproduction.missed_cases == ()
    assert reproduction.result is not None
    assert reproduction.recorded is False


def test_a_candidate_level_miss_is_run_failed_by_the_accepted_rule() -> None:
    # `frozen_copy_miss` is a case-level code: `missed_cases` lists cases, so a candidate-level one
    # names none. It still proves replay mode (no `replay_unsupported`), and it is a failed run.
    transport = _Replayer(failures=[_failure("frozen_copy_miss")], honoured=False)
    with _client(transport) as client:
        reproduction = client.reproduce(_score())

    assert (reproduction.outcome, reproduction.reason) == ("failed", "run_failed")
    assert reproduction.missed_cases == ()
    assert reproduction.result is not None


def test_classify_judges_candidate_level_codes_without_a_run() -> None:
    unavailable = _result(failures=[_failure("frozen_copy_unavailable")])
    missed = _result(failures=[_failure("frozen_copy_miss")])

    assert _classify(_score(), unavailable) == ("failed", "frozen_copy_unavailable", ())
    assert _classify(_score(), missed) == ("failed", "run_failed", ())


# --- the copy id of a stored score is validated and normalised ----------------------------------


def test_a_score_normalises_its_copy_id_like_the_board() -> None:
    assert _score(frozen_copy_id=COPY.upper()).frozen_copy_id == COPY
    assert _score(frozen_copy_id="{" + COPY + "}").frozen_copy_id == COPY
    assert _score(frozen_copy_id=COPY.replace("-", "")).frozen_copy_id == COPY


@pytest.mark.parametrize(
    ("bad", "error"),
    [("not-a-uuid", ValueError), ("", ValueError), (COPY + "\n", ValueError), (7, TypeError)],
)
def test_a_score_refuses_an_invalid_copy_id_at_construction(bad: object, error: type) -> None:
    with pytest.raises(error, match="frozen_copy_id"):
        _score(frozen_copy_id=bad)


def test_reproduce_never_sends_a_malformed_copy_id_header() -> None:
    transport = _Replayer()
    with _client(transport) as client:
        client.reproduce(_score(frozen_copy_id=COPY.upper()))

    assert transport.candidate is not None
    assert transport.candidate.replay_frozen_copy == COPY
