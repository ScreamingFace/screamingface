"""The Client's `/runs` wire client (E5 P1 spec §4.1, D7; plan C1).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher, every evaluation I start is
recorded on the Engine, and a failure to record it never stops the evaluation.

INVARIANT (D7): any failure of `POST /runs` is one `Unavailable`, never an exception.
INVARIANT (§4.1): on reads and cancel, only a 404 with code `run_not_found` means the id is
unknown; any other 404 means the Engine does not serve Runs.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from screamingface._core.retry import RetryingAsyncTransport, RetryingTransport
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._engine import runs as wire
from screamingface.errors import AuthenticationError, EngineUnavailableError, ExecutionError

RUN_ID = "run_" + "a" * 32
_Handler = Callable[[httpx.Request], httpx.Response]


def _record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": RUN_ID,
        "state": "running",
        "created_at": "2026-11-03T10:00:00Z",
        "finished_at": None,
        "benchmark": "gsm8k",
        "case_count": 3,
        "candidates": [
            {
                "name": "alpha",
                "state": "succeeded",
                "attempt_id": "t" * 64,
                "started_at": "2026-11-03T10:00:01Z",
                "finished_at": "2026-11-03T10:00:09Z",
                "cost_usd": "0.000000000001",
                "error_code": None,
            },
            {
                "name": "beta",
                "state": "pending",
                "attempt_id": None,
                "started_at": None,
                "finished_at": None,
                "cost_usd": None,
                "error_code": None,
            },
        ],
    }
    record.update(overrides)
    return record


def _problem(status: int, code: str | None = None) -> httpx.Response:
    body: dict[str, Any] = {"type": "about:blank", "title": "x", "status": status}
    if code is not None:
        body["code"] = code
    return httpx.Response(
        status, content=json.dumps(body), headers={"content-type": "application/problem+json"}
    )


def _request(handler: _Handler, seen: list[httpx.Request]) -> wire.Request:
    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.Client(base_url="http://engine.test", transport=httpx.MockTransport(respond))
    return wire.marked_request(http)


_SPEC = wire.RunRequest(
    client_key="k" * 32,
    benchmark="gsm8k",
    case_count=3,
    candidates=("alpha", "beta"),
    client_version="9.9.9",
)


# --- POST /runs ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [200, 201])
def test_create_returns_the_run(status: int) -> None:
    seen: list[httpx.Request] = []
    run = wire.create_sync(_request(lambda _r: httpx.Response(status, json=_record()), seen), _SPEC)

    assert isinstance(run, wire.RunRecord)
    assert run.id == RUN_ID
    assert run.candidates[0].cost_usd == Decimal("0.000000000001")
    assert run.created_at == datetime(2026, 11, 3, 10, tzinfo=UTC)
    (sent,) = seen
    assert (sent.method, sent.url.path) == ("POST", "/runs")
    assert json.loads(sent.content) == {
        "client_key": "k" * 32,
        "benchmark": "gsm8k",
        "case_count": 3,
        "candidates": ["alpha", "beta"],
        "client_version": "9.9.9",
    }
    # WHY replay-safe: `client_key` makes the call idempotent, so a lost answer may be re-sent.
    assert sent.extensions.get(_REPLAY_SAFE) is True


def test_a_lost_create_answer_is_resent_with_the_same_client_key() -> None:
    bodies: list[bytes] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        if len(bodies) == 1:
            raise httpx.ReadError("connection reset", request=request)
        return httpx.Response(200, json=_record())

    http = httpx.Client(
        base_url="http://engine.test",
        transport=RetryingTransport(httpx.MockTransport(respond), sleep=lambda _s: None),
    )
    run = wire.create_sync(wire.marked_request(http), _SPEC)

    assert isinstance(run, wire.RunRecord)
    assert len(bodies) == 2 and bodies[0] == bodies[1]


@pytest.mark.parametrize(
    "answer",
    [
        _problem(401, "identity_required"),
        _problem(404),
        httpx.Response(404, text="Not Found"),
        _problem(422),
        _problem(503),
        httpx.Response(500, text="boom"),
        httpx.Response(201, text="not json"),
        httpx.Response(201, json={"id": RUN_ID}),
    ],
    ids=["401", "404-problem", "404-plain", "422", "503", "500", "not-json", "malformed"],
)
def test_any_failed_create_is_unavailable(answer: httpx.Response) -> None:
    result = wire.create_sync(_request(lambda _r: answer, []), _SPEC)

    assert isinstance(result, wire.Unavailable)
    assert result.reason


def test_an_unreachable_engine_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = wire.create_sync(_request(refuse, []), _SPEC)

    assert isinstance(result, wire.Unavailable)


# --- GET /runs/{id} and DELETE /runs/{id} -------------------------------------------------


def test_get_reads_the_run() -> None:
    seen: list[httpx.Request] = []
    run = wire.get_sync(_request(lambda _r: httpx.Response(200, json=_record()), seen), RUN_ID)

    assert run.candidates[1].state == "pending" and run.candidates[1].cost_usd is None
    assert seen[0].url.path == f"/runs/{RUN_ID}"


def test_an_id_is_one_path_segment() -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(KeyError):
        wire.get_sync(_request(lambda _r: _problem(404, "run_not_found"), seen), "../token")

    assert seen[0].url.raw_path == b"/runs/..%2Ftoken"


@pytest.mark.parametrize("call", ["get", "cancel"])
def test_run_not_found_is_an_unknown_id(call: str) -> None:
    request = _request(lambda _r: _problem(404, "run_not_found"), [])

    with pytest.raises(KeyError, match=RUN_ID):
        getattr(wire, f"{call}_sync")(request, RUN_ID)


@pytest.mark.parametrize("answer", [_problem(404), httpx.Response(404, text="Not Found")])
@pytest.mark.parametrize("call", ["get", "cancel", "list"])
def test_any_other_404_means_runs_are_not_served(call: str, answer: httpx.Response) -> None:
    request = _request(lambda _r: answer, [])

    with pytest.raises(ExecutionError) as caught:
        if call == "list":
            wire.list_sync(request)
        else:
            getattr(wire, f"{call}_sync")(request, RUN_ID)

    assert caught.value.code == "runs_unavailable"


@pytest.mark.parametrize("status", [202, 204])
def test_cancel_accepts_both_answers(status: int) -> None:
    seen: list[httpx.Request] = []
    wire.cancel_sync(_request(lambda _r: httpx.Response(status), seen), RUN_ID)

    assert (seen[0].method, seen[0].url.path) == ("DELETE", f"/runs/{RUN_ID}")


def test_a_refused_caller_is_an_authentication_error() -> None:
    with pytest.raises(AuthenticationError):
        wire.get_sync(_request(lambda _r: _problem(401, "identity_required"), []), RUN_ID)


def test_an_unreachable_engine_raises_on_a_read() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(EngineUnavailableError):
        wire.get_sync(_request(refuse, []), RUN_ID)


@pytest.mark.parametrize(
    "body",
    [
        _record(state="paused"),
        _record(created_at="2026-11-03T10:00:00"),
        _record(case_count="3"),
        _record(candidates=[{"name": "alpha"}]),
        {**_record(), "candidates": [{**_record()["candidates"][0], "cost_usd": "a lot"}]},
        [],
    ],
    ids=["state", "naive-time", "count", "candidate", "cost", "not-object"],
)
def test_a_malformed_run_fails_to_decode(body: object) -> None:
    with pytest.raises(ExecutionError) as caught:
        wire.get_sync(_request(lambda _r: httpx.Response(200, json=body), []), RUN_ID)

    assert caught.value.code == "engine_contract_error"


# --- GET /runs ----------------------------------------------------------------------------


def test_list_follows_the_cursor_up_to_the_limit() -> None:
    second = "run_" + "b" * 32
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if "cursor" not in request.url.params:
            return httpx.Response(200, json={"runs": [_record()], "next_cursor": RUN_ID})
        return httpx.Response(200, json={"runs": [_record(id=second)], "next_cursor": second})

    since = datetime(2026, 11, 1, tzinfo=UTC)
    runs = wire.list_sync(_request(respond, seen), state="running", since=since, limit=2)

    assert [run.id for run in runs] == [RUN_ID, second]
    first, then = (dict(request.url.params) for request in seen)
    assert first == {"state": "running", "since": since.isoformat(), "limit": "2"}
    assert then == {**first, "limit": "1", "cursor": RUN_ID}


def test_list_stops_at_the_last_page() -> None:
    seen: list[httpx.Request] = []
    runs = wire.list_sync(
        _request(
            lambda _r: httpx.Response(200, json={"runs": [_record()], "next_cursor": None}), seen
        ),
        limit=50,
    )

    assert len(runs) == 1 and len(seen) == 1


def test_list_pages_are_capped_at_the_engine_page_size() -> None:
    seen: list[httpx.Request] = []
    wire.list_sync(
        _request(lambda _r: httpx.Response(200, json={"runs": [], "next_cursor": None}), seen),
        limit=1000,
    )

    assert seen[0].url.params["limit"] == "200"


# --- async twins --------------------------------------------------------------------------


def _async_request(handler: _Handler) -> wire.AsyncRequest:
    http = httpx.AsyncClient(
        base_url="http://engine.test",
        transport=RetryingAsyncTransport(httpx.MockTransport(handler)),
    )
    return wire.marked_async_request(http)


@pytest.mark.asyncio
async def test_async_twins_share_the_contract() -> None:
    answers = {
        ("POST", "/runs"): _problem(404),
        ("DELETE", f"/runs/{RUN_ID}"): _problem(404, "run_not_found"),
    }

    def respond(request: httpx.Request) -> httpx.Response:
        return answers[request.method, request.url.path]

    request = _async_request(respond)

    assert isinstance(await wire.create_async(request, _SPEC), wire.Unavailable)
    with pytest.raises(KeyError):
        await wire.cancel_async(request, RUN_ID)


@pytest.mark.parametrize("run_id", ["../../x", "run_ABC", "run_" + "a" * 31, ""])
def test_a_run_id_not_minted_by_the_engine_is_refused(run_id: str) -> None:
    # INVARIANT: the id names a file in the local result store, so it is never a path.
    body = _record(id=run_id)

    with pytest.raises(ExecutionError) as caught:
        wire.get_sync(_request(lambda _r: httpx.Response(200, json=body), []), RUN_ID)
    created = wire.create_sync(_request(lambda _r: httpx.Response(201, json=body), []), _SPEC)

    assert caught.value.code == "engine_contract_error"
    assert isinstance(created, wire.Unavailable)


def test_a_page_that_adds_nothing_ends_the_list() -> None:
    seen: list[httpx.Request] = []
    page = {"runs": [], "next_cursor": RUN_ID}

    runs = wire.list_sync(_request(lambda _r: httpx.Response(200, json=page), seen), limit=50)

    assert runs == () and len(seen) == 1
