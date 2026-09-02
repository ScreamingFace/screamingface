"""Confirmed SF Engine transport contract against a controlled protocol server."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from contextlib import closing
from typing import Any, cast

import httpx
import pytest
from protocol_server import protocol_server

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._engine.transport import (
    AsyncUrl4CloudTransport,
    Url4CloudTransport,
    _attachment_is_still_registering,
    _start_sync,
)
from screamingface._evaluation.model import (
    Candidate,
    _compiled_candidate,
    _compiled_operation,
)


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


def test_transport_attaches_before_start_and_returns_the_root_outcome() -> None:
    with protocol_server() as engine:
        outcome = _run(engine.url)

    assert outcome.result_body == "[test] done"
    assert engine.state.inbound_events[0]["type"] == "ai.url4.attach"
    assert engine.state.inbound_events[0]["data"] == {"from_sequence": None}


@pytest.mark.asyncio
async def test_async_transport_has_the_same_attach_and_result_boundary() -> None:
    with protocol_server() as engine:
        outcome = await _arun(engine.url)

    assert outcome.result_body == "[test] done"
    assert engine.state.inbound_events[0]["type"] == "ai.url4.attach"
    assert engine.state.inbound_events[0]["data"] == {"from_sequence": None}


def test_transport_retries_while_the_websocket_attachment_is_registering() -> None:
    with protocol_server(mode="delayed_attach") as engine:
        outcome = _run(engine.url)

    assert outcome.result_body == "[test] done"
    assert engine.state.start_attempts >= 2


@pytest.mark.asyncio
async def test_async_transport_retries_the_same_attachment_race() -> None:
    with protocol_server(mode="delayed_attach") as engine:
        outcome = await _arun(engine.url)

    assert outcome.result_body == "[test] done"
    assert engine.state.start_attempts >= 2


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(202), False),
        (httpx.Response(428, text="attach a WebSocket"), False),
        (
            httpx.Response(
                428,
                content=b"not-json",
                headers={"content-type": "application/problem+json"},
            ),
            False,
        ),
        (
            httpx.Response(
                428,
                json=[],
                headers={"content-type": "application/problem+json"},
            ),
            False,
        ),
        (
            httpx.Response(
                428,
                json={"detail": 1},
                headers={"content-type": "application/problem+json"},
            ),
            False,
        ),
        (
            httpx.Response(
                428,
                json={"detail": "A different precondition"},
                headers={"content-type": "application/problem+json"},
            ),
            False,
        ),
        (
            httpx.Response(
                428,
                json={"detail": "Attach a WebSocket to the topic before starting the run."},
                headers={"content-type": "application/problem+json"},
            ),
            True,
        ),
    ],
)
def test_only_the_attachment_registration_problem_is_retried(
    response: httpx.Response,
    expected: bool,
) -> None:
    assert _attachment_is_still_registering(response) is expected


def test_start_connection_failure_is_reported_as_engine_unavailable() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("engine offline", request=request)

    with httpx.Client(
        base_url="http://engine.test",
        transport=httpx.MockTransport(fail),
    ) as http:
        with pytest.raises(sf.EngineUnavailableError, match="Could not start"):
            _start_sync(http, "test-capability", "(@)!'hello'")


def test_callback_failure_stops_the_attached_run_and_reraises() -> None:
    original = RuntimeError("progress renderer failed")

    def fail(event: sf.Event) -> None:
        raise original

    with protocol_server(mode="stop") as engine:
        with pytest.raises(RuntimeError) as caught:
            _run(engine.url, fail)

    assert caught.value is original
    assert [event["type"] for event in engine.state.inbound_events] == [
        "ai.url4.attach",
        "ai.url4.stop",
    ]


def test_keyboard_interrupt_stops_the_attached_run_and_reraises() -> None:
    def interrupt(event: sf.Event) -> None:
        raise KeyboardInterrupt

    with protocol_server(mode="stop") as engine:
        with pytest.raises(KeyboardInterrupt):
            _run(engine.url, interrupt)

    assert [event["type"] for event in engine.state.inbound_events] == [
        "ai.url4.attach",
        "ai.url4.stop",
    ]


@pytest.mark.asyncio
async def test_async_callback_failure_has_the_same_stop_behavior() -> None:
    original = RuntimeError("async progress renderer failed")

    async def fail(event: sf.Event) -> None:
        raise original

    with protocol_server(mode="stop") as engine:
        with pytest.raises(RuntimeError) as caught:
            await _arun(engine.url, fail)

    assert caught.value is original
    assert [event["type"] for event in engine.state.inbound_events] == [
        "ai.url4.attach",
        "ai.url4.stop",
    ]


@pytest.mark.asyncio
async def test_async_cancellation_stops_the_attached_run_and_reraises() -> None:
    async def cancel(event: sf.Event) -> None:
        raise asyncio.CancelledError

    with protocol_server(mode="stop") as engine:
        with pytest.raises(asyncio.CancelledError):
            await _arun(engine.url, cancel)

    assert [event["type"] for event in engine.state.inbound_events] == [
        "ai.url4.attach",
        "ai.url4.stop",
    ]


def test_sequence_gap_reattaches_from_the_first_missing_event() -> None:
    with protocol_server(mode="gap") as engine:
        _run(engine.url)

    assert [event["data"] for event in engine.state.inbound_events] == [
        {"from_sequence": None},
        {"from_sequence": 2},
    ]


@pytest.mark.asyncio
async def test_async_sequence_gap_reattaches_from_the_first_missing_event() -> None:
    with protocol_server(mode="gap") as engine:
        await _arun(engine.url)

    assert [event["data"] for event in engine.state.inbound_events] == [
        {"from_sequence": None},
        {"from_sequence": 2},
    ]


def test_silent_event_stream_times_out_and_stops_the_paid_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "screamingface._engine.transport._EVENT_RECEIVE_TIMEOUT_SECONDS",
        0.1,
    )
    with protocol_server(mode="stop") as engine:
        with pytest.raises(sf.ExecutionError) as caught:
            _run(engine.url)

    assert caught.value.code == "event_stream_timeout"
    assert caught.value.permanent is False
    assert [event["type"] for event in engine.state.inbound_events] == [
        "ai.url4.attach",
        "ai.url4.stop",
    ]


@pytest.mark.asyncio
async def test_async_silent_event_stream_has_the_same_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "screamingface._engine.transport._EVENT_RECEIVE_TIMEOUT_SECONDS",
        0.1,
    )
    with protocol_server(mode="stop") as engine:
        with pytest.raises(sf.ExecutionError) as caught:
            await _arun(engine.url)

    assert caught.value.code == "event_stream_timeout"
    assert [event["type"] for event in engine.state.inbound_events] == [
        "ai.url4.attach",
        "ai.url4.stop",
    ]


def test_disconnect_before_terminal_state_is_an_execution_error() -> None:
    with protocol_server(mode="disconnect") as engine:
        with pytest.raises(sf.ExecutionError, match="disconnected") as caught:
            _run(engine.url)

    assert caught.value.code == "websocket_disconnected"
    assert caught.value.permanent is False


@pytest.mark.asyncio
async def test_async_disconnect_before_terminal_state_is_an_execution_error() -> None:
    with protocol_server(mode="disconnect") as engine:
        with pytest.raises(sf.ExecutionError, match="disconnected") as caught:
            await _arun(engine.url)

    assert caught.value.code == "websocket_disconnected"
    assert caught.value.permanent is False


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("token_invalid_json", "must be JSON"),
        ("token_malformed", "is malformed"),
    ],
)
def test_transport_rejects_malformed_capability_responses(
    mode: str,
    message: str,
) -> None:
    with protocol_server(mode=cast(Any, mode)) as engine:
        with pytest.raises(sf.ExecutionError, match=message):
            _run(engine.url)


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("missing_preference", "acknowledge asynchronous"),
        ("missing_location", "missing Location"),
    ],
)
def test_transport_rejects_incomplete_async_start_responses(
    mode: str,
    message: str,
) -> None:
    with protocol_server(mode=cast(Any, mode)) as engine:
        with pytest.raises(sf.ExecutionError, match=message):
            _run(engine.url)


def test_start_problem_is_preserved_as_an_execution_error() -> None:
    with protocol_server(mode="start_error") as engine:
        with pytest.raises(sf.ExecutionError, match="test runner is unavailable") as caught:
            _run(engine.url)

    assert caught.value.code == "runner_unavailable"
    assert caught.value.status == 502
    assert caught.value.permanent is False
    assert caught.value.details == {
        "type": "runner_unavailable",
        "title": "Runner unavailable",
        "status": 502,
        "detail": "The test runner is unavailable.",
    }


def test_authentication_problem_preserves_structured_diagnostics() -> None:
    with protocol_server(mode="start_auth_error") as engine:
        with pytest.raises(sf.AuthenticationError) as caught:
            _run(engine.url)

    assert str(caught.value) == ("Could not start the Run: The execution capability expired.")
    assert caught.value.code == "capability_expired"
    assert caught.value.status == 401
    assert caught.value.permanent is True
    assert caught.value.details == {
        "type": "capability_expired",
        "title": "Capability expired",
        "status": 401,
        "detail": "The execution capability expired.",
    }


def test_transport_observer_receives_public_events_in_order() -> None:
    seen: list[sf.Event] = []
    with protocol_server() as engine:
        _run(engine.url, seen.append)

    assert [event.kind for event in seen] == ["started", "usage", "terminated"]


@pytest.mark.asyncio
async def test_async_callback_is_awaited_in_event_order() -> None:
    seen: list[str] = []

    async def observe(event: sf.Event) -> None:
        seen.append(event.kind)

    with protocol_server() as engine:
        await _arun(engine.url, observe)

    assert seen == ["started", "usage", "terminated"]


def test_heartbeat_is_consumed_as_internal_liveness() -> None:
    seen: list[str] = []
    with protocol_server(mode="heartbeat") as engine:
        _run(engine.url, lambda event: seen.append(event.kind))

    assert seen == ["started", "usage", "terminated"]


def test_advisory_error_is_consumed_without_terminating_the_run() -> None:
    seen: list[str] = []
    with protocol_server(mode="advisory_error") as engine:
        outcome = _run(engine.url, lambda event: seen.append(event.kind))

    assert outcome.result_body == "[test] done"
    assert seen == ["started", "usage", "terminated"]


def test_stream_failure_reattaches_then_fails_instead_of_hanging() -> None:
    with protocol_server(mode="stream_failed") as engine:
        with pytest.raises(sf.ExecutionError) as caught:
            _run(engine.url)

    assert caught.value.code == "event_stream_failed"
    assert caught.value.permanent is False
    assert caught.value.details == {
        "code": "stream_failed",
        "message": "the topic subscription failed (ServerError); re-attach to resume",
        "ref_id": None,
    }
    assert [event["type"] for event in engine.state.inbound_events] == [
        "ai.url4.attach",
        "ai.url4.attach",
        "ai.url4.attach",
        "ai.url4.attach",
        "ai.url4.stop",
    ]
    assert [event["data"] for event in engine.state.inbound_events[1:4]] == [
        {"from_sequence": 1},
        {"from_sequence": 1},
        {"from_sequence": 1},
    ]


@pytest.mark.asyncio
async def test_async_stream_failure_has_the_same_bounded_behavior() -> None:
    with protocol_server(mode="stream_failed") as engine:
        with pytest.raises(sf.ExecutionError) as caught:
            await _arun(engine.url)

    assert caught.value.code == "event_stream_failed"
    assert [event["type"] for event in engine.state.inbound_events] == [
        "ai.url4.attach",
        "ai.url4.attach",
        "ai.url4.attach",
        "ai.url4.attach",
        "ai.url4.stop",
    ]


@pytest.mark.parametrize("error", [OSError("observer failed"), TimeoutError("observer timed out")])
def test_transport_preserves_disconnect_shaped_callback_exceptions(
    error: BaseException,
) -> None:
    def fail(event: sf.Event) -> None:
        raise error

    with protocol_server(mode="stop") as engine:
        with pytest.raises(type(error)) as caught:
            _run(engine.url, fail)

    assert caught.value is error


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("observer failed"), TimeoutError("observer timed out")])
async def test_async_transport_preserves_disconnect_shaped_callback_exceptions(
    error: BaseException,
) -> None:
    async def fail(event: sf.Event) -> None:
        raise error

    with protocol_server(mode="stop") as engine:
        with pytest.raises(type(error)) as caught:
            await _arun(engine.url, fail)

    assert caught.value is error


def test_an_out_of_band_notice_does_not_kill_a_paid_run() -> None:
    # STORY: as a researcher whose cache directive was overridden, the Engine tells me so and
    # the Run I am paying for keeps going. Before this, the notice aborted the Run outright.
    seen: list[str] = []
    with protocol_server(mode="unsequenced_log") as engine:
        outcome = _run(engine.url, lambda event: seen.append(event.kind))

    assert outcome.result_body == "[test] done"
    assert seen == ["started", "usage", "terminated"]


@pytest.mark.asyncio
async def test_an_out_of_band_notice_does_not_kill_a_paid_async_run() -> None:
    seen: list[str] = []
    with protocol_server(mode="unsequenced_log") as engine:
        outcome = await _arun(engine.url, lambda event: seen.append(event.kind))

    assert outcome.result_body == "[test] done"
    assert seen == ["started", "usage", "terminated"]


# --- client-originated trace context (OME-967) --------------------------------------------

_TRACEPARENT = re.compile(r"^00-(?!0{32}$)[0-9a-f]{32}-(?!0{16}$)[0-9a-f]{16}-[0-9a-f]{2}$")
"""The shape url4's own `_TRACEPARENT_RE` accepts, plus its two all-zero rejections.

