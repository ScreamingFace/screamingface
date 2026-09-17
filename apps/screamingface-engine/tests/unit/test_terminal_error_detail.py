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
from screamingface_engine.error_text import ENGINE_ERROR_CODES
from screamingface_engine.runner.connector import _raise_for_status
from screamingface_engine.testing import InMemoryEventStream
from url4.core.errors import CollectionError, RenderError, ResolutionError
from url4.streaming.lifecycle import _error_info
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
    # AIDEV-NOTE: the FIXTURE's code changed in the OME-941 round-3 audit (`malformed_source` ->
    # `unbound_reference`); every assertion below is the one this test has always made. The old
    # fixture's message ("unexpected ')' at position 4") was a genuine ParseError about the
    # caller's own expression — but `malformed_source` is ALSO `CollectionError`'s class default,
    # and those raise sites embed the fetched body, so the code can no longer be allowlisted.
    # The real fix is to give CollectionError its own code; tracked separately.
    resp = await _get_terminal(
        "topic-engine-error",
        _terminated(
            "topic-engine-error",
            "failed",
            error=ErrorInfo(
                code="unbound_reference",
                message="$missing is not bound in this scope",
                permanent=True,
            ),
        ),
    )

    assert resp.status_code == 502
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "unbound_reference"
    assert body["detail"] == "$missing is not bound in this scope"
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


# --------------------------------------------------------------------------------------
# Review round 2 (OME-941): the allowlist must be load-bearing, and the code must not be the
# ONLY thing vouching for the message.
#
# Round 1 rested on "an allowlisted code vouches for the author of the message". It did not:
# `runner/connector.py::_raise_for_status` lifted BOTH `code` and `message` out of the UPSTREAM
# response body, so an upstream answering with an allowlisted code would have had its own text
# echoed verbatim. These tests pin the repair from both ends — the connector no longer lets an
# upstream mint an engine-reserved code, and the HTTP surface bounds and screens every message
# it echoes, whichever code carried it.
# --------------------------------------------------------------------------------------

# Codes the ledger names as deliberately EXCLUDED. Each must scrub. `resolution_failed` leads
# because it is `ResolutionError`'s class default — the code under which connector text and
# `io/http.py`'s `f"GET {url!r} failed: {exc}"` actually arrive.
EXCLUDED_CODES = (
    "resolution_failed",
    "internal_error",
    "aigateway_bad_response",
    "aigateway_http_401",
    "aigateway_empty_response",
    "provider_refusal",
    "model_timeout",
    "judge_unavailable",
    "draco_grading_failed",
    "invalid_candidate_input",
    # Removed from the allowlist by the OME-941 round-3 audit; see error_text.py for the raise
    # site that disproved each. Listed here so re-adding one fails a test.
    "malformed_source",
    "unknown_processor",
    "unrenderable",
    "expansion_not_iterable",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", EXCLUDED_CODES)
async def test_every_excluded_code_scrubs_its_message(code: str) -> None:
    """Adding any of these to the allowlist must break a test, not slip through review."""
    assert code not in ENGINE_ERROR_CODES
    topic = f"topic-excluded-{code}"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(code=code, message=PROVIDER_MESSAGE, permanent=False),
        ),
    )

    body = resp.json()
    assert body["code"] == "internal_error"
    assert body["detail"] == "the run failed"
    raw = resp.content.decode()
    assert PROVIDER_SECRET not in raw
    if code != "internal_error":
        assert code not in raw


# Spelled out by hand ON PURPOSE. Parametrizing over `ENGINE_ERROR_CODES` itself would make
# deleting an entry delete a test case rather than fail one — the mutation survived exactly that
# way on the first attempt. This tuple is the second copy the set is compared against, so adding
# or removing a code fails `test_the_allowlist_is_exactly_this_set` and nothing else has to know.
ALLOWLISTED_CODES = (
    "unbound_reference",
    "cycle_detected",
    "unknown_identity",
    "timeout",
    "result_too_large",
)


def test_the_allowlist_is_exactly_this_set() -> None:
    """Changing the allowlist is a security decision, so it must fail a test to make it."""
    assert ENGINE_ERROR_CODES == frozenset(ALLOWLISTED_CODES)
    assert len(ALLOWLISTED_CODES) == len(set(ALLOWLISTED_CODES))


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ALLOWLISTED_CODES)
async def test_every_allowlisted_code_is_echoed_with_its_message(code: str) -> None:
    """Deleting an entry from the allowlist must break a test too — the set is not decorative."""
    topic = f"topic-allowed-{code}"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(code=code, message="engine authored detail", permanent=True),
        ),
    )

    body = resp.json()
    assert body["code"] == code
    assert body["detail"] == "engine authored detail"


