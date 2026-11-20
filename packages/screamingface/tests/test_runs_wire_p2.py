"""The Client's `/runs` wire for a detached Run (E5 P2 spec §4.1, D2, D16; plan C1).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, I send my evaluation to the Engine
once, with every Candidate's start, and the Engine runs it whether or not I stay.

INVARIANT (D2): Runs are required, so a `POST /runs` the Engine refused raises; nothing runs
without a Run.
INVARIANT (D16): an Engine older than P2 answers the new body with a 422 or 404 that has no
`code`, and only that reads as "upgrade the Engine"; every refusal a P2 Engine makes is coded.
"""

from __future__ import annotations

import asyncio
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


def test_a_stop_reason_this_client_does_not_know_reads_as_none(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1878 review round 3: a newer Engine may add a stop reason. The Run still reads, with
    `stopped_by` None (its `state` still says how it ended), so a released Client can open it."""
    record = _p2_record(state="interrupted", stopped_by="drained")
    # WHY a fresh set: "logged once" is per process, so another test that read the same reason
    # first must not change what this one sees.
    monkeypatch.setattr(wire, "_UNKNOWN_STOP_REASONS", set())

    with caplog.at_level("WARNING"):
        run = wire.get_sync(_request(_answer(200, record), []), RUN_ID)
        again = wire.get_sync(_request(_answer(200, record), []), RUN_ID)

    assert (run.state, run.stopped_by, again.stopped_by) == ("interrupted", None, None)
    assert sum("drained" in r.getMessage() for r in caplog.records) == 1


@pytest.mark.parametrize("value", ["", 7, ["canceled"]])
def test_a_stop_reason_that_is_not_text_is_still_malformed(value: object) -> None:
    with pytest.raises(ExecutionError) as raised:
        wire.get_sync(_request(_answer(200, _p2_record(stopped_by=value)), []), RUN_ID)

    assert raised.value.code == "engine_contract_error"


@pytest.mark.parametrize(
    ("detach", "said"),
    [(True, "sf.runs.list()"), (False, "stops it within 2 minutes")],
)
def test_a_lost_answer_to_post_runs_says_the_run_may_exist_and_what_becomes_of_it(
    detach: bool, said: str
) -> None:
    """#1878 review rounds 4 and 5: the Engine may have registered the Run and started it before
    the answer was lost. A detached Run is found by when it was made (a Run shows no client
    key); an attached one stops with nobody following it."""

    def timed_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    with pytest.raises(EngineUnavailableError) as raised:
        wire.create_sync(_request(timed_out, []), _run_request(detach=detach))

    message = str(raised.value)
    assert "may" in message and said in message
    assert "k" * 32 not in message


@pytest.mark.parametrize(
    ("detach", "said"),
    [(True, "until its deadline"), (False, "stops it within 2 minutes")],
)
def test_a_registration_this_client_cannot_read_names_the_run_it_started(
    detach: bool, said: str
) -> None:
    """#1878 review: the Engine registered and started the Run before the Client failed to read
    its answer (a newer Engine's state, say), so the error names the Run and what becomes of it.
    WHY the id and not the client key: a Run never shows its client key."""
    newer = _p2_record(state="paused")

    with pytest.raises(ExecutionError) as raised:
        wire.create_sync(_request(_answer(201, newer), []), _run_request(detach=detach))

    assert raised.value.code == "engine_contract_error"
    assert newer["id"] in str(raised.value) and said in str(raised.value)
    assert f"sf.runs.get({newer['id']!r})" in (raised.value.hint or "")


def test_candidates_are_read_in_index_order() -> None:
    """#1878 review: the Report pairs each Candidate with the context's at its position."""
    record = _p2_record()
    record["candidates"].reverse()

    run = wire.get_sync(_request(_answer(200, record), []), RUN_ID)

    assert [(c.index, c.name) for c in run.candidates] == [(0, "alpha"), (1, "beta")]


@pytest.mark.parametrize(
    "indexes", [(1, 1), (0, 2), (-1, 0), (1, 2)], ids=["duplicate", "gap", "negative", "shifted"]
)
def test_candidate_indexes_that_are_not_each_position_once_are_malformed(
    indexes: tuple[int, int],
) -> None:
    record = _p2_record()
    for candidate, index in zip(record["candidates"], indexes, strict=True):
        candidate["index"] = index

    with pytest.raises(ExecutionError) as raised:
        wire.get_sync(_request(_answer(200, record), []), RUN_ID)

    assert raised.value.code == "engine_contract_error"


def test_a_start_named_for_another_candidate_is_malformed() -> None:
    record = _p2_record()
    record["candidates"][0]["start"] = {"name": "beta", "url4": "/gsm8k?model=openai/beta"}

    with pytest.raises(ExecutionError) as raised:
        wire.get_sync(_request(_answer(200, record), []), RUN_ID)

    assert raised.value.code == "engine_contract_error"


@pytest.mark.parametrize(
    ("detach", "said"),
    [(True, "sf.runs.list()"), (False, "stops it within 2 minutes")],
)
def test_ctrl_c_while_post_runs_waits_says_the_run_may_exist(detach: bool, said: str) -> None:
    """#1878 review: the Engine may have registered the Run before the interruption. The
    interruption is kept, with a note on what becomes of the Run."""

    def interrupted(request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt) as raised:
        wire.create_sync(_request(interrupted, []), _run_request(detach=detach))

    note = " ".join(raised.value.__notes__)
    assert "may have been registered" in note and said in note


@pytest.mark.asyncio
async def test_a_cancelled_post_runs_says_the_run_may_exist() -> None:
    async def cancelled(method: str, path: str, json: object = None) -> httpx.Response:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError) as raised:
        await wire.create_async(cancelled, _run_request(detach=True))

    assert "sf.runs.list()" in " ".join(raised.value.__notes__)


def test_a_registration_with_no_id_to_read_says_where_to_find_the_run() -> None:
    """#1878 review: with no id to name, the Run is found by when it was made."""
    with pytest.raises(ExecutionError) as raised:
        wire.create_sync(_request(_answer(201, {"state": "paused"}), []), _run_request(detach=True))

    assert "sf.runs.list()" in (raised.value.hint or "")
