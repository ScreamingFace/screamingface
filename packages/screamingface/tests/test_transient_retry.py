"""Replay-safe requests survive a transient edge failure (OME-1107).

A single Cloudflare 520 on one `POST /token` destroyed an evaluation of 8 candidates after 7
had already finished, because nothing retried a request the SDK itself had declared safe to
replay. The origin was healthy the whole time — the blip lived above it, in the tunnel.

INVARIANT under test: retry is gated on the `_REPLAY_SAFE` request extension, NEVER on the
HTTP method. `GET /?q=` starts billable work despite being a GET and carries no marker, so it
must never be replayed. That is the property these tests exist to protect — every other
assertion here is secondary to it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from screamingface._core.retry import RetryingAsyncTransport, RetryingTransport
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._engine.transport import _require_success
from screamingface.errors import ExecutionError

type _Outcome = int | tuple[int, dict[str, str]] | Exception


class _Recorder:
    """A handler that replays a scripted sequence of outcomes and counts attempts."""

    def __init__(self, *outcomes: _Outcome) -> None:
        self._outcomes: list[_Outcome] = list(outcomes)
        self.attempts = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        outcome = self._outcomes[min(self.attempts - 1, len(self._outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, tuple):
            status, headers = outcome
            return httpx.Response(status, headers=headers, text="body")
        return httpx.Response(outcome, text="body")


@dataclass
class _Rig:
    """A client plus the delays its transport was asked to sleep for."""

    client: httpx.Client
    slept: list[float]


def _rig(
    handler: _Recorder,
    *,
    attempts: int = 3,
    base_delay: float = 0.25,
    max_retry_after: float = 30.0,
    jitter: Callable[[], float] = lambda: 0.0,
) -> _Rig:
    slept: list[float] = []
    transport = RetryingTransport(
        httpx.MockTransport(handler),
        attempts=attempts,
        base_delay=base_delay,
        max_retry_after=max_retry_after,
        sleep=slept.append,
        jitter=jitter,
    )
    return _Rig(httpx.Client(transport=transport, base_url="https://engine.test"), slept)


async def _no_sleep(_seconds: float) -> None:
    return None


def _async_client(handler: _Recorder) -> httpx.AsyncClient:
    transport = RetryingAsyncTransport(httpx.MockTransport(handler), sleep=_no_sleep)
    return httpx.AsyncClient(transport=transport, base_url="https://engine.test")


# ── the invariant ────────────────────────────────────────────────────────────────────────


def test_a_request_without_the_replay_marker_is_never_retried() -> None:
    """THE load-bearing assertion. `GET /?q=` starts a Run despite being a GET and carries no
    marker; replaying it would double-fire billable work. Default-deny, no exceptions."""
    handler = _Recorder(520, 200)
    rig = _rig(handler)
    with rig.client as client:
        response = client.get("/", params={"q": "expr"})
    assert response.status_code == 520, "an unmarked request must surface its failure as-is"
    assert handler.attempts == 1, "an unmarked request must be sent exactly once"


@pytest.mark.asyncio
async def test_the_async_transport_never_retries_an_unmarked_request() -> None:
    """The async twin of the load-bearing invariant."""
    handler = _Recorder(520, 200)
    async with _async_client(handler) as client:
        response = await client.get("/", params={"q": "expr"})
    assert response.status_code == 520
    assert handler.attempts == 1


# ── retrying what IS safe ────────────────────────────────────────────────────────────────


def test_a_replay_safe_request_survives_a_transient_edge_failure() -> None:
    """The incident, reproduced: one 520 then success. The caller must never see the 520."""
    handler = _Recorder(520, 200)
    rig = _rig(handler)
    with rig.client as client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 200
    assert handler.attempts == 2


@pytest.mark.asyncio
async def test_the_async_transport_retries_a_replay_safe_request() -> None:
    handler = _Recorder(520, 200)
    async with _async_client(handler) as client:
        response = await client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 200
    assert handler.attempts == 2


@pytest.mark.parametrize("status", [502, 503, 504, 520, 522, 524, 408, 429])
def test_retryable_statuses_are_retried(status: int) -> None:
    handler = _Recorder(status, 200)
    rig = _rig(handler)
    with rig.client as client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 200
    assert handler.attempts == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 500])
def test_non_retryable_statuses_are_returned_immediately(status: int) -> None:
    """A deterministic failure is not made better by repetition. 500 is deliberately excluded:
    an application error repeats, and retrying only hides it."""
    handler = _Recorder(status, 200)
    rig = _rig(handler)
    with rig.client as client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == status
    assert handler.attempts == 1


# ── bounds and pacing ────────────────────────────────────────────────────────────────────


def test_the_attempt_budget_is_bounded() -> None:
    """A permanently failing edge must surface, not spin."""
    handler = _Recorder(520)
    rig = _rig(handler, attempts=3)
    with rig.client as client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 520
    assert handler.attempts == 3


def test_backoff_grows_between_attempts() -> None:
    """Bounded exponential backoff — a tight loop against a struggling edge is a second
    outage, not a recovery."""
    handler = _Recorder(520, 520, 200)
    rig = _rig(handler, attempts=3, base_delay=0.5)
    with rig.client as client:
        client.post("/token", extensions={_REPLAY_SAFE: True})
    assert len(rig.slept) == 2
    assert rig.slept[1] > rig.slept[0]


def test_retry_after_delta_seconds_is_honoured() -> None:
    """The server named a number; second-guessing it is how a thundering herd starts."""
    handler = _Recorder((503, {"Retry-After": "2"}), 200)
    rig = _rig(handler)
    with rig.client as client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 200
    assert rig.slept == pytest.approx([2.0])


def test_retry_after_beyond_the_cap_stops_rather_than_sleeping() -> None:
    """Obeying an hour-long Retry-After is indistinguishable from a hang. Surfacing the
    response lets the caller decide."""
    handler = _Recorder((503, {"Retry-After": "3600"}), 200)
    rig = _rig(handler, max_retry_after=30.0)
    with rig.client as client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 503
    assert handler.attempts == 1
    assert rig.slept == []


def test_a_transport_error_is_retried_then_surfaces() -> None:
    handler = _Recorder(httpx.ConnectError("boom"), httpx.ConnectError("boom"))
    rig = _rig(handler, attempts=2)
    with rig.client as client, pytest.raises(httpx.ConnectError):
        client.post("/token", extensions={_REPLAY_SAFE: True})
    assert handler.attempts == 2


def test_a_transport_error_recovers_when_a_later_attempt_succeeds() -> None:
    handler = _Recorder(httpx.ConnectError("boom"), 200)
    rig = _rig(handler)
    with rig.client as client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 200


# ── error messages stay readable ─────────────────────────────────────────────────────────


def test_an_html_error_page_is_reduced_to_its_status() -> None:
    """The second half of the incident: a Cloudflare 520 reached the user as ~7KB of markup,
    with the only useful token buried inside it."""
    page = (
        "<!DOCTYPE html>\n<html><head><title>520</title></head><body>"
        + "x" * 5000
        + "</body></html>"
    )
    response = httpx.Response(520, text=page, headers={"content-type": "text/html"})
    with pytest.raises(ExecutionError) as raised:
        _require_success(response, "mint an execution capability")
    message = str(raised.value)
    assert "HTTP 520" in message
    assert "<!DOCTYPE" not in message
    assert "<html" not in message
    assert len(message) < 200


def test_a_short_plain_text_body_is_kept() -> None:
    """Bounded, not blind: a short plain reason is exactly what belongs in the message."""
    response = httpx.Response(503, text="upstream busy", headers={"content-type": "text/plain"})
    with pytest.raises(ExecutionError) as raised:
        _require_success(response, "mint an execution capability")
    assert "HTTP 503" in str(raised.value)
    assert "upstream busy" in str(raised.value)


def test_a_long_plain_text_body_is_truncated() -> None:
    response = httpx.Response(502, text="y" * 4000, headers={"content-type": "text/plain"})
    with pytest.raises(ExecutionError) as raised:
        _require_success(response, "mint an execution capability")
    assert len(str(raised.value)) < 400


def test_a_problem_json_detail_is_still_preferred() -> None:
    """INVARIANT preserved: what the Engine itself says is structured, and still wins."""
    response = httpx.Response(
        503,
        json={"type": "about:blank", "detail": "the runner is at capacity — retry shortly"},
        headers={"content-type": "application/problem+json"},
    )
    with pytest.raises(ExecutionError) as raised:
        _require_success(response, "start the SF Engine Run")
    assert "the runner is at capacity" in str(raised.value)


# ── Retry-After: the HTTP-date wire form ─────────────────────────────────────────────────


def test_retry_after_http_date_is_honoured() -> None:
    """A server may send `Retry-After` as an HTTP-date instead of delta-seconds (RFC 9110
    §10.2.3) — both forms are the same server-named number, just spelled differently, and
    second-guessing either is how a thundering herd starts."""
    target = format_datetime(datetime.now(UTC) + timedelta(seconds=5), usegmt=True)
    handler = _Recorder((503, {"Retry-After": target}), 200)
    rig = _rig(handler)
    with rig.client as client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 200
    assert rig.slept == pytest.approx([5.0], abs=1.0)


def test_retry_after_naive_http_date_is_treated_as_utc() -> None:
    """`_http_date` documents that it normalises to UTC — an HTTP-date with no zone info is
    the case that promise exists for, not merely a parse detail."""
    naive = (datetime.now(UTC) + timedelta(seconds=5)).strftime("%a, %d %b %Y %H:%M:%S")
    handler = _Recorder((503, {"Retry-After": naive}), 200)
    rig = _rig(handler)
    with rig.client as client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 200
    assert rig.slept == pytest.approx([5.0], abs=1.0)


def test_an_unparsable_retry_after_falls_back_to_backoff() -> None:
    """A `Retry-After` that is neither delta-seconds nor an HTTP-date must not crash the
    retry loop — it is treated as though the header were absent."""
    handler = _Recorder((503, {"Retry-After": "whenever"}), 200)
    rig = _rig(handler, base_delay=0.5)
    with rig.client as client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 200
    assert rig.slept == pytest.approx([0.5])


@pytest.mark.asyncio
async def test_the_async_transport_also_stops_rather_than_sleeping_beyond_the_cap() -> None:
    """The async twin of the delta-seconds cap test: obeying an hour-long `Retry-After` is
    indistinguishable from a hang there too."""
    handler = _Recorder((503, {"Retry-After": "3600"}), 200)
    async with _async_client(handler) as client:
        response = await client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 503
    assert handler.attempts == 1


# ── construction guards ──────────────────────────────────────────────────────────────────


def test_zero_attempts_is_rejected() -> None:
    """The attempt budget is a promise the loop makes to itself: at least one send always
    happens. Zero would silently short-circuit every replay-safe request without ever
    asking the network."""
    with pytest.raises(ValueError, match="attempts must be >= 1, got 0"):
        RetryingTransport(httpx.MockTransport(lambda _request: httpx.Response(200)), attempts=0)


def test_negative_attempts_is_rejected() -> None:
    """The async twin's guard is the same shared `_RetryPlan` — a negative budget is just as
    nonsensical as zero."""
    with pytest.raises(ValueError, match="attempts must be >= 1, got -1"):
        RetryingAsyncTransport(
            httpx.MockTransport(lambda _request: httpx.Response(200)), attempts=-1
        )


# ── a body that dies mid-read ─────────────────────────────────────────────────────────────


class _FailingBodyStream(httpx.SyncByteStream):
    """A response whose headers arrived but whose BODY died mid-stream (OME-1107 review).

    `stream=` is the important part: `Response(content=...)` reads eagerly inside
    `__init__`, which would raise in the handler. The failure must happen only when the
    retry loop calls `read()` on the already-returned response — the exact case the loop
    used to let escape.
    """

    def __init__(self) -> None:
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        raise httpx.ReadError("connection dropped mid-body")

    def close(self) -> None:
        self.closed = True


class _AsyncFailingBodyStream(httpx.AsyncByteStream):
    """The async twin; same contract — headers arrived, the body did not."""

    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self) -> AsyncIterator[bytes]:
        raise httpx.ReadError("connection dropped mid-body")

    async def aclose(self) -> None:
        self.closed = True


def _read_failure_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[httpx.Client, list[float]]:
    """A sync client whose transport will retry — mirror of `_rig`, but its handler may
    return stream-backed responses, which `_Recorder` cannot express."""
    slept: list[float] = []
    transport = RetryingTransport(
        httpx.MockTransport(handler),
        attempts=3,
        base_delay=0.25,
        max_retry_after=30.0,
        sleep=slept.append,
        jitter=lambda: 0.0,
    )
    return httpx.Client(transport=transport, base_url="https://engine.test"), slept


def _async_read_failure_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    """The async twin of `_read_failure_client`."""
    transport = RetryingAsyncTransport(
        httpx.MockTransport(handler),
        attempts=3,
        base_delay=0.25,
        max_retry_after=30.0,
        sleep=_no_sleep,
        jitter=lambda: 0.0,
    )
    return httpx.AsyncClient(transport=transport, base_url="https://engine.test")


def test_a_body_read_failure_is_retried_like_any_transport_failure() -> None:
    """The reviewer's finding on #835: a retryable 503 whose BODY raises `httpx.ReadError`
    used to escape the loop — one attempt, no retry, no release. It is the same transient
    failure as a dropped send, so it gets a fresh attempt and the dead response is
    released."""
    dead = _FailingBodyStream()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, stream=dead)
        return httpx.Response(200, text="ok")

    client, _slept = _read_failure_client(handler)
    with client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 200
    assert attempts == 2
    assert dead.closed, "the dead response must be released before re-sending"


@pytest.mark.asyncio
async def test_the_async_transport_retries_a_body_read_failure() -> None:
    """The async twin of the reviewer's finding — it escaped both transports."""
    dead = _AsyncFailingBodyStream()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, stream=dead)
        return httpx.Response(200, text="ok")

    async with _async_read_failure_client(handler) as client:
        response = await client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 200
    assert attempts == 2
    assert dead.closed, "the dead response must be released before re-sending"


def test_a_body_read_failure_uses_backoff_not_the_retry_after_that_never_arrived() -> None:
    """A `Retry-After` rides on the response that died: it was delivered on headers whose
    body never did, and a connection-level drop is backoff territory, not the server's
    schedule. The retry is paced exactly like any other transport failure."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            dead = _FailingBodyStream()
            return httpx.Response(503, headers={"Retry-After": "2"}, stream=dead)
        return httpx.Response(200, text="ok")

    client, slept = _read_failure_client(handler)
    with client:
        response = client.post("/token", extensions={_REPLAY_SAFE: True})
    assert response.status_code == 200
    assert attempts == 2
    assert slept == pytest.approx([0.25]), "backoff(1), not the unread Retry-After of 2s"