@pytest.mark.asyncio
async def test_an_upstream_message_under_an_allowlisted_code_never_reaches_the_response() -> None:
    """The chain test for the round-1 hole, with the tainted step really executed.

    An upstream answers a model call with an allowlisted code and its own text. That response is
    turned into a `ResolutionError` by the real `_raise_for_status`, then into an `ErrorInfo` by
    url4's real `_error_info`, and only then handed to the GET path. Nothing in the chain is
    hand-built, so the test fails the moment any link starts trusting the upstream again.
    """
    upstream = httpx.Response(
        401,
        json={
            "detail": {
                "code": "malformed_source",
                "message": (
                    f"our cluster db-7 rejected the request; key {PROVIDER_SECRET} is revoked"
                ),
            }
        },
        request=httpx.Request("POST", "http://aigateway.test/v1/chat/completions"),
    )
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(upstream)
    error = _error_info(caught.value)

    topic = "topic-upstream-allowlisted-code"
    resp = await _get_terminal(topic, _terminated(topic, "failed", error=error))

    raw = resp.content.decode()
    assert PROVIDER_SECRET not in raw
    assert "db-7" not in raw
    assert "malformed_source" not in raw
    assert resp.json()["code"] == "internal_error"


@pytest.mark.asyncio
async def test_an_allowlisted_message_is_capped_rather_than_echoed_unbounded() -> None:
    """`malformed_source` embeds `{token!r}` of the caller's expression with no bound of its own."""
    topic = "topic-unbounded-detail"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(code="malformed_source", message="x" * 5_000, permanent=True),
        ),
    )

    detail = resp.json()["detail"]
    assert len(detail) <= 200


@pytest.mark.asyncio
async def test_an_allowlisted_message_carrying_an_internal_marker_is_withheld() -> None:
    """The same screen the benchmark surface applies — one policy module, not two."""
    topic = "topic-marker-detail"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(
                code="malformed_source",
                message='Traceback (most recent call last): File "/srv/engine/runner.py", line 9',
                permanent=True,
            ),
        ),
    )

    body = resp.json()
    assert body["detail"] == "the run failed"
    assert "/srv/engine" not in resp.content.decode()


@pytest.mark.asyncio
async def test_an_allowlisted_message_is_whitespace_normalized() -> None:
    """A newline-bearing detail is one line on the wire, so a log line cannot be forged in it."""
    topic = "topic-newline-detail"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(code="timeout", message="deadline\n\texceeded", permanent=False),
        ),
    )

    assert resp.json()["detail"] == "deadline exceeded"


@pytest.mark.asyncio
async def test_a_trace_id_rides_on_a_stopped_and_a_timed_out_problem_too() -> None:
    """Stated plainly because it is a production body change (review round 2, medium finding).

    Every terminal problem body gains `trace_id` — 409 and 504 included, error or no error —
    because a real run always carries a `traceparent` from `lifecycle.run`. Only a frame with no
    traceparent at all keeps the pre-OME-941 body, and that is not the production case.
    """
    stopped = await _get_terminal(
        "topic-stopped-traced", _terminated("topic-stopped-traced", "stopped")
    )
    assert stopped.status_code == 409
    assert stopped.json()["trace_id"] == TRACE_ID

    timed_out = await _get_terminal(
        "topic-timeout-traced", _terminated("topic-timeout-traced", "timed_out")
    )
    assert timed_out.status_code == 504
    assert timed_out.json()["trace_id"] == TRACE_ID


@pytest.mark.asyncio
async def test_a_marker_only_allowlisted_message_is_withheld_with_no_path_to_help() -> None:
    """Isolates the marker screen from the path screen.

    The traceback test above also trips the PATH pattern, so deleting the internal-marker branch
    of `public_message` survived it. This message carries a marker and NO path, so only the
    marker branch can withhold it.
    """
    topic = "topic-marker-only"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(
                code="malformed_source",
                message="Traceback (most recent call last): line 9 in handler",
                permanent=True,
            ),
        ),
    )

    body = resp.json()
    assert body["detail"] == "the run failed"
    assert "handler" not in resp.content.decode()


