"""B5 design-review round: realistic replay failures, the replay's own numbers, and the spine.

FEATURE: OME-1307 — what `reproduce` does with the outputs a real Engine gives. The Engine writes
its `cache.replay` statement only when the run touched the cache, so an all-miss replay, or a replay
refused for an unknown label, may arrive with no summary at all. The replay failure codes in the
result prove replay mode, so they decide the outcome before the statement is required.
STORY: as someone who reproduces a score, a replay that missed the cache says which cases missed,
and a run that never replayed is still refused. The one spine test runs submit, get_score and
reproduce against a stub Engine that honours replay and a board that stores what it is sent.
"""

from __future__ import annotations

import json
from dataclasses import fields
from http import HTTPStatus
from typing import Any
from uuid import UUID

import httpx
import pytest
from _isolation_engine import RunPlan, isolation_engine
from test_client_run import REPLAY_URL4, _ReplayTransport
from test_leaderboards import SCORE_ID, SCOREBOARD_URL, _score_response
from test_reproduce import (
    LABEL,
    RUN_ID,
    _AsyncReplayer,
    _Board,
    _client,
    _failure,
    _Replayer,
    _score,
)

import screamingface as sf
from screamingface import _reproduction
from screamingface._engine.transport import AsyncUrl4CloudTransport
from screamingface._evaluation.model import Candidate, _stamped, _with_answer_seed
from screamingface._report_primitives import reproducible_status
from screamingface.errors import ExecutionError

# --- finding 1: replay failure codes prove replay mode ------------------------------------------


def test_an_all_miss_replay_with_no_summary_is_cache_miss_with_its_case_ids() -> None:
    # The Engine fails every call before a provider, and a run that touched no cache writes no
    # summary, so `cache.replay` is absent. The miss codes still say it was a replay.
    transport = _Replayer(
        cases=((4, "replay_cache_miss"), (9, "replay_cache_miss")), score=None, honoured=False
    )
    with _client(transport) as client:
        reproduction = client.reproduce(_score(total_questions=2))

    assert (reproduction.outcome, reproduction.reason) == ("failed", "cache_miss")
    assert reproduction.missed_cases == (4, 9)
    assert reproduction.result is not None


def test_an_unknown_cache_revision_with_no_summary_is_its_own_reason() -> None:
    # K10: the Engine fails every case before the first chat call, so there is no summary either.
    transport = _Replayer(
        cases=((1, "unknown_cache_revision"), (2, "unknown_cache_revision")),
        score=None,
        honoured=False,
    )
    with _client(transport) as client:
        reproduction = client.reproduce(_score(total_questions=2))

    assert (reproduction.outcome, reproduction.reason) == ("failed", "unknown_cache_revision")
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
        failures=[_failure("unknown_cache_revision")],
        honoured=False,
    )
    with _client(transport) as client:
        reproduction = client.reproduce(_score())

    assert (reproduction.outcome, reproduction.reason) == ("failed", "unknown_cache_revision")


def test_the_url4_path_returns_a_replay_failure_and_refuses_a_plain_one() -> None:
    from screamingface._evaluation.url4 import evaluate_url4_sync

    missed = _Replayer(cases=((1, "replay_cache_miss"),), score=None, honoured=False)
    report = evaluate_url4_sync(missed, REPLAY_URL4, None, False, cache_replay=LABEL)
    assert report.candidates[0].cases[0].failures[0].code == "replay_cache_miss"

    plain = _Replayer(honoured=False)
    with pytest.raises(ExecutionError) as raised:
        evaluate_url4_sync(plain, REPLAY_URL4, None, False, cache_replay=LABEL)
    assert raised.value.code == "replay_unsupported"


def test_a_wrong_statement_beside_replay_codes_still_classifies_by_the_codes() -> None:
    class _Other(_Replayer):
        def run(self, candidate: Any, on_event: object) -> Any:
            from dataclasses import replace

            return replace(super().run(candidate, on_event), cache_replay="cr-ba9876543210")

    with _client(_Other(cases=((1, "replay_cache_miss"),), score=None)) as client:
        reproduction = client.reproduce(_score())

    assert (reproduction.outcome, reproduction.reason) == ("failed", "cache_miss")


