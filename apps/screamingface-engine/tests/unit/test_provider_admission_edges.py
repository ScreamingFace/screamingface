"""Admission retries preserve caller deadlines and spend uncertainty (OME-1163)."""

import asyncio
import itertools
import time

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world import connector as c
from url4.core.errors import ResolutionError

pytestmark = pytest.mark.asyncio


def reply(kind):
    if kind == "transport":
        raise httpx.ReadError("lost response")
    if kind == "queue":
        return httpx.Response(
            503, headers={"Retry-After": "0"}, json={"detail": {"code": "provider_queue_timeout"}}
        )
    return httpx.Response(200, json={"ok": True})


@pytest.mark.parametrize(
    "first,second", list(itertools.product(["transport", "queue", "ok"], repeat=2))
)
async def test_shared_attempt_limit_and_unknown_spend_matrix(monkeypatch, first, second):
    calls = []
    monkeypatch.setattr(c, "_transport_backoff", lambda _: 0)
    monkeypatch.setattr(c, "_queue_retry_delay", lambda *_: 0)

    async def handler(request):
        calls.append(request)
        return reply([first, second][len(calls) - 1])

    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as client:
        if second == "transport" and first != "ok":
            with pytest.raises(ResolutionError) as caught:
                await c._post_completion(client, headers={}, body={})
            assert caught.value.code == "aigateway_transport_error"
        else:
            response, unknown_spend = await c._post_completion(client, headers={}, body={})
            assert unknown_spend == (first == "transport")
            assert response.status_code == (503 if first != "ok" and second == "queue" else 200)
    assert len(calls) == (1 if first == "ok" else 2)


async def test_deadline_enforced_even_if_transport_ignores_httpx_timeout():
    calls = []

    async def handler(request) -> httpx.Response:
        calls.append(request)
        await asyncio.Event().wait()
        raise AssertionError("The caller deadline must cancel this transport")

    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as client:
        with request_scope(RequestScope(origin="run", deadline=time.monotonic() + 0.03)):
            with pytest.raises(ResolutionError) as caught:
                await c._post_completion(
                    client,
                    headers={"x-aigw-execution-timeout-s": "600", "x-aigw-queue-timeout-s": "600"},
                    body={},
                )
    assert caught.value.code == "aigateway_deadline_exceeded"
    assert len(calls) == 1


async def test_expired_caller_never_starts_transport():
    calls = []

    async def handler(request):
        calls.append(request)
        return reply("ok")

    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as client:
        with request_scope(RequestScope(origin="run", deadline=time.monotonic() - 1)):
            with pytest.raises(ResolutionError) as caught:
                await c._post_completion(client, headers={}, body={})
    assert caught.value.code == "aigateway_deadline_exceeded"
    assert calls == []


async def test_remaining_budget_is_recomputed_after_queue_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(c, "_queue_retry_delay", lambda *_: 0.02)

    async def handler(request):
        calls.append(request)
        return reply("queue" if len(calls) == 1 else "ok")

    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler), timeout=0.1
    ) as client:
        with request_scope(RequestScope(origin="run", deadline=time.monotonic() + 1)):
            await c._post_completion(client, headers={}, body={})
    budgets = [float(r.headers["x-aigw-remaining-timeout-s"]) for r in calls]
    assert len(budgets) == 2
    assert budgets[0] - budgets[1] >= 0.015


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "string",
        {},
        {"detail": []},
        {"detail": "provider_queue_timeout"},
        {"detail": {"code": "other"}},
    ],
)
async def test_unclassified_503_does_not_trigger_queue_retry(payload):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(503, json=payload)

    async with httpx.AsyncClient(
        base_url="http://fake", transport=httpx.MockTransport(handler)
    ) as client:
        result, unknown = await c._post_completion(client, headers={}, body={})
    assert len(calls) == 1
    assert result.status_code == 503
    assert not unknown