@pytest.mark.asyncio
async def test_an_allowlisted_message_carrying_a_credential_is_withheld() -> None:
    """A vouched author is not a guarantee of vouched CONTENT.

    `malformed_source` is raised about the caller's own expression, and an expression can embed
    a key. The credential screen runs on an allowlisted message too — no code exempts it.
    """
    topic = "topic-credential-detail"
    resp = await _get_terminal(
        topic,
        _terminated(
            topic,
            "failed",
            error=ErrorInfo(
                code="malformed_source",
                message=f"unexpected token {PROVIDER_SECRET!r} at position 12",
                permanent=True,
            ),
        ),
    )

    body = resp.json()
    assert body["detail"] == "the run failed"
    assert PROVIDER_SECRET not in resp.content.decode()


# --- the allowlist cannot vouch for a message it does not author (OME-941 round 3) -------------
#
# WHY these exist: the allowlist's premise is "an allowlisted code means url4 core authored this
# message about the CALLER'S OWN expression". Auditing all nine raise sites showed the premise is
# false for four of them, for two distinct reasons:
#
#   1. A CODE IS NOT AN AUTHOR. `malformed_source` is the class default of BOTH `ParseError`
#      (genuinely about the caller's expression) and `CollectionError` (whose io/layer.py raise
#      sites interpolate the FETCHED BODY). One code, two authors — no allowlist entry can be
#      right for it.
#   2. MESSAGES INTERPOLATE RESOLVED VALUES. `unknown_processor` embeds `{resolved!r}` from
#      `await spawn(value)` — a model output. `unrenderable` embeds `{text!r}`, the rendered form
#      of an AST that may carry a fetched value. `expansion_not_iterable` embeds `{exc}` of the
#      CollectionError from reason 1.
#
# Each case below builds the REAL exception class the way its real raise site builds it, so these
# fail if anyone re-adds the code — and keep failing if a raise site starts interpolating.

# WHY a prose canary and NOT `PROVIDER_SECRET`: the first version of these tests used the
# `sk-proj-…` secret and PASSED before the allowlist was narrowed — `public_message`'s credential
# screen caught the token, so the test proved the screen works and said nothing about the
# allowlist. Real leaked remote text is not credential-shaped: it is a model refusal, a fetched
# document, an upstream error sentence. This canary is deliberately ordinary prose so the ONLY
# thing that can withhold it is the code not being allowlisted.
REMOTE_TEXT = "the patient record for Jane Doe was not found in the archive"

LEAKY_RAISE_SITES = (
    pytest.param(
        "malformed_source",
        lambda text: CollectionError(
            f"collection source resolved to a scalar value, "
            f"not an iterable collection: {text[:80]!r}"
        ),
        id="malformed_source-CollectionError-embeds-fetched-body",
    ),
    pytest.param(
        "expansion_not_iterable",
        lambda text: ResolutionError(
            f"expansion source is not iterable: {CollectionError(text)}",
            code="expansion_not_iterable",
        ),
        id="expansion_not_iterable-wraps-the-collection-error",
    ),
    pytest.param(
        "unknown_processor",
        lambda text: ResolutionError(
            f"processor expression resolved to another expression ({text!r}); "
            "resolution is single-pass",
            code="unknown_processor",
            permanent=True,
        ),
        id="unknown_processor-embeds-spawn-output",
    ),
    pytest.param(
        "unrenderable",
        lambda text: RenderError(f"rendered text {text!r} does not reparse: unbalanced"),
        id="unrenderable-embeds-rendered-ast-text",
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "build"), LEAKY_RAISE_SITES)
async def test_a_real_raise_site_carrying_remote_text_never_reaches_the_response(
    code: str, build: object
) -> None:
    """The exception is built as its REAL raise site builds it, then travels the real path:
    `_error_info` reads `getattr(exc, "code")` and `str(exc)`, exactly as `lifecycle.run` does."""
    exc = build(REMOTE_TEXT)  # type: ignore[operator]
    info = _error_info(exc)

    assert info.code == code, "the fixture must reproduce the real raise site's code"
    assert REMOTE_TEXT in info.message, "the fixture must actually carry the remote text"

    topic = f"topic-leaky-{code}"
    resp = await _get_terminal(topic, _terminated(topic, "failed", error=info))

    assert REMOTE_TEXT not in resp.content.decode(), (
        f"{code} echoed a message its raise site interpolated from remote data"
    )
