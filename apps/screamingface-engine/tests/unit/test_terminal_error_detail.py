"""The transactional GET path must report WHY a run ended, and under which trace (OME-941).

`_terminal_response` used to read only `TerminatedData.status`, so a synchronous caller got a
bare `502 "the run failed"` while the real `ErrorInfo` sat on the stream that is purged moments
later. These tests pin the two halves of surfacing it:

- the useful half — an engine-authored code, its message and the run's `trace_id` reach the
  problem body;
- the dangerous half — an error code the engine did not author is NOT passed through, and its
  message (which is `str(exc)`, i.e. provider text verbatim for any provider-facing adapter)
  reaches the response nowhere at all.

ASSERTION RULE for this file: never assert over `repr()` of a model or a container. A
`repr(...)` of a pydantic object renders as `<... object at 0x...>` under some configurations and
a substring check against it passes for anything — this repo has already shipped one security
test that was green against a live leak for exactly that reason. Leak checks here walk the
decoded JSON fields AND the raw response bytes.
"""

from datetime import UTC, datetime

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.protocol import ErrorInfo, TerminatedData, TerminatedEvent

SECRET = "terminal-error-secret"
WINDOW_S = 60
LIFETIME_S = 58_800
T0 = datetime(2026, 9, 17, 9, 0, 0, tzinfo=UTC)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID = "00f067aa0ba902b7"
TRACEPARENT = f"00-{TRACE_ID}-{SPAN_ID}-01"

# What a provider-facing adapter's exception actually looks like once `_error_info` has turned it
# into an `ErrorInfo`: a code the engine never authored, and `str(exc)` carrying the upstream body.
PROVIDER_CODE = "aigateway_bad_response"
PROVIDER_MESSAGE = (
    "openai 401: {'error': {'message': 'Incorrect API key provided: sk-proj-A1b2C3d4E5f6G7h8. "
    "You can find your API key at https://platform.openai.com/account/api-keys'}}"
)
PROVIDER_SECRET = "sk-proj-A1b2C3d4E5f6G7h8"


def _cap(topic: str) -> dict[str, str]:
    codec = JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S)
    return {"URL4-Capability": codec.sign(topic, T0)}


def _make_app(stream: InMemoryEventStream) -> FastAPI:
    return create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S, sync_max_wait_s=5.0),
        stream=stream,
        job_runner=RecordingJobRunner(),
        clock=lambda: T0,
        interest=FixedGate(True),
    )


def _terminated(
    topic: str,
    status: str,
    *,
    error: ErrorInfo | None = None,
    traceparent: str | None = TRACEPARENT,
) -> TerminatedEvent:
    return TerminatedEvent(
        id=f"term-{topic}",
        source=f"/trace/{topic}/node/root",
        subject=topic,
        traceparent=traceparent,
        data=TerminatedData(status=status, error=error),  # type: ignore[arg-type]
    )


async def _get_terminal(topic: str, event: TerminatedEvent) -> httpx.Response:
    """Publish `event` as `topic`'s only frame and return the synchronous GET's response."""
    stream = InMemoryEventStream()
    await stream.publish(topic, event)
    transport = ASGITransport(app=_make_app(stream))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/", params={"q": "gpt()"}, headers=_cap(topic))


@pytest.mark.asyncio
async def test_a_failed_run_names_its_engine_error_code_message_and_trace_id() -> None:
    resp = await _get_terminal(
        "topic-engine-error",
        _terminated(
            "topic-engine-error",
            "failed",
            error=ErrorInfo(
                code="malformed_source",
                message="unexpected ')' at position 4",
                permanent=True,
            ),
        ),
    )

    assert resp.status_code == 502
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "malformed_source"
    assert body["detail"] == "unexpected ')' at position 4"
    assert body["permanent"] is True
    assert body["trace_id"] == TRACE_ID


