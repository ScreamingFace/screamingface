"""Admission retries respect caller budgets and transport phase limits."""

from types import SimpleNamespace

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world import connector as c
from screamingface_engine.world.config import WorldConfigError
from url4.core.errors import ResolutionError


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["queue", "transport"])
async def test_retry_rechecks_full_budget_after_backoff(monkeypatch, failure_kind):
    clock = [100.0]
    monkeypatch.setattr(c, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(c, "_queue_retry_delay", lambda *_: 0.5)
    monkeypatch.setattr(c, "_transport_backoff", lambda *_: 0.5)

    async def delayed_wakeup(attempt, delay):
        clock[0] += 3.0

    monkeypatch.setattr(c, "_wait_to_retry", delayed_wakeup)
    calls = []

    def handler(request):
        calls.append(request)
        if failure_kind == "transport":
            raise httpx.ReadError("lost reply")
        return httpx.Response(503, json={"detail": {"code": "provider_queue_timeout"}})

    headers = {"x-aigw-execution-timeout-s": "0.4", "x-aigw-queue-timeout-s": "0.6"}
    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as client:
        with request_scope(RequestScope(origin="run", deadline=108.0)):
            if failure_kind == "transport":
                with pytest.raises(ResolutionError) as error:
                    await c._post_completion(client, headers=headers, body={})
                assert error.value.code == "aigateway_deadline_exceeded"
            else:
                response, uncertain = await c._post_completion(client, headers=headers, body={})
                assert response.status_code == 503
                assert not uncertain
    assert len(calls) == 1, "A retry started with 5 seconds left, below its 6-second full budget"


@pytest.mark.asyncio
async def test_declared_budgets_preserve_short_transport_phase_limits():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    timeout = httpx.Timeout(connect=1, pool=0.1, write=2, read=60)
    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler), timeout=timeout
    ) as client:
        await c._post_completion(
            client,
            headers={"x-aigw-execution-timeout-s": "600", "x-aigw-queue-timeout-s": "600"},
            body={},
        )
    assert calls[0].extensions["timeout"] == {"connect": 1, "pool": 0.1, "write": 2, "read": 1205}


@pytest.mark.parametrize("field", ["timeout_s", "queue_timeout_s"])
def test_programmatic_budget_rejects_boolean(field):
    with pytest.raises(WorldConfigError):
        if field == "timeout_s":
            c.AigatewayConfig(timeout_s=True)
        else:
            c.AigatewayConfig(queue_timeout_s=True)
