"""Offline admission contract: saturation, cancellation and phase budgets."""

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException, Request

from aigateway.core.admission import dispatch_with_budgets
from aigateway.core.concurrency import provider_slot
from aigateway.routes.chat_dispatch import _dispatch_with_backpressure


def request(*, execution=1.0, queue=None, headers=None, app=None):
    settings = SimpleNamespace(
        provider_execution_timeout_s=execution,
        provider_queue_timeout_s=queue,
        provider_max_concurrency=1,
        provider_max_concurrency_overrides={},
    )
    app = app or SimpleNamespace(state=SimpleNamespace(settings=settings))
    disconnect = asyncio.Event()

    async def receive():
        await disconnect.wait()
        return {"type": "http.disconnect"}

    req = Request(
        {
            "type": "http",
            "app": app,
            "headers": [(k.encode(), str(v).encode()) for k, v in (headers or {}).items()],
        },
        receive,
    )
    return req, disconnect


async def answer():
    return "answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("queue", [None, 0.01])
async def test_queue_expiry_never_dispatches_and_preserves_slot(caplog, queue):
    req, _ = request(execution=0.01, queue=queue)
    called = False

    async def provider():
        nonlocal called
        called = True

    with caplog.at_level("INFO"):
        async with provider_slot(req.app, "openrouter", 1):
            with pytest.raises(HTTPException) as error:
                await dispatch_with_budgets(req, "openrouter", provider)
            assert error.value.status_code == 503
            assert cast(dict[str, str], error.value.detail)["code"] == "provider_queue_timeout"
            assert error.value.headers == {"Retry-After": "1"}
            assert not called
        assert await dispatch_with_budgets(req, "openrouter", answer) == "answer"
    record = next(
        r for r in caplog.records if getattr(r, "outcome", None) == "provider_queue_timeout"
    )
    assert record.queue_wait_ms > 0
    assert record.provider_execution_ms == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect_client", [False, True])
async def test_cancelled_waiter_never_dispatches(disconnect_client):
    req, disconnect = request()
    called = False

    async def provider():
        nonlocal called
        called = True

    async with provider_slot(req.app, "openrouter", 1):
        task = asyncio.create_task(dispatch_with_budgets(req, "openrouter", provider))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        if disconnect_client:
            disconnect.set()
        else:
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not called
    assert await dispatch_with_budgets(req, "openrouter", answer) == "answer"


@pytest.mark.asyncio
async def test_execution_timeout_is_distinct_and_releases_slot(caplog):
    req, _ = request(execution=0.01)

    async def blocked():
        await asyncio.Event().wait()

    with caplog.at_level("INFO"), pytest.raises(HTTPException) as error:
        await dispatch_with_budgets(req, "openrouter", blocked)
    assert cast(dict[str, str], error.value.detail)["code"] == "provider_execution_timeout"
    assert error.value.status_code == 504
    assert await dispatch_with_budgets(req, "openrouter", answer) == "answer"
    record = next(
        r for r in caplog.records if getattr(r, "outcome", None) == "provider_execution_timeout"
    )
    assert record.provider_execution_ms > 0


@pytest.mark.asyncio
async def test_execution_budget_starts_after_admission(caplog):
    req, _ = request(execution=0.02, queue=1)
    with caplog.at_level("INFO"):
        async with provider_slot(req.app, "openrouter", 1):
            task = asyncio.create_task(dispatch_with_budgets(req, "openrouter", answer))
            await asyncio.sleep(0.04)
            assert not task.done()
        assert await task == "answer"
    record = next(r for r in caplog.records if getattr(r, "outcome", None) == "success")
    assert record.queue_wait_ms >= 20
    assert record.provider_execution_ms < record.queue_wait_ms


@pytest.mark.asyncio
async def test_explicit_caller_budget_caps_queue():
    req, _ = request(headers={"x-aigw-remaining-timeout-s": 0.01})
    async with provider_slot(req.app, "openrouter", 1):
        with pytest.raises(HTTPException) as error:
            await dispatch_with_budgets(req, "openrouter", answer)
    assert cast(dict[str, str], error.value.detail)["code"] == "caller_deadline_exceeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [4, 50])
