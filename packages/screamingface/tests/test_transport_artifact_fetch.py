"""Transport redemption of result claim tickets (OME-892).

FEATURE: deliver large results in full instead of cutting them off at 1 MiB.
INVARIANT: an outcome leaves the transport with a fully materialized `result_body` —
verified against the ticket's byte count and sha256 BEFORE anything decodes it. A
mismatch is a named integrity failure, never a mangled Report.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import closing

import pytest
from protocol_server import protocol_server

import screamingface as sf
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


def _run(
    engine_url: str,
    on_event: Callable[[sf.Event], None] | None = None,
) -> _RunOutcome:
    with closing(Url4CloudTransport(engine_url)) as transport:
        return transport.run(_candidate(), on_event)


async def _arun(
    engine_url: str,
    on_event: Callable[[sf.Event], None | Awaitable[None]] | None = None,
) -> _RunOutcome:
    transport = AsyncUrl4CloudTransport(engine_url)
    try:
        return await transport.run(_candidate(), on_event)
    finally:
        await transport.close()


def test_sync_transport_materializes_an_artifact_result() -> None:
    body = '{"cases":[' + "1," * 4000 + "1]}"
    with protocol_server(mode="artifact_result", artifact_body=body) as engine:
        outcome = _run(engine.url)
    assert outcome.result_path is not None
    assert outcome.result_path.read_text() == body
    # The ticket survives for recovery; downstream decoding reads the verified file.
    assert outcome.artifact is not None


def test_async_transport_materializes_an_artifact_result() -> None:
    body = '{"cases":[' + "2," * 4000 + "2]}"
    with protocol_server(mode="artifact_result", artifact_body=body) as engine:
        outcome = asyncio.run(_arun(engine.url))
    assert outcome.result_path is not None
    assert outcome.result_path.read_text() == body
    assert outcome.artifact is not None


def test_artifact_fetch_sends_the_run_capability() -> None:
    with protocol_server(mode="artifact_result") as engine:
        _run(engine.url)
        assert engine.state.artifact_requests
        path, capability = engine.state.artifact_requests[0]
        assert path.startswith("/artifacts/")
        assert capability in engine.state.minted_tokens


def test_short_artifact_body_is_a_named_integrity_error() -> None:
    body = "X" * 1000
    with protocol_server(
        mode="artifact_result",
        artifact_body=body,
        artifact_served=body.encode("utf-8")[:-7],
    ) as engine:
        with pytest.raises(ExecutionError) as excinfo:
            _run(engine.url)
    # WHY both numbers: the researcher's first question is "how much arrived?"
    assert excinfo.value.code == "result_integrity_mismatch"
    assert "1000" in str(excinfo.value)
    assert "993" in str(excinfo.value)


def test_corrupted_artifact_bytes_are_a_named_integrity_error() -> None:
    body = "Y" * 1000
    tampered = b"Z" + body.encode("utf-8")[1:]  # same length, different content
    with protocol_server(
        mode="artifact_result", artifact_body=body, artifact_served=tampered
    ) as engine:
        with pytest.raises(ExecutionError) as excinfo:
            _run(engine.url)
    assert excinfo.value.code == "result_integrity_mismatch"


def test_missing_artifact_is_an_execution_error_not_a_report() -> None:
    with protocol_server(mode="artifact_result", artifact_missing=True) as engine:
        with pytest.raises(ExecutionError):
            _run(engine.url)


def test_a_transient_reset_during_the_fetch_is_retried_not_fatal() -> None:
    # WHY: the parcel still sits on the server after a dropped connection — losing a
    # 16-hour paid run to one TCP reset would be #642's cost with a new cause.
    body = "W" * 2000
    with protocol_server(
        mode="artifact_result", artifact_body=body, artifact_fail_first=2
    ) as engine:
        outcome = _run(engine.url)
    assert outcome.result_path is not None
    assert outcome.result_path.read_text() == body
    # 2 failed attempts + 1 success were all observed by the server.
    assert len(engine.state.artifact_requests) == 3


def test_an_oversized_response_is_cut_off_at_the_ticket_size_not_buffered() -> None:
    # INVARIANT: the ticket already states the exact size — the client must never buffer
    # past it, so a rogue 200 cannot OOM the researcher's process.
    body = "V" * 1000
    with protocol_server(
        mode="artifact_result",
        artifact_body=body,
        artifact_served=("V" * 1000 + "EXTRA-BYTES-BEYOND-THE-TICKET").encode(),
    ) as engine:
        with pytest.raises(ExecutionError) as excinfo:
            _run(engine.url)
    assert excinfo.value.code == "result_integrity_mismatch"


def test_redemption_mints_a_fresh_token_because_run_tokens_expire() -> None:
    # WHY: capability tokens live ~60 s while an evaluation runs for an hour — the 2026-08-19
    # live run proved the run-start token is ALWAYS expired by redemption time (401, $30 of
    # results stranded on disk). Redemption must present a token minted AFTER the run ended.
    body = '{"cases":[' + "3," * 4000 + "3]}"
    with protocol_server(
        mode="artifact_result", artifact_body=body, artifact_token_expiry=True
    ) as engine:
        outcome = _run(engine.url)
        assert outcome.result_path is not None
        assert outcome.result_path.read_text() == body
        # One mint to start the run, one fresh mint to redeem the ticket.
        assert len(engine.state.minted_tokens) == 2
        _, capability = engine.state.artifact_requests[-1]
        assert capability == engine.state.minted_tokens[-1]


def test_async_redemption_mints_a_fresh_token_because_run_tokens_expire() -> None:
    body = '{"cases":[' + "4," * 4000 + "4]}"
    with protocol_server(
        mode="artifact_result", artifact_body=body, artifact_token_expiry=True
    ) as engine:
        outcome = asyncio.run(_arun(engine.url))
        assert outcome.result_path is not None
        assert outcome.result_path.read_text() == body
        assert len(engine.state.minted_tokens) == 2
        _, capability = engine.state.artifact_requests[-1]
        assert capability == engine.state.minted_tokens[-1]
