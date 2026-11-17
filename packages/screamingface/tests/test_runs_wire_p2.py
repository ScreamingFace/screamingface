"""The Client's `/runs` wire for a detached Run (E5 P2 spec §4.1, D2, D16; plan C1).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, I send my evaluation to the Engine
once, with every Candidate's start, and the Engine runs it whether or not I stay.

INVARIANT (D2): Runs are required, so a `POST /runs` the Engine refused raises; nothing runs
without a Run.
INVARIANT (D16): an Engine older than P2 answers the new body with a 422 or 404 that has no
`code`, and only that reads as "upgrade the Engine"; every refusal a P2 Engine makes is coded.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from test_runs_wire import RUN_ID, _problem, _record, _request

from screamingface._engine import runs as wire
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    EngineUnavailableError,
    ExecutionError,
)

_Handler = Callable[[httpx.Request], httpx.Response]
CONTEXT = '{"benchmark": {"name": "gsm8k"}}'
CONTEXT_REF = wire.ContextRef(
    sha256=hashlib.sha256(CONTEXT.encode()).hexdigest(), size_bytes=len(CONTEXT.encode())
)


def _start(name: str, **flags: Any) -> wire.StartRequest:
    return wire.StartRequest(name=name, url4=f"/gsm8k?model=openai/{name}", **flags)


def _run_request(**overrides: Any) -> wire.RunRequest:
    values: dict[str, Any] = {
        "client_key": "k" * 32,
        "benchmark": "gsm8k",
        "case_count": 3,
        "candidates": (_start("alpha", answer_seed=7, capture=True), _start("beta")),
        "client_version": "0.1.2",
        "context": CONTEXT,
    }
    values.update(overrides)
    return wire.RunRequest(**values)


def _p2_record(**overrides: Any) -> dict[str, Any]:
    record = _record(
        detached=True,
        deadline_at="2026-11-05T10:00:00Z",
        stopped_by=None,
        context={"sha256": CONTEXT_REF.sha256, "size_bytes": CONTEXT_REF.size_bytes},
    )
    for index, candidate in enumerate(record["candidates"]):
        candidate["index"] = index
    record.update(overrides)
    return record


def _answer(status: int, body: object) -> _Handler:
    return lambda _: httpx.Response(status, json=body)


def test_the_body_carries_every_start_the_context_and_how_the_run_ends() -> None:
    seen: list[httpx.Request] = []
    run = _run_request(detach=True, deadline_s=3600)

    wire.create_sync(_request(_answer(201, _p2_record()), seen), run)

    assert json.loads(seen[0].content) == {
        "client_key": "k" * 32,
        "benchmark": "gsm8k",
        "case_count": 3,
        "candidates": [
            {
                "name": "alpha",
                "url4": "/gsm8k?model=openai/alpha",
                "answer_seed": 7,
                "capture": True,
                "use_cache": True,
                "replay_frozen_copy": None,
            },
            {
                "name": "beta",
                "url4": "/gsm8k?model=openai/beta",
                "answer_seed": None,
                "capture": False,
                "use_cache": True,
                "replay_frozen_copy": None,
            },
        ],
        "client_version": "0.1.2",
        "context": CONTEXT,
        "detach": True,
        "deadline_s": 3600,
    }


def test_create_returns_the_run_with_its_detached_fields() -> None:
    run = wire.create_sync(_request(_answer(201, _p2_record()), []), _run_request())

    assert (run.id, run.detached, run.stopped_by) == (RUN_ID, True, None)
    assert (
        run.deadline_at is not None and run.deadline_at.isoformat() == "2026-11-05T10:00:00+00:00"
    )
    assert run.context == CONTEXT_REF
    assert [c.index for c in run.candidates] == [0, 1]


def test_runs_off_raises_that_runs_are_off() -> None:
    with pytest.raises(ExecutionError) as raised:
        wire.create_sync(_request(lambda _: _problem(404, "runs_off"), []), _run_request())

    assert raised.value.code == "runs_off"
    assert "Runs are off" in raised.value.message


@pytest.mark.parametrize("status", [404, 422])
def test_an_older_engine_raises_the_upgrade_to_make(status: int) -> None:
    with pytest.raises(EngineCapabilityError) as raised:
        wire.create_sync(_request(lambda _: _problem(status), []), _run_request())

    assert raised.value.code == "engine_upgrade_required"
    assert "Upgrade the SF Engine" in (raised.value.hint or "")


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (422, "deadline_too_long"),
        (422, "invalid_request"),
        (409, "client_key_conflict"),
        (413, "request_too_large"),
        (400, "x_profile_unsupported"),
    ],
)
def test_a_coded_refusal_raises_with_its_code(status: int, code: str) -> None:
    with pytest.raises(ExecutionError) as raised:
        wire.create_sync(_request(lambda _: _problem(status, code), []), _run_request())

    assert (raised.value.code, raised.value.status, raised.value.permanent) == (code, status, True)


def test_a_store_that_cannot_keep_the_context_may_be_retried() -> None:
    with pytest.raises(ExecutionError) as raised:
        wire.create_sync(
            _request(lambda _: _problem(503, "result_store_unavailable"), []), _run_request()
        )

    assert (raised.value.code, raised.value.permanent) == ("result_store_unavailable", False)


def test_a_refused_caller_is_an_authentication_error() -> None:
    with pytest.raises(AuthenticationError):
        wire.create_sync(_request(lambda _: _problem(401), []), _run_request())


def test_an_unreachable_engine_raises() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(EngineUnavailableError):
        wire.create_sync(_request(unreachable, []), _run_request())


def test_a_malformed_answer_is_a_contract_error() -> None:
    with pytest.raises(ExecutionError) as raised:
        wire.create_sync(_request(_answer(201, {"id": "nope"}), []), _run_request())

    assert raised.value.code == "engine_contract_error"


def test_a_read_from_an_engine_before_p2_has_no_detached_fields() -> None:
    run = wire.get_sync(_request(_answer(200, _record()), []), RUN_ID)

    assert (run.detached, run.deadline_at, run.stopped_by, run.context) == (False, None, None, None)
    assert [(c.index, c.start, c.record) for c in run.candidates] == [
        (0, None, None),
        (1, None, None),
    ]


def test_the_full_read_carries_each_candidates_start_and_record() -> None:
    record = _p2_record()
    record["candidates"][0]["start"] = {
        "name": "alpha",
        "url4": "/gsm8k?model=openai/alpha",
        "answer_seed": 7,
        "capture": False,
        "use_cache": False,
        "replay_frozen_copy": None,
    }
    record["candidates"][0]["record"] = {"trace_id": "t" * 32}

    run = wire.get_sync(_request(_answer(200, record), []), RUN_ID)

    first = run.candidates[0]
    assert first.start == _start("alpha", answer_seed=7, use_cache=False)
    assert first.record == {"trace_id": "t" * 32}


def test_the_summary_view_is_asked_for_by_name() -> None:
    seen: list[httpx.Request] = []

    wire.get_sync(_request(_answer(200, _p2_record()), seen), RUN_ID, summary=True)

    assert seen[0].url.path == f"/runs/{RUN_ID}"
    assert seen[0].url.params["view"] == "summary"


def _context_answer(body: bytes, status: int = 200) -> _Handler:
    return lambda _: httpx.Response(status, content=body)


def test_the_context_is_read_back_when_its_checksum_matches() -> None:
    seen: list[httpx.Request] = []

    context = wire.context_sync(
        _request(_context_answer(CONTEXT.encode()), seen), RUN_ID, CONTEXT_REF
    )

    assert context == CONTEXT
    assert seen[0].url.path == f"/runs/{RUN_ID}/context"


@pytest.mark.parametrize(
    "body", [b'{"benchmark": {"name": "gsm9k"}}', CONTEXT.encode() + b" "], ids=["bytes", "size"]
)
def test_a_context_that_does_not_match_the_runs_checksum_is_refused(body: bytes) -> None:
    with pytest.raises(ExecutionError) as raised:
        wire.context_sync(_request(_context_answer(body), []), RUN_ID, CONTEXT_REF)

    assert raised.value.code == "context_mismatch"


def test_a_context_the_engine_no_longer_holds_is_gone() -> None:
    with pytest.raises(ExecutionError) as raised:
        wire.context_sync(
            _request(lambda _: _problem(404, "context_not_found"), []), RUN_ID, CONTEXT_REF
        )

    assert raised.value.code == "context_not_found"


@pytest.mark.asyncio
async def test_the_async_twins_share_the_contract() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/context"):
            return httpx.Response(200, content=CONTEXT.encode())
        if request.method == "POST":
            return httpx.Response(201, json=_p2_record())
        return _problem(404, "runs_off")

    async with httpx.AsyncClient(
        base_url="http://engine.test", transport=httpx.MockTransport(respond)
    ) as http:
        request = wire.marked_async_request(http)
        created = await wire.create_async(request, _run_request())
        context = await wire.context_async(request, RUN_ID, CONTEXT_REF)

    assert (created.id, context) == (RUN_ID, CONTEXT)