WHY duplicated rather than imported: `packages/screamingface` does not depend on `url4`
(httpx, pynacl, pyyaml, websockets), and OME-967 mints locally rather than adding a
distribution dependency for four lines of string formatting. This regex is the contract
between the two packages, so it is stated where it is asserted.
"""


def test_the_client_originates_trace_context_on_every_leg_of_a_run() -> None:
    # INVARIANT (OME-967): the trace id must exist BEFORE the first outbound call, not
    # before the run starts. Capability mint, run start and WS handshake are the three
    # failure classes that today carry no id at all and are unjoinable forever.
    with protocol_server() as engine:
        _run(engine.url)

    phases = {phase for phase, value in engine.state.traceparents if value}
    assert phases == {"mint", "start", "websocket"}
    assert all(_TRACEPARENT.match(value or "") for _, value in engine.state.traceparents)


def test_one_run_carries_one_trace_id_across_all_of_its_legs() -> None:
    # WHY this is separate from the shape check: three well-formed but DIFFERENT ids would
    # satisfy the assertion above and still be useless — the join key is the trace id being
    # the same one everywhere.
    with protocol_server() as engine:
        _run(engine.url)

    assert len(engine.state.trace_ids()) == 1


@pytest.mark.asyncio
async def test_the_async_client_originates_the_same_trace_context() -> None:
    with protocol_server() as engine:
        await _arun(engine.url)

    phases = {phase for phase, value in engine.state.traceparents if value}
    assert phases == {"mint", "start", "websocket"}
    assert len(engine.state.trace_ids()) == 1


def test_the_trace_id_the_client_sent_is_the_one_it_reports_on_the_outcome() -> None:
    # The ticket's second Verify item: the id the client holds must equal the id on the wire,
    # or the user quotes an id that appears in no log.
    with protocol_server() as engine:
        outcome = _run(engine.url)

    assert outcome.trace_id in engine.state.trace_ids()


def test_a_run_that_never_starts_still_surfaces_a_trace_id_to_the_caller() -> None:
    # INVARIANT (OME-967): this is consequence #1 of the ticket — a pre-first-frame failure.
    # It raises EngineUnavailableError, NOT ExecutionError, which is why the id lives on the
    # base error class rather than on ExecutionError alone.
    with protocol_server(mode="start_error") as engine:
        with pytest.raises(sf.ScreamingFaceError) as raised:
            _run(engine.url)

    assert raised.value.trace_id
    assert raised.value.trace_id in engine.state.trace_ids()


def test_a_surfaced_trace_id_is_rendered_where_the_user_can_read_it() -> None:
    # An id retained on the exception but never shown is the status quo: the client already
    # receives `traceparent` on every event and has zero read sites for it.
    error = sf.ExecutionError("the run failed", trace_id="4bf92f3577b34da6a3ce929d0e0e4736")

    rendered = "\n".join(error._render_traceback_())

    assert "4bf92f3577b34da6a3ce929d0e0e4736" in rendered
