"""§2.2b (04-review-fixes.md): a budget that runs out upstream has its own code.

FEATURE (unit 3, prd/03): the R7 signal ("is the 30 s budget too short?"). With the FX-1
deadline, a slow model ends as a 502 before url4's 504. The connector names that case
`aigateway_deadline_exceeded` (transient, so still 502) so the tier can count it. With no
deadline (the ensemble path) every code is the one it was before.

Stubbed aigateway throughout (`httpx.MockTransport`): no real external API is called.
"""

from __future__ import annotations

import time

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world import connector as connector_module
from url4.core.errors import ResolutionError

pytestmark = pytest.mark.asyncio

_DEADLINE_EXCEEDED = "aigateway_deadline_exceeded"


class _Gateway:
    """Raises ``error`` for the first ``fail_times`` attempts, then answers 200."""

    def __init__(self, fail_times: int, error: type[httpx.TransportError]) -> None:
        self._fail_times = fail_times
        self._error = error
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error("synthetic transport failure", request=request)
        return httpx.Response(200, json={"ok": True})


def _client(gateway: _Gateway, timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handler),
        base_url="http://aigateway.test",
        timeout=timeout,
    )


async def _post(client: httpx.AsyncClient, deadline: float | None) -> tuple[httpx.Response, bool]:
    with request_scope(RequestScope(deadline=deadline)):
        return await connector_module._post_completion(client, headers={}, body={})


async def test_an_attempt_that_times_out_at_the_deadline_bound_is_deadline_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The attempt's timeout was the time left (1 s < 28 s), so the budget is what ran out."""
    monkeypatch.setattr(connector_module, "_transport_backoff", lambda _: 0.0)
    gateway = _Gateway(fail_times=1, error=httpx.ReadTimeout)
    async with _client(gateway, timeout=28.0) as client:
        with pytest.raises(ResolutionError) as caught:
            await _post(client, time.monotonic() + 1.0)
    assert caught.value.code == _DEADLINE_EXCEEDED
    assert caught.value.permanent is False
    assert gateway.calls == 1


async def test_a_retry_skipped_because_the_deadline_is_near_is_deadline_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connector_module, "_transport_backoff", lambda _: 0.5)
    gateway = _Gateway(fail_times=1, error=httpx.ConnectError)
    async with _client(gateway, timeout=1.0) as client:
        with pytest.raises(ResolutionError) as caught:
            await _post(client, time.monotonic() + 1.2)
    assert caught.value.code == _DEADLINE_EXCEEDED
    assert caught.value.permanent is False
    assert gateway.calls == 1


async def test_a_connect_error_that_leaves_room_retries_and_keeps_the_transport_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connector_module, "_transport_backoff", lambda _: 0.0)
    gateway = _Gateway(fail_times=2, error=httpx.ConnectError)
    async with _client(gateway, timeout=0.2) as client:
        with pytest.raises(ResolutionError) as caught:
            await _post(client, time.monotonic() + 5.0)
    assert caught.value.code == "aigateway_transport_error"
    assert gateway.calls == 2


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
async def test_no_deadline_keeps_the_transport_code(
    monkeypatch: pytest.MonkeyPatch, error: type[httpx.TransportError]
) -> None:
    """The ensemble path binds no deadline: its codes are exactly the ones on `main`."""
    monkeypatch.setattr(connector_module, "_transport_backoff", lambda _: 0.0)
    gateway = _Gateway(fail_times=2, error=error)
    async with _client(gateway, timeout=0.2) as client:
        with pytest.raises(ResolutionError) as caught:
            await _post(client, None)
    assert caught.value.code == "aigateway_transport_error"
    assert gateway.calls == 2