@pytest.mark.asyncio
async def test_the_async_client_classifies_realistic_failures_the_same_way() -> None:
    def make(transport: _AsyncReplayer) -> sf.AsyncClient:
        return sf.AsyncClient(
            engine_url="https://engine.example",
            scoreboard_url=SCOREBOARD_URL,
            scoreboard_transport=httpx.MockTransport(_Board()),
            run_transport=transport,  # type: ignore[arg-type]
        )

    miss = make(_AsyncReplayer(cases=((7, "replay_cache_miss"),), score=None, honoured=False))
    async with miss:
        missed = await miss.reproduce(_score())
    plain = make(_AsyncReplayer(cases=((1, "provider_error"),), score=None, honoured=False))
    async with plain:
        unsupported = await plain.reproduce(_score())

    assert (missed.reason, missed.missed_cases) == ("cache_miss", (7,))
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

    stamped = _stamped(candidate, cache_replay=LABEL)

    for field in fields(Candidate):
        expected = LABEL if field.name == "cache_replay" else getattr(candidate, field.name)
        assert getattr(stamped, field.name) == expected, field.name
    assert stamped.answer_seed == 7
    assert candidate.cache_replay is None, "the original is not changed"


def _candidate() -> Candidate:
    transport = _ReplayTransport()
    from screamingface._evaluation.url4 import evaluate_url4_sync

    evaluate_url4_sync(transport, REPLAY_URL4, None, False)
    assert transport.candidate is not None
    return transport.candidate


# --- finding 5: one narrowing of the reproducible status ----------------------------------------


def test_the_reproducible_status_narrows_in_one_place() -> None:
    assert reproducible_status(None) is None
    assert reproducible_status("complete") == "complete"
    assert reproducible_status("partial") == "partial"
    for bad in ("maybe", True, 1, ""):
        with pytest.raises(ValueError, match="reproducible"):
            reproducible_status(bad)


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
                cache_revision=LABEL,
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
                    _stamped(_candidate(), cache_replay=LABEL),
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
        keys = ("cache_revision", "reproducible", "answer_seed")
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
            body[key] == self.stored[key] for key in ("score", "total_questions", "cache_revision")
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
                "cache_revision": body["cache_revision"],
                "client_version": None,
            },
        )


def test_submit_then_get_score_then_reproduce_is_exact_and_recorded() -> None:
    body = json.loads(_ReplayTransport().run(None, None).result_body or "")  # type: ignore[arg-type]
    summary = {
        "cache.hits": 0,
        "cache.misses": 1,
        "cache.bypasses": 0,
        "cache.revision": LABEL,
        "cache.reproducible": "complete",
    }
    plans = {
        REPLAY_URL4: RunPlan(honour_replay=True, summary=summary, result_body=json.dumps(body))
    }
    board = _StoringBoard()
    with isolation_engine(plans) as engine:
        client = sf.Client(
            engine_url=engine.url,
            scoreboard_url=SCOREBOARD_URL,
            scoreboard_transport=httpx.MockTransport(board),
        )
        with client:
            (result,) = client.evaluate(REPLAY_URL4, answer_seed=7, progress=False).candidates
            submitted = client.leaderboards.submit(result)
            fetched = client.leaderboards.get_score(submitted.id)
            reproduction = client.reproduce(fetched)
            after = client.leaderboards.get_score(submitted.id)

        labels = dict(engine.state.replay_labels)

    # The original run named its cache version and the board stored it.
    assert (result.cache_revision, result.reproducible) == (LABEL, "complete")
    assert board.stored is not None
    assert board.stored["cache_revision"] == LABEL
    assert board.stored["answer_seed"] == 7
    assert (fetched.cache_revision, fetched.answer_seed, fetched.reproduction_count) == (
        LABEL,
        7,
        0,
    )
    # The reproduction was a replay: it started once with the label, and the first run did not.
    assert list(labels.values()) == [LABEL]
    assert (reproduction.outcome, reproduction.reason) == ("exact", None)
    assert (reproduction.recorded, reproduction.record_error) == (True, None)
    # The board stored the replay's own run, and now counts it.
    (recorded,) = board.reproductions
    assert reproduction.result is not None
    assert recorded["run_id"] == reproduction.result.run_id != result.run_id
    assert after.reproduction_count == 1
    assert UUID(str(after.id)) == UUID(SCORE_ID)
