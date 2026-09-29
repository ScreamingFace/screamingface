"""Edit the authors or the paper URL of a submission from the SDK (E14a, OME-1307, MD-19).

FEATURE: OME-1307 (E14) editable submission metadata. The SDK half of contract C5
(`PATCH /v1/scores/{id}` with `If-Match`) and of the C4 `paper_url` field. Every test uses an
`httpx.MockTransport` fake of the Scoreboard (D7 X-20): no network, no `apps/` import.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

import httpx
import pytest
from url4 import expr, render, src, text

import screamingface as sf
from screamingface import _default_client
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import _compiled_operation

SCOREBOARD_URL = "https://scoreboard.example"
SUBMITTED_AT = "2026-08-08T12:30:00Z"
SCORE_ID = "af95892d-7438-4ac3-9b47-5e06f62c8251"
PAPER_URL = "https://arxiv.org/abs/2609.01234"

Mode = Literal["sync", "async"]
MODES: tuple[Mode, ...] = ("sync", "async")


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


def _candidate_result() -> sf.CandidateResult:
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
        run_id="run-fusion-alpha",
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
    )


def _sync_client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(handler),
    )


def _async_client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.AsyncClient:
    return sf.AsyncClient(
        engine_url="https://engine.example",
        scoreboard_url=SCOREBOARD_URL,
        scoreboard_transport=httpx.MockTransport(handler),
    )


async def _edit(
    mode: Mode,
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: Any,
) -> sf.LeaderboardScore:
    if mode == "sync":
        with _sync_client(handler) as client:
            return client.leaderboards.update_submission(SCORE_ID, **kwargs)
    async with _async_client(handler) as async_client:
        return await async_client.leaderboards.update_submission(SCORE_ID, **kwargs)


class _Board:
    """A Scoreboard fake that records each request and answers from a script."""

    def __init__(self, *replies: httpx.Response | Exception) -> None:
        self.seen: list[httpx.Request] = []
        self.bodies: list[object] = []
        self._replies = list(replies)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        self.bodies.append(json.loads(request.read()) if request.content else None)
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if isinstance(reply, Exception):
            raise reply
        # WHY a copy: a Response's stream is consumed by the first client that reads it, and the
        # same scripted reply serves the sync and the async run of one parametrized case.
        return httpx.Response(reply.status_code, content=reply.content, headers=reply.headers)


def _ok(**extra: object) -> httpx.Response:
    return httpx.Response(200, json=_score_response(**extra))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_update_submission_sends_if_match_and_parses(mode: Mode) -> None:
    board = _Board(_ok(paper_url=PAPER_URL, metadata_revision=2, authors=["alice", "bob"]))

    score = await _edit(
        mode,
        board,
        expected_revision=1,
        authors=["alice@example.com", "bob@example.com"],
        paper_url=PAPER_URL,
    )

    assert len(board.seen) == 1
    request = board.seen[0]
    assert request.method == "PATCH"
    assert request.url.path == f"/v1/scores/{SCORE_ID}"
    assert request.headers["If-Match"] == '"1"'
    assert board.bodies[0] == {
        "authors": ["alice@example.com", "bob@example.com"],
        "paper_url": PAPER_URL,
    }
    assert score.id == UUID(SCORE_ID)
    assert score.paper_url == PAPER_URL
    assert score.metadata_revision == 2
    assert score.authors == ("alice", "bob")
    assert score.scoreboard_url == SCOREBOARD_URL


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_partial_update_sends_only_the_given_field(mode: Mode) -> None:
    board = _Board(_ok(paper_url=PAPER_URL, metadata_revision=4))

    await _edit(mode, board, expected_revision=3, paper_url=PAPER_URL)
    await _edit(mode, board, expected_revision=4, authors=["alice@example.com"])

    assert board.bodies == [{"paper_url": PAPER_URL}, {"authors": ["alice@example.com"]}]
    assert [request.headers["If-Match"] for request in board.seen] == ['"3"', '"4"']


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("field", ["authors", "paper_url"])
async def test_md19_none_sends_json_null_to_clear_a_field(mode: Mode, field: str) -> None:
    # INVARIANT: None is a real value in C5 (it clears the field, MD-E7). It must reach the wire as
    # JSON null, and it must not be confused with "not given" (no key at all).
    board = _Board(_ok(metadata_revision=5))

    await _edit(mode, board, expected_revision=4, **{field: None})

    assert board.bodies == [{field: None}]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_no_field_raises_before_any_request(mode: Mode) -> None:
    board = _Board(_ok())

    with pytest.raises(ValueError, match="update_submission needs authors or paper_url"):
        await _edit(mode, board, expected_revision=1)

    assert board.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("revision", "error", "message"),
    [
        (0, ValueError, "expected_revision must be positive"),
        (-1, ValueError, "expected_revision must be positive"),
        (True, TypeError, "expected_revision must be an integer"),
        ("1", TypeError, "expected_revision must be an integer"),
    ],
)
async def test_md19_expected_revision_is_validated_before_any_request(
    mode: Mode, revision: object, error: type[Exception], message: str
) -> None:
    board = _Board(_ok())

    with pytest.raises(error, match=message):
        await _edit(mode, board, expected_revision=revision, paper_url=PAPER_URL)

    assert board.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("authors", "error", "message"),
    [
        ([f"a{index}@example.com" for index in range(11)], ValueError, "at most 10"),
        (["not-an-email"], ValueError, "valid email address"),
        ([], ValueError, "at least one email address"),
        ("alice@example.com", TypeError, "sequence of email addresses"),
        ([7], TypeError, "each author must be an email address string"),
    ],
)
async def test_md19_authors_use_the_submit_validator(
    mode: Mode, authors: object, error: type[Exception], message: str
) -> None:
    board = _Board(_ok())

    with pytest.raises(error, match=message):
        await _edit(mode, board, expected_revision=1, authors=authors)

    assert board.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("paper_url", "error", "message"),
    [
        ("   ", ValueError, "paper_url must be non-blank text or None"),
        ("", ValueError, "paper_url must be non-blank text or None"),
        (7, TypeError, "paper_url must be a string or None"),
    ],
)
async def test_md19_paper_url_type_and_blank_are_refused_before_any_request(
    mode: Mode, paper_url: object, error: type[Exception], message: str
) -> None:
    board = _Board(_ok())

    with pytest.raises(error, match=message):
        await _edit(mode, board, expected_revision=1, paper_url=paper_url)

    assert board.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_paper_url_is_sent_stripped_and_without_url_rules(mode: Mode) -> None:
    # INVARIANT: the SDK checks the type only; the Scoreboard is the one URL validator (MD-E5).
    board = _Board(_ok())

    await _edit(mode, board, expected_revision=1, paper_url="  not a url at all  ")

    assert board.bodies == [{"paper_url": "not a url at all"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={"detail": "no"}), "identity_not_verified"),
        (httpx.Response(403, json={"detail": "no"}), "not_submission_owner"),
        (httpx.Response(404, json={"detail": "no"}), "unknown_score"),
        (httpx.Response(412, content=b"<html>proxy</html>"), "metadata_revision_conflict"),
        (httpx.Response(422, json={"detail": "no"}), "invalid_submission_metadata"),
        (httpx.Response(428, json={"detail": "no"}), "precondition_required"),
        (httpx.Response(400, json={"detail": "no"}), "scoreboard_contract_error"),
        (
            # The coded body wins over the status map (D7 X-8).
            httpx.Response(
                422, json={"detail": {"code": "invalid_paper_url", "message": "bad url"}}
            ),
            "invalid_paper_url",
        ),
        (
            # A blank code is no code: the status map answers.
            httpx.Response(403, json={"detail": {"code": "  ", "message": "no"}}),
            "not_submission_owner",
        ),
    ],
)
async def test_md19_error_codes_are_typed(mode: Mode, response: httpx.Response, code: str) -> None:
    board = _Board(response)

    with pytest.raises(sf.LeaderboardError) as caught:
        await _edit(mode, board, expected_revision=1, paper_url=PAPER_URL)

    assert caught.value.code == code
    assert caught.value.status == response.status_code
    assert caught.value.permanent is True
    assert len(board.seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_conflict_keeps_the_whole_body_in_details(mode: Mode) -> None:
    # INVARIANT: `_error_details` is unchanged, so a coded 412 exposes the whole JSON body
    # (current revision and values, MD-E3) and the caller retries with the new revision. A 412
    # is never retried by the SDK.
    body = {
        "detail": {
            "code": "metadata_revision_conflict",
            "message": "The submission changed",
            "current_revision": 3,
            "current": {"authors": ["alice"], "paper_url": None},
        }
    }
    board = _Board(httpx.Response(412, json=body))

    with pytest.raises(sf.LeaderboardError) as caught:
        await _edit(mode, board, expected_revision=1, paper_url=PAPER_URL)

    assert caught.value.code == "metadata_revision_conflict"
    assert caught.value.details == body
    assert cast(Any, caught.value.details)["detail"]["current_revision"] == 3
    assert caught.value.permanent is True
    assert len(board.seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_server_error_is_not_permanent_and_keeps_its_default_code(mode: Mode) -> None:
    board = _Board(httpx.Response(503, json={"detail": "busy"}))

    with pytest.raises(sf.LeaderboardError) as caught:
        await _edit(mode, board, expected_revision=1, paper_url=PAPER_URL)

    assert caught.value.code == "scoreboard_contract_error"
    assert caught.value.permanent is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_connection_error_is_retried_once(mode: Mode) -> None:
    board = _Board(httpx.ConnectError("boom"), _ok(metadata_revision=2))

    score = await _edit(mode, board, expected_revision=1, paper_url=PAPER_URL)

    assert score.metadata_revision == 2
    assert len(board.seen) == 2
    assert [request.headers["If-Match"] for request in board.seen] == ['"1"', '"1"']
    assert board.bodies == [{"paper_url": PAPER_URL}, {"paper_url": PAPER_URL}]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_two_connection_errors_raise_unreachable(mode: Mode) -> None:
    board = _Board(httpx.ConnectError("boom"))

    with pytest.raises(sf.LeaderboardError) as caught:
        await _edit(mode, board, expected_revision=1, paper_url=PAPER_URL)

    assert len(board.seen) == 2
    assert caught.value.code == "scoreboard_unreachable"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_non_transport_http_error_is_not_retried(mode: Mode) -> None:
    # WHY: only a transport error is safe to send again at once; a decode error or a protocol
    # error from the body is not a lost connection.
    board = _Board(httpx.DecodingError("bad body"))

    with pytest.raises(sf.LeaderboardError) as caught:
        await _edit(mode, board, expected_revision=1, paper_url=PAPER_URL)

    assert len(board.seen) == 1
    assert caught.value.code == "scoreboard_unreachable"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_patch_uses_a_15_second_timeout(mode: Mode) -> None:
    board = _Board(_ok())

    await _edit(mode, board, expected_revision=1, paper_url=PAPER_URL)

    assert board.seen[0].extensions["timeout"]["read"] == 15.0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_other_scoreboard_calls_keep_the_client_default_timeout(mode: Mode) -> None:
    board = _Board(_ok())

    if mode == "sync":
        with _sync_client(board) as client:
            client.leaderboards.get_score(SCORE_ID)
    else:
        async with _async_client(board) as async_client:
            await async_client.leaderboards.get_score(SCORE_ID)

    assert board.seen[0].extensions["timeout"]["read"] != 15.0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_submit_sends_paper_url_only_when_given(mode: Mode) -> None:
    board = _Board(httpx.Response(201, json=_score_response(paper_url=PAPER_URL)))
    candidate = _candidate_result()

    if mode == "sync":
        with _sync_client(board) as client:
            client.leaderboards.submit(candidate, paper_url=PAPER_URL)
            client.leaderboards.submit(candidate)
    else:
        async with _async_client(board) as async_client:
            await async_client.leaderboards.submit(candidate, paper_url=PAPER_URL)
            await async_client.leaderboards.submit(candidate)

    with_paper, without_paper = board.bodies
    assert isinstance(with_paper, dict)
    assert isinstance(without_paper, dict)
    assert with_paper["paper_url"] == PAPER_URL
    assert "paper_url" not in without_paper


@pytest.mark.parametrize(
    ("paper_url", "error", "message"),
    [
        ("  ", ValueError, "paper_url must be non-blank text or None"),
        (5, TypeError, "paper_url must be a string or None"),
    ],
)
def test_md19_submit_refuses_a_bad_paper_url_before_any_request(
    paper_url: object, error: type[Exception], message: str
) -> None:
    board = _Board(_ok())

    with _sync_client(board) as client, pytest.raises(error, match=message):
        client.leaderboards.submit(_candidate_result(), paper_url=cast(Any, paper_url))

    assert board.seen == []


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.asyncio
async def test_md19_score_decode_reads_paper_url_and_revision_and_tolerates_absence(
    mode: Mode,
) -> None:
    async def get(reply: httpx.Response) -> sf.LeaderboardScore:
        board = _Board(reply)
        if mode == "sync":
            with _sync_client(board) as client:
                return client.leaderboards.get_score(SCORE_ID)
        async with _async_client(board) as async_client:
            return await async_client.leaderboards.get_score(SCORE_ID)

    present = await get(_ok(paper_url=PAPER_URL, metadata_revision=3))
    assert (present.paper_url, present.metadata_revision) == (PAPER_URL, 3)

    absent = await get(_ok())
    assert (absent.paper_url, absent.metadata_revision) == (None, None)

    nulls = await get(_ok(paper_url=None, metadata_revision=None))
    assert (nulls.paper_url, nulls.metadata_revision) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("revision", [0, True, "2", -1])
async def test_md19_score_decode_refuses_a_bad_metadata_revision(
    mode: Mode, revision: object
) -> None:
    board = _Board(_ok(metadata_revision=revision))

    with pytest.raises(sf.LeaderboardError) as caught:
        if mode == "sync":
            with _sync_client(board) as client:
                client.leaderboards.get_score(SCORE_ID)
        else:
            async with _async_client(board) as async_client:
                await async_client.leaderboards.get_score(SCORE_ID)

    assert caught.value.code == "invalid_leaderboard"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_md19_score_decode_refuses_a_blank_paper_url(mode: Mode) -> None:
    board = _Board(_ok(paper_url="  "))

    with pytest.raises(sf.LeaderboardError) as caught:
        if mode == "sync":
            with _sync_client(board) as client:
                client.leaderboards.get_score(SCORE_ID)
        else:
            async with _async_client(board) as async_client:
                await async_client.leaderboards.get_score(SCORE_ID)

    assert caught.value.code == "invalid_leaderboard"


def test_md19_module_facade_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, dict[str, object]]] = []

    class FakeLeaderboards:
        def update_submission(self, score_id: object, **kwargs: object) -> str:
            calls.append((score_id, kwargs))
            return "updated"

    class FakeClient:
        leaderboards = FakeLeaderboards()

    monkeypatch.setattr(_default_client, "_client", FakeClient())

    assert sf.leaderboards.update_submission(SCORE_ID, expected_revision=2, paper_url=None) == (
        "updated"
    )
    assert calls[0][0] == SCORE_ID
    assert calls[0][1]["expected_revision"] == 2
    assert calls[0][1]["paper_url"] is None
    # An argument the caller did not give reaches the client as "not given", not as None.
    assert calls[0][1]["authors"] is sf.leaderboards.UNSET

    monkeypatch.setattr(_default_client, "_client", None)


def test_md19_module_facade_submit_forwards_paper_url(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeLeaderboards:
        def submit(self, candidate_result: object, **kwargs: object) -> str:
            calls.append(kwargs)
            return "submitted"

    class FakeClient:
        leaderboards = FakeLeaderboards()

    monkeypatch.setattr(_default_client, "_client", FakeClient())
    candidate = _candidate_result()

    assert sf.leaderboards.submit(candidate, paper_url=PAPER_URL) == "submitted"
    assert calls[-1] == {"authors": None, "paper_url": PAPER_URL}

    # A call without paper_url sends no paper_url key (a board before E14a stays valid).
    assert sf.leaderboards.submit(candidate) == "submitted"
    assert calls[-1] == {"authors": None}

    monkeypatch.setattr(_default_client, "_client", None)