async def test_32_calls_respect_override_and_log_effective_limit(caplog, limit):
    req, _ = request()
    req.app.state.settings.provider_max_concurrency_overrides = {"openrouter": limit}
    active = peak = 0
    full = asyncio.Event()
    release = asyncio.Event()

    async def provider():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == min(limit, 32):
            full.set()
        await release.wait()
        active -= 1
        return "answer"

    with caplog.at_level("INFO"):
        calls = [
            asyncio.create_task(
                dispatch_with_budgets(request(app=req.app)[0], "openrouter", provider)
            )
            for _ in range(32)
        ]
        await asyncio.wait_for(full.wait(), 1)
        assert peak == min(limit, 32)
        release.set()
        assert await asyncio.gather(*calls) == ["answer"] * 32
    records = [r for r in caplog.records if hasattr(r, "provider_concurrency_limit")]
    assert len(records) == 32
    assert all(r.provider_concurrency_limit == limit for r in records)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["nan", "inf", "0", "-1", "oops"])
async def test_invalid_budget_is_rejected(value):
    req, _ = request(headers={"x-aigw-queue-timeout-s": value})
    with pytest.raises(HTTPException) as error:
        await dispatch_with_budgets(req, "openrouter", answer)
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_caller_cannot_extend_operator_queue_limit():
    req, _ = request(queue=0.01, headers={"x-aigw-queue-timeout-s": 100})
    async with provider_slot(req.app, "openrouter", 1):
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(dispatch_with_budgets(req, "openrouter", answer), 1)
    assert cast(dict[str, str], error.value.detail)["code"] == "provider_queue_timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize("httpx_timeout", [False, True])
async def test_provider_timeout_is_safe_and_classified(caplog, httpx_timeout):
    import httpx
    from litellm.exceptions import Timeout

    from aigateway.config import Settings
    from aigateway.routes.chat_dispatch import _dispatch_with_backpressure

    req, _ = request()
    req.app.state.settings = Settings()

    async def timed_out(body):
        if httpx_timeout:
            raise httpx.ReadTimeout("secret prompt and credential")
        raise Timeout(message="secret prompt and credential", model="fake", llm_provider="fake")

    with caplog.at_level("INFO"), pytest.raises(HTTPException) as error:
        await _dispatch_with_backpressure(
            req, SimpleNamespace(chat_completion=timed_out), "openrouter", {}
        )
    assert cast(dict[str, str], error.value.detail)["code"] == "provider_execution_timeout"
    assert "secret" not in str(error.value.detail)
    assert "secret" not in caplog.text
    assert any(getattr(r, "outcome", None) == "provider_execution_timeout" for r in caplog.records)


@pytest.mark.asyncio
async def test_disconnection_during_execution_cancels_provider_and_releases_slot():
    req, disconnect = request()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def provider():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = asyncio.create_task(dispatch_with_budgets(req, "openrouter", provider))
    await entered.wait()
    disconnect.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    assert await dispatch_with_budgets(request(app=req.app)[0], "openrouter", answer) == "answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queue", "caller"])
async def test_expired_waiter_never_dispatches_when_slot_wakes_before_timeout_callback(phase):
    import time

    req, _ = request(
        queue=0.02 if phase == "queue" else 1,
        headers={"x-aigw-remaining-timeout-s": 0.02} if phase == "caller" else None,
    )
    dispatched = []

    async def provider():
        dispatched.append(True)
        return "answer"

    async with provider_slot(req.app, "openrouter", 1):
        task = asyncio.create_task(dispatch_with_budgets(req, "openrouter", provider))
        await asyncio.sleep(0.005)
        # WHY: synchronous work can delay timeout callbacks beyond their deadline.
        # Releasing capacity schedules the waiter before the overdue timer executes.
        time.sleep(0.05)
    result = (await asyncio.gather(task, return_exceptions=True))[0]
    assert not dispatched
    assert isinstance(result, HTTPException)
    expected = "provider_queue_timeout" if phase == "queue" else "caller_deadline_exceeded"
    assert cast(dict[str, str], result.detail)["code"] == expected
    # INVARIANT: refusing an already-acquired slot must not leak capacity.
    async with provider_slot(req.app, "openrouter", 1, timeout_s=0.1):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", ["disconnect", "task"])
