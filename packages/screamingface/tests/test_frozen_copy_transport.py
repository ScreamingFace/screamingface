"""A Candidate's start carries its capture request or the frozen copy it replays (E14 B5).

FEATURE: OME-1307 — a capture run asks for a frozen copy only when asked. A replay names the frozen
copy it must answer from, as the answer seed does. Since E5 P2 (spec D8) both travel in the start
the Run keeps, and the Engine's driver sends them on with the start.
STORY: as someone who reproduces a score, a run that does not replay from the frozen copy is never
paid for. As someone who captures a run, the copy is asked for only when I ask.

WHY no echo check any more: the Client used to stop a replay run whose start response did not
echo the copy, because an older Engine ignored the header and ran a paid run. An Engine that runs
Runs honours the copy, and an Engine before that refuses the whole Run before anything runs
(D16), which the last test pins.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from _isolation_engine import candidate
from _run_engine import ended, run_engine

from screamingface._engine.run_client import RunClient
from screamingface._engine.run_request import start_request
from screamingface._engine.runs import StartRequest
from screamingface._engine.transport import Url4CloudTransport
from screamingface._evaluation.model import (
    _with_answer_seed,
    _with_capture,
    _with_replay_frozen_copy,
)
from screamingface.errors import EngineCapabilityError

COPY = "0b1f6d3a-5c0e-4a8e-9a3f-2f6f8f4c7d11"


def test_a_replay_start_sends_the_copy_id_beside_the_seed() -> None:
    body = start_request(
        _with_answer_seed(_with_replay_frozen_copy(candidate("go"), COPY), 7)
    ).body()

    assert (body["replay_frozen_copy"], body["answer_seed"]) == (COPY, 7)


def test_a_normal_start_sends_no_replay_header_and_checks_no_echo() -> None:
    assert start_request(candidate("go")).body()["replay_frozen_copy"] is None


def test_a_capture_start_sends_the_header() -> None:
    assert start_request(_with_capture(candidate("go"))).body()["capture"] is True


def test_a_start_without_capture_sends_no_capture_header() -> None:
    assert start_request(candidate("go")).body()["capture"] is False


def test_capture_and_a_replay_start_refuse_to_build_together() -> None:
    # INVARIANT: the Engine refuses both together, so no start is built with both, whether from
    # a compiled Candidate (which refuses the stamp) or directly.
    with pytest.raises(ValueError, match="mutually exclusive"):
        _with_replay_frozen_copy(_with_capture(candidate("go")), COPY)
    with pytest.raises(ValueError, match="mutually exclusive"):
        StartRequest(name="go", url4="(@)!'go'", capture=True, replay_frozen_copy=COPY)


def test_the_transport_sends_the_capture_header_from_the_candidate() -> None:
    with run_engine([[ended()]], {}) as engine:
        transport = Url4CloudTransport(engine.url)
        try:
            transport.register_run(None, (_with_capture(candidate("capture")),))
            transport.register_run(None, (_with_replay_frozen_copy(candidate("replay"), COPY),))
        finally:
            transport.close()

    starts = [body["candidates"][0] for body in engine.state.registered]
    assert [(start["capture"], start["replay_frozen_copy"]) for start in starts] == [
        (True, None),
        (False, COPY),
    ]
    assert engine.state.deleted == []


def test_an_engine_that_cannot_run_a_run_replays_nothing() -> None:
    """An Engine older than Runs answers `POST /runs` with a code-less 404: nothing is started,
    so a replay never becomes a paid run (spec D16)."""
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(404, json={"detail": "Not Found"})

    http = httpx.Client(base_url="https://engine.test", transport=httpx.MockTransport(respond))
    client = RunClient(http, "https://engine.test", cast(Any, None), None)

    with pytest.raises(EngineCapabilityError):
        client.register(None, (_with_replay_frozen_copy(candidate("replay"), COPY),))

    assert [request.url.path for request in seen] == ["/runs"]