@pytest.mark.asyncio
async def test_a_provider_authored_message_never_reaches_the_http_response() -> None:
    topic = "topic-provider-leak"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(code=PROVIDER_CODE, message=PROVIDER_MESSAGE, permanent=False),
        ),
    )

    assert resp.status_code == 502
    body = resp.json()
    # The code the engine did not author is not passed through...
    assert body["code"] == "internal_error"
    assert PROVIDER_CODE not in body["code"]
    # ...and the detail falls back to the fixed table entry, carrying none of the message.
    assert body["detail"] == "the run failed"
    # Field-by-field, then over the raw bytes: no member of the body carries any fragment of the
    # provider's text, and neither does anything else the response happens to serialise.
    for name, value in body.items():
        assert isinstance(value, str | int | bool)
        if isinstance(value, str):
            assert PROVIDER_SECRET not in value, name
            assert "platform.openai.com" not in value, name
            assert PROVIDER_MESSAGE not in value, name
    raw = resp.content.decode()
    assert PROVIDER_SECRET not in raw
    assert "platform.openai.com" not in raw
    assert "Incorrect API key" not in raw
    assert PROVIDER_CODE not in raw


@pytest.mark.asyncio
async def test_a_scrubbed_error_still_reports_permanent_and_the_trace_id() -> None:
    """Scrubbing the text must not cost the caller the two fields that cannot leak."""
    topic = "topic-scrubbed-fields"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(code=PROVIDER_CODE, message=PROVIDER_MESSAGE, permanent=False),
        ),
    )

    body = resp.json()
    assert body["permanent"] is False
    assert body["trace_id"] == TRACE_ID


@pytest.mark.asyncio
async def test_the_topic_is_never_rendered_into_a_terminal_problem() -> None:
    """The topic is a bearer capability: echoing it into an error body hands it to any log."""
    topic = "topic-capability-must-not-leak"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(code="malformed_source", message="bad expression", permanent=True),
        ),
    )

    assert topic not in resp.content.decode()


@pytest.mark.asyncio
async def test_a_timed_out_run_surfaces_its_error_detail_too() -> None:
    """The detail path keys off the error frame, not off which terminal status produced it."""
    topic = "topic-timeout-detail"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "timed_out",
            error=ErrorInfo(code="timeout", message="deadline of 30s exceeded", permanent=False),
        ),
    )

    assert resp.status_code == 504
    body = resp.json()
    assert body["code"] == "timeout"
    assert body["detail"] == "deadline of 30s exceeded"
    assert body["trace_id"] == TRACE_ID


@pytest.mark.asyncio
async def test_a_malformed_traceparent_yields_no_trace_id_rather_than_a_junk_one() -> None:
    """A field the caller would paste into a trace search must be a real id or absent."""
    topic = "topic-bad-traceparent"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(code="malformed_source", message="bad expression", permanent=True),
            traceparent="not-a-traceparent",
        ),
    )

    assert "trace_id" not in resp.json()


@pytest.mark.asyncio
async def test_an_all_zero_trace_id_is_not_reported() -> None:
    """W3C's invalid all-zero trace id would otherwise look like a legitimate run to search for."""
    topic = "topic-zero-trace"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(code="malformed_source", message="bad expression", permanent=True),
            traceparent=f"00-{'0' * 32}-{SPAN_ID}-01",
        ),
    )

    assert "trace_id" not in resp.json()


@pytest.mark.asyncio
async def test_a_terminal_frame_without_an_error_keeps_the_table_response() -> None:
    """The pre-OME-941 body shape survives verbatim when there is nothing extra to say."""
    topic = "topic-no-error"
    resp = await _get_terminal(topic, _terminated(topic, "stopped", error=None, traceparent=None))

    assert resp.status_code == 409
    assert resp.json() == {
        "type": "about:blank",
        "title": "Conflict",
        "status": 409,
        "detail": "the run was stopped",
    }


@pytest.mark.asyncio
async def test_a_trace_id_is_reported_even_when_the_run_carried_no_error() -> None:
    """Traceability is the point of the epic: a stopped run is still a run worth finding."""
    topic = "topic-no-error-traced"
    resp = await _get_terminal(topic, _terminated(topic, "stopped", error=None))

    assert resp.json()["trace_id"] == TRACE_ID