@pytest.mark.parametrize("immediate_answer", [False, True])
async def test_cancelled_waiter_cannot_dispatch_when_capacity_returns(cancel, immediate_answer):
    req, disconnect = request()
    dispatched = []

    async def provider():
        dispatched.append(True)
        if not immediate_answer:
            await asyncio.Event().wait()
        return "answer"

    async with provider_slot(req.app, "openrouter", 1):
        task = asyncio.create_task(dispatch_with_budgets(req, "openrouter", provider))
        await asyncio.sleep(0.005)
        if cancel == "disconnect":
            disconnect.set()
        else:
            task.cancel()
        # INVARIANT: cancellation and capacity returning in the same loop turn
        # cannot allow even the first provider instruction to run.
    result = (await asyncio.gather(task, return_exceptions=True))[0]
    assert not dispatched
    assert isinstance(result, asyncio.CancelledError)
    async with provider_slot(req.app, "openrouter", 1, timeout_s=0.1):
        pass


@pytest.mark.asyncio
async def test_stalled_waiter_preserves_earlier_caller_deadline_classification():
    import time

    req, _ = request(queue=0.02, headers={"x-aigw-remaining-timeout-s": 0.01})
    async with provider_slot(req.app, "openrouter", 1):
        task = asyncio.create_task(dispatch_with_budgets(req, "openrouter", answer))
        await asyncio.sleep(0.005)
        time.sleep(0.05)
    with pytest.raises(HTTPException) as error:
        await task
    assert cast(dict[str, str], error.value.detail)["code"] == "caller_deadline_exceeded"


@pytest.mark.asyncio
async def test_execution_budget_includes_overload_backoff():
    from fastapi import HTTPException

    from aigateway.config import Settings
    from aigateway.routes.chat_dispatch import _dispatch_with_backpressure

    req, _ = request()
    req.app.state.settings = Settings(
        provider_max_concurrency=1,
        provider_execution_timeout_s=0.03,
        retry_backoff_base_seconds=1,
        retry_jitter_seconds=0,
    )
    count = 0

    async def provider(body):
        nonlocal count
        count += 1
        raise HTTPException(503, detail="fake overload")

    with pytest.raises(HTTPException) as error:
        await _dispatch_with_backpressure(
            req, SimpleNamespace(chat_completion=provider), "fake", {}
        )
    assert error.value.status_code == 504
    assert cast(dict[str, str], error.value.detail)["code"] == "provider_execution_timeout"
    assert count == 1
    async with provider_slot(req.app, "fake", 1, timeout_s=0.1):
        pass


@pytest.mark.asyncio
async def test_execution_header_cannot_extend_operator_limit():
    req, _ = request(execution=0.01, headers={"x-aigw-execution-timeout-s": 100})

    async def blocked():
        await asyncio.Event().wait()

    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(dispatch_with_budgets(req, "openrouter", blocked), 1)
    assert error.value.status_code == 504
    assert cast(dict[str, str], error.value.detail)["code"] == "provider_execution_timeout"
    assert await dispatch_with_budgets(req, "openrouter", answer) == "answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", ["disconnect", "shutdown", "both"])
async def test_http_dispatch_consumes_only_disconnect_cancellation(cancel):
    from aigateway.config import Settings

    req, disconnect = request()
    req.app.state.settings = Settings(provider_max_concurrency=1)
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    receive = req.receive

    async def receive_with_shutdown():
        message = await receive()
        # INVARIANT: a simultaneous shutdown cancellation must survive disconnect handling.
        task.cancel("shutdown")
        return message

    if cancel == "both":
        req._receive = receive_with_shutdown

    async def provider(body):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = asyncio.create_task(
        _dispatch_with_backpressure(req, SimpleNamespace(chat_completion=provider), "fake", {})
    )
    await asyncio.wait_for(entered.wait(), 1)
    if cancel == "shutdown":
        task.cancel("shutdown")
    else:
        disconnect.set()
    if cancel == "disconnect":
        with pytest.raises(HTTPException) as error:
            await task
        assert error.value.status_code == 499
        assert task.cancelling() == 0
    else:
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelling() == 1
    assert cancelled.is_set()
    async with provider_slot(req.app, "fake", 1, timeout_s=0.1):
        pass
