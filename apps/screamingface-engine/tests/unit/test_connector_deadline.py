"""FX-1 (04-review-fixes.md §2.1): the request deadline bounds the aigateway transport retry.

FEATURE (unit 3, prd/03): the sync surface's timeout ladder. The connector's transport retry is
the one place that can know whether there is time for one more attempt, so it reads the
deadline the sync producer binds in the request scope. With no deadline (the ensemble path) the
behaviour is the one it has always had.

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


class _Gateway:
    """Fails the first ``fail_times`` attempts with a ReadTimeout; records each attempt."""

    def __init__(self, fail_times: int) -> None:
        self._fail_times = fail_times
        self.read_timeouts: list[float | None] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.read_timeouts.append(request.extensions["timeout"]["read"])
        if len(self.read_timeouts) <= self._fail_times:
            raise httpx.ReadTimeout("synthetic read timeout", request=request)
        return httpx.Response(200, json={"ok": True})


def _client(gateway: _Gateway, timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handler),
        base_url="http://aigateway.test",
        timeout=timeout,
    )


async def test_no_deadline_keeps_the_client_timeout_and_the_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ensemble path binds no deadline: two attempts, each under the client's own timeout."""
    monkeypatch.setattr(connector_module, "_transport_backoff", lambda _: 0.0)
    gateway = _Gateway(fail_times=1)
    async with _client(gateway, timeout=28.0) as client:
        with request_scope(RequestScope()):
            _resp, retried = await connector_module._post_completion(client, headers={}, body={})
    assert retried is True
    assert gateway.read_timeouts == [28.0, 28.0]


async def test_each_attempt_timeout_is_capped_by_the_time_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connector_module, "_transport_backoff", lambda _: 0.0)
    gateway = _Gateway(fail_times=0)
    async with _client(gateway, timeout=28.0) as client:
        with request_scope(RequestScope(deadline=time.monotonic() + 1.0)):
            await connector_module._post_completion(client, headers={}, body={})
    [timeout] = gateway.read_timeouts
    assert timeout is not None and 0.0 < timeout <= 1.0


async def test_a_retry_that_cannot_fit_backoff_plus_one_attempt_is_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """deadline - now < delay + configured timeout → raise the transient error, do not sleep."""
    monkeypatch.setattr(connector_module, "_transport_backoff", lambda _: 0.5)
    gateway = _Gateway(fail_times=1)
    started = time.monotonic()
    async with _client(gateway, timeout=1.0) as client:
        with request_scope(RequestScope(deadline=time.monotonic() + 1.2)):
            with pytest.raises(ResolutionError) as caught:
                await connector_module._post_completion(client, headers={}, body={})
    assert caught.value.code == "aigateway_deadline_exceeded"
    assert caught.value.permanent is False
    assert len(gateway.read_timeouts) == 1
    assert time.monotonic() - started < 0.4, "the connector slept for a retry it never made"


async def test_a_retry_runs_when_the_deadline_leaves_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connector_module, "_transport_backoff", lambda _: 0.0)
    gateway = _Gateway(fail_times=1)
    async with _client(gateway, timeout=0.2) as client:
        with request_scope(RequestScope(deadline=time.monotonic() + 5.0)):
            _resp, retried = await connector_module._post_completion(client, headers={}, body={})
    assert retried is True
    assert len(gateway.read_timeouts) == 2


async def test_an_expired_deadline_makes_no_call() -> None:
    gateway = _Gateway(fail_times=0)
    async with _client(gateway, timeout=28.0) as client:
        with request_scope(RequestScope(deadline=time.monotonic() - 0.1)):
            with pytest.raises(ResolutionError) as caught:
                await connector_module._post_completion(client, headers={}, body={})
    assert caught.value.code == "aigateway_deadline_exceeded"
    assert caught.value.permanent is False
    assert gateway.read_timeouts == []
