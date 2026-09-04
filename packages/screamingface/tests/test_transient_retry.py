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

from collections.abc import Callable
from dataclasses import dataclass

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
