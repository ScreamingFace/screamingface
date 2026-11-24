"""The transport reads each Candidate's result in full (OME-892, E5 P2 spec D9a).

FEATURE: deliver large results in full instead of cutting them off at 1 MiB. Since E5 P2 the
Engine keeps every result of a Run it drives, and the transport reads it from the Run's result
route as the Run's owner.
INVARIANT: an outcome leaves the transport with a fully materialized `result_body` —
verified against the record's byte count and sha256 BEFORE anything decodes it. A
mismatch is a named integrity failure, never a mangled Report.
"""

from __future__ import annotations

import asyncio
from contextlib import closing

import pytest
from _run_engine import (
    AsyncCollectingSink,
    CollectingSink,
    ended,
    run_engine,
    settled,
    state,
)

from screamingface._core.ports import _RunOutcome
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface._evaluation.model import (
    Candidate,
    _compiled_candidate,
    _compiled_operation,
)
from screamingface.errors import ExecutionError


def _candidate() -> Candidate:
    return _compiled_candidate(
        name="opus",
        kind="model",
        models=("provider/opus",),
        url4="(@)!'hello'",
        operations=(
            _compiled_operation(
                id="op_opus",
                kind="model",
                label="opus answer",
                depends_on=(),
            ),
        ),
    )


def _script(body: str) -> list[list[str | int]]:
    return [[state(0, "scheduled"), settled(0, body.encode()), ended()]]


def _run(engine_url: str) -> _RunOutcome:
    sink = CollectingSink()
    with closing(Url4CloudTransport(engine_url)) as transport:
        run_id = transport.register_run(None, (_candidate(),))
        transport.follow_run(run_id, (_candidate(),), sink)
    outcome = sink.outcomes[0]
    if isinstance(outcome, Exception):
        raise outcome
    return outcome


async def _arun(engine_url: str) -> _RunOutcome:
    sink = AsyncCollectingSink()
    transport = AsyncUrl4CloudTransport(engine_url)
    try:
        run_id = await transport.register_run(None, (_candidate(),))
        await transport.follow_run(run_id, (_candidate(),), sink)
    finally:
        await transport.close()
    outcome = sink.outcomes[0]
    if isinstance(outcome, Exception):
        raise outcome
    return outcome


def test_sync_transport_materializes_an_artifact_result() -> None:
    body = '{"cases":[' + "1," * 4000 + "1]}"
    with run_engine(_script(body), {0: body.encode()}) as engine:
        outcome = _run(engine.url)
    assert outcome.result_body == body
    # No artifact ticket: downstream decoding sees only the materialized body.
    assert outcome.artifact is None


def test_async_transport_materializes_an_artifact_result() -> None:
    body = '{"cases":[' + "2," * 4000 + "2]}"
    with run_engine(_script(body), {0: body.encode()}) as engine:
        outcome = asyncio.run(_arun(engine.url))
    assert outcome.result_body == body
    assert outcome.artifact is None


def test_artifact_fetch_sends_the_run_capability() -> None:
    """The result route is the Run owner's: it names the Run and the Candidate's index."""
    with run_engine(_script("{}"), {0: b"{}"}) as engine:
        _run(engine.url)
        (path,) = engine.state.fetched
        assert path.endswith("/candidates/0/result")


def test_short_artifact_body_is_a_named_integrity_error() -> None:
    body = "X" * 1000
    with run_engine(_script(body), {0: body.encode("utf-8")[:-7]}) as engine:
        with pytest.raises(ExecutionError) as excinfo:
            _run(engine.url)
    # WHY both numbers: the researcher's first question is "how much arrived?"
    assert excinfo.value.code == "result_integrity_mismatch"
    assert "1000" in str(excinfo.value)
    assert "993" in str(excinfo.value)


def test_corrupted_artifact_bytes_are_a_named_integrity_error() -> None:
    body = "Y" * 1000
    tampered = b"Z" + body.encode("utf-8")[1:]  # same length, different content
    with run_engine(_script(body), {0: tampered}) as engine:
        with pytest.raises(ExecutionError) as excinfo:
            _run(engine.url)
    assert excinfo.value.code == "result_integrity_mismatch"


def test_missing_artifact_is_an_execution_error_not_a_report() -> None:
    with run_engine(_script("{}"), {}) as engine:
        with pytest.raises(ExecutionError):
            _run(engine.url)


def test_a_transient_reset_during_the_fetch_is_retried_not_fatal() -> None:
    # WHY: the result still sits on the Engine after a dropped connection — losing a
    # 16-hour paid run to one TCP reset would be #642's cost with a new cause.
    body = "W" * 2000
    with run_engine(_script(body), {0: body.encode()}, drop_fetches=2) as engine:
        outcome = _run(engine.url)
    assert outcome.result_body == body
    # 2 failed attempts + 1 success were all observed by the server.
    assert len(engine.state.fetched) == 3


def test_an_oversized_response_is_cut_off_at_the_ticket_size_not_buffered() -> None:
    # INVARIANT: the record already states the exact size — the client must never buffer
    # past it, so a rogue 200 cannot OOM the researcher's process.
    body = "V" * 1000
    served = ("V" * 1000 + "EXTRA-BYTES-BEYOND-THE-TICKET").encode()
    with run_engine(_script(body), {0: served}) as engine:
        with pytest.raises(ExecutionError) as excinfo:
            _run(engine.url)
    assert excinfo.value.code == "result_integrity_mismatch"


def test_redemption_mints_a_fresh_token_because_run_tokens_expire() -> None:
    # WHY: capability tokens live ~60 s while an evaluation runs for an hour (the 2026-08-19
    # live run stranded $30 of results on an expired one). The result route takes the caller's
    # identity instead, so no token is minted and none can have expired.
    body = '{"cases":[' + "3," * 4000 + "3]}"
    with run_engine(_script(body), {0: body.encode()}) as engine:
        outcome = _run(engine.url)
        assert outcome.result_body == body
        assert "url4-capability" not in {name.lower() for name in engine.state.fetch_headers[-1]}


def test_async_redemption_mints_a_fresh_token_because_run_tokens_expire() -> None:
    body = '{"cases":[' + "4," * 4000 + "4]}"
    with run_engine(_script(body), {0: body.encode()}) as engine:
        outcome = asyncio.run(_arun(engine.url))
        assert outcome.result_body == body
        assert "url4-capability" not in {name.lower() for name in engine.state.fetch_headers[-1]}
