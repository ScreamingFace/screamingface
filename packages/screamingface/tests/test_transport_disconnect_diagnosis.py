"""Why a Run's follow drops, and the drop the Client used to cause itself.

Every cause of a lost stream reaches the researcher as one message — an oversized frame, a proxy
draining a listener, a rolled Pod, a refused sign-in. These pin the one the Client is
responsible for (a frame bigger than it accepts), plus the diagnostic that tells the rest apart.

Since E5 P2 the Client follows one stream per Run (spec §4.2), which forwards each Candidate's
frames unchanged, its inline result frames among them.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import closing

import pytest
from _run_engine import (
    AsyncCollectingSink,
    CollectingSink,
    ended,
    run_engine,
    settled,
    state,
    topic,
)
from _websocket_wire import cloudevent
from test_client_protocol import _candidate

from screamingface._engine.run_client import FollowTimings
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface.errors import AuthenticationError, ExecutionError

# The Engine's inline cap (1 MiB): a result frame this size is the largest it sends inline.
_CAP_BODY = "x" * (1024 * 1024)


def _result_frame() -> str:
    payload = cloudevent(
        "ai.url4.result", {"body": _CAP_BODY, "media_type": "text/plain"}, 1, subject=topic(0)
    )
    return json.dumps({"type": "candidate.event", "index": 0, "event": payload})


_SCRIPT = [[state(0, "running"), _result_frame(), settled(0, b"{}"), ended()]]


def test_a_result_at_the_engine_cap_reaches_the_researcher() -> None:
    sink = CollectingSink()
    with run_engine(_SCRIPT, {0: b"{}"}) as engine:
        with closing(Url4CloudTransport(engine.url)) as transport:
            run_id = transport.register_run(None, (_candidate(),))
            transport.follow_run(run_id, (_candidate(),), sink)

    assert sink.outcomes[0].result_body == "{}"
    assert len(engine.state.followed) == 1


@pytest.mark.asyncio
async def test_a_result_at_the_engine_cap_reaches_an_async_researcher() -> None:
    sink = AsyncCollectingSink()
    with run_engine(_SCRIPT, {0: b"{}"}) as engine:
        transport = AsyncUrl4CloudTransport(engine.url)
        try:
            run_id = await transport.register_run(None, (_candidate(),))
            await transport.follow_run(run_id, (_candidate(),), sink)
        finally:
            await transport.close()

    assert sink.outcomes[0].result_body == "{}"
    assert len(engine.state.followed) == 1


def test_an_access_challenge_retries_with_a_freshly_minted_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D15: the follow needs no capability and starts no login; a challenge ends it with how
    to pick the Run up."""
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response

    from screamingface._engine import run_client

    def challenged(*_args: object, **_kwargs: object) -> None:
        raise InvalidStatus(Response(403, "Forbidden", Headers()))

    monkeypatch.setattr(run_client.sync_ws, "connect", challenged)
    with run_engine([], {}) as engine:
        with closing(Url4CloudTransport(engine.url)) as transport:
            run_id = transport.register_run(None, (_candidate(),))
            with pytest.raises(AuthenticationError) as raised:
                transport.follow_run(run_id, (_candidate(),), CollectingSink())

    assert raised.value.code == "login_expired"


@pytest.mark.asyncio
async def test_an_access_challenge_retries_with_a_fresh_capability_when_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response

    from screamingface._engine import run_client

    def challenged(*_args: object, **_kwargs: object) -> None:
        raise InvalidStatus(Response(401, "Unauthorized", Headers()))

    monkeypatch.setattr(run_client.async_ws, "connect", challenged)
    with run_engine([], {}) as engine:
        transport = AsyncUrl4CloudTransport(engine.url)
        try:
            run_id = await transport.register_run(None, (_candidate(),))
            with pytest.raises(AuthenticationError) as raised:
                await transport.follow_run(run_id, (_candidate(),), AsyncCollectingSink())
        finally:
            await transport.close()

    assert raised.value.code == "login_expired"
    assert not asyncio.all_tasks() - {asyncio.current_task()}


def test_a_dropped_stream_reports_its_close_code_and_elapsed_time() -> None:
    with run_engine([[state(0, "running"), 1001]], {}) as engine:
        with closing(Url4CloudTransport(engine.url)) as transport:
            transport._runs._timings = FollowTimings(0.0, 0.0)
            run_id = transport.register_run(None, (_candidate(),))
            with pytest.raises(ExecutionError) as raised:
                transport.follow_run(run_id, (_candidate(),), CollectingSink())

    assert raised.value.code == "websocket_disconnected"
    assert "engine sent close 1001" in raised.value.message
    assert "s (" in raised.value.message
