"""Engine half of OME-886. Fake Gateway responses only; no paid calls."""

import asyncio
import time

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world import connector as c
from screamingface_engine.world.config import WorldConfigError
from url4.core.errors import ResolutionError


def busy(retry_after="1"):
    return httpx.Response(
        503,
        headers={"Retry-After": retry_after},
        json={
            "detail": {
                "code": "provider_queue_timeout",
                "message": "Timed out waiting for capacity.",
            }
        },
    )


def test_default_and_override_budgets():
    default = c.AigatewayConfig(timeout_s=600)
    assert default.admission_timeout_s == 600
    assert default.transport_timeout_s == 1205
    override = c.AigatewayConfig(timeout_s=600, queue_timeout_s=30)
    assert override.transport_timeout_s == 635


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_budget_rejected(value):
    with pytest.raises(WorldConfigError):
        c.AigatewayConfig(queue_timeout_s=value)


@pytest.mark.parametrize(
    "value,expected",
    [("3600", 8), ("0", 0.5), ("2", 2), ("nan", 0.75), ("-1", 0.75), ("bad", 0.75)],
)
def test_retry_after_is_bounded(value, expected, monkeypatch):
    monkeypatch.setattr(c, "_transport_backoff", lambda _: 0.75)
    assert c._queue_retry_delay(busy(value), 0) == expected


@pytest.mark.asyncio
async def test_queue_retries_share_existing_attempt_limit(monkeypatch):
    calls = []
    monkeypatch.setattr(c, "_queue_retry_delay", lambda *_: 0)

    def handler(request):
        calls.append(request)
        return busy()

    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(handler)
    ) as client:
        response, retried = await c._post_completion(client, headers={}, body={})
    assert not retried  # explicit admission refusals cannot hide billed work
    assert len(calls) == 2
    with pytest.raises(ResolutionError) as error:
        c._raise_for_status(response)
    assert error.value.code == "provider_queue_timeout"
    assert not error.value.permanent


@pytest.mark.asyncio
async def test_execution_timeout_is_not_retried_by_queue_policy():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(504, json={"detail": {"code": "provider_execution_timeout"}})

    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(handler)
    ) as client:
        response, retried = await c._post_completion(client, headers={}, body={})
    assert not retried
    assert len(calls) == 1
    with pytest.raises(ResolutionError) as error:
        c._raise_for_status(response)
    assert error.value.code == "provider_execution_timeout"


@pytest.mark.asyncio
async def test_declared_budgets_extend_transport_and_preserve_caller_cap():
    calls = []

    def handler(request):
        calls.append(request)
        return busy()

    headers = {"x-aigw-execution-timeout-s": "600", "x-aigw-queue-timeout-s": "600"}
    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(handler)
    ) as client:
        with request_scope(RequestScope(origin="run", deadline=time.monotonic() + 10)):
            response, retried = await c._post_completion(client, headers=headers, body={})
    assert response.status_code == 503
    assert not retried  # no room for a full retry
    assert len(calls) == 1
    assert 0 < calls[0].extensions["timeout"]["read"] <= 10
    assert 0 < float(calls[0].headers["x-aigw-remaining-timeout-s"]) <= 10


@pytest.mark.asyncio
async def test_outer_timeout_accommodates_both_declared_budgets():
    seen = []

    def handler(request):
        seen.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(handler)
    ) as client:
        await c._post_completion(
            client,
            headers={"x-aigw-execution-timeout-s": "600", "x-aigw-queue-timeout-s": "30"},
            body={},
        )
    assert seen == [635]


@pytest.mark.asyncio
async def test_cancellation_during_queue_retry_does_not_start_another_attempt(monkeypatch):
    attempts = 0
    waiting = asyncio.Event()

    def handler(request):
        nonlocal attempts
        attempts += 1
        waiting.set()
        return busy("8")

    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(handler)
    ) as client:
        task = asyncio.create_task(c._post_completion(client, headers={}, body={}))
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_failure", [False, True])
async def test_queue_retry_preserves_known_spend_but_transport_loss_stays_unknown(
    transport_failure, monkeypatch
):
    attempts = 0
    monkeypatch.setattr(c, "_transport_backoff", lambda _: 0)
    monkeypatch.setattr(c, "_queue_retry_delay", lambda *_: 0)

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if transport_failure:
                raise httpx.ReadError("lost reply")
            return busy()
        return httpx.Response(200, json={"choices": []})

    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(handler)
    ) as client:
        response, uncertain_spend = await c._post_completion(client, headers={}, body={})
    assert response.status_code == 200
    assert attempts == 2
    assert uncertain_spend is transport_failure
