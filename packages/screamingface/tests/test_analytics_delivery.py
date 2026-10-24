import asyncio

import httpx
import pytest

from screamingface._analytics.delivery import send_batch


@pytest.mark.asyncio
async def test_retries_keep_ids_and_never_send_product_auth():
    requests = []

    def handler(request):
        requests.append(request)
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        return httpx.Response(503 if len(requests) == 1 else 202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await send_batch(
            client, "https://example.test/v1/events", [{"event_id": "same"}], lambda: True
        )
    assert len(requests) == 2
    assert requests[0].content == requests[1].content


@pytest.mark.asyncio
async def test_decline_between_attempts_prevents_retry():
    allowed = True

    def handler(request):
        nonlocal allowed
        allowed = False
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await send_batch(client, "https://example.test/v1/events", [], lambda: allowed)


@pytest.mark.asyncio
async def test_total_deadline_bounds_hung_transport():
    async def handler(request):
        await asyncio.sleep(10)
        return httpx.Response(202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                send_batch(client, "https://example.test", [], lambda: True), timeout=0.02
            )


def test_background_delivery_does_not_wait_for_transport(monkeypatch):
    import threading
    import time

    from screamingface._analytics.delivery import BackgroundSink

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = httpx.AsyncClient

    async def handler(request):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.001)
        finished.set()
        return httpx.Response(202)

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    sink = BackgroundSink("https://example.test/v1/events", lambda event: True)
    started = time.monotonic()
    sink.emit({"event_id": "example"})
    assert time.monotonic() - started < 0.2
    try:
        assert entered.wait(1)
    finally:
        release.set()
    assert finished.wait(1)


def test_queue_is_bounded_and_clear_discards_pending_events(monkeypatch):
    from screamingface._analytics.delivery import BackgroundSink

    monkeypatch.setattr("threading.Thread.start", lambda self: None)
    sink = BackgroundSink("https://example.test", lambda event: True)
    sink.emit({"event_id": "x" * 4097})
    assert sink._queue.qsize() == 0
    for i in range(150):
        sink.emit({"event_id": str(i)})
    assert sink._queue.qsize() == 100
    sink.clear()
    assert sink._queue.empty()


@pytest.mark.asyncio
async def test_transport_failure_is_bounded_and_permanent_errors_are_not_retried():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("sensitive content must never be logged")
        return httpx.Response(400)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await send_batch(client, "https://example.test", [], lambda: True)
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,attempts", [(202, 1), (400, 1), (429, 2), (500, 1), (502, 1), (503, 2)]
)
async def test_only_retryable_gateway_statuses_are_retried(status, attempts):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await send_batch(client, "https://example.test/v1/events", [], lambda: True)
    assert len(requests) == attempts
