import asyncio
import json

import httpx
import pytest

from analytics_service.adapters.posthog import PostHogDelivery
from analytics_service.contract import parse_batch
from analytics_service.ports import DeliveryUnavailable, UpstreamRejected


async def test_mapping_and_identical_retry(envelope):
    bodies = []

    async def handler(request):
        bodies.append(request.content)
        return httpx.Response(503 if len(bodies) == 1 else 200, json={"status": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PostHogDelivery(client, "https://posthog.example", "test-token")
        await adapter.deliver(parse_batch(envelope))
    assert len(bodies) == 2 and bodies[0] == bodies[1]
    payload = json.loads(bodies[0])
    event = payload["batch"][0]
    original = envelope["events"][0]
    assert payload["api_key"] == "test-token"
    assert event["uuid"] == original["event_id"]
    assert event["timestamp"] == original["timestamp"]
    assert event["properties"]["distinct_id"] == "sf:installation:" + original["persistent_id"]
    assert event["properties"]["$process_person_profile"] is False
    assert event["properties"]["$geoip_disable"] is True
    assert "sent_at" not in payload and "$set" not in event["properties"]


@pytest.mark.parametrize(
    "status,body,error,attempts",
    [
        (400, {"secret": "private"}, UpstreamRejected, 1),
        (302, {}, UpstreamRejected, 1),
        (429, {}, DeliveryUnavailable, 2),
        (503, {}, DeliveryUnavailable, 2),
        (200, {"status": 0}, DeliveryUnavailable, 2),
        (200, {"status": 1, "errors": ["partial"]}, DeliveryUnavailable, 2),
    ],
)
async def test_status_semantics(envelope, status, body, error, attempts):
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(error):
            await PostHogDelivery(client, "https://posthog.example", "token").deliver(
                parse_batch(envelope)
            )
    assert len(requests) == attempts


async def test_total_deadline_and_cancellation(envelope):
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(10)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PostHogDelivery(client, "https://posthog.example", "token", budget=0.02)
        start = asyncio.get_running_loop().time()
        with pytest.raises(DeliveryUnavailable):
            await adapter.deliver(parse_batch(envelope))
        assert asyncio.get_running_loop().time() - start < 0.5
        task = asyncio.create_task(adapter.deliver(parse_batch(envelope)))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(calls) <= 2


@pytest.mark.parametrize("response", ["malformed", "large", "transport", "retry_after"])
async def test_ambiguous_and_bounded_responses(envelope, response):
    calls = []

    async def handler(request):
        calls.append(request)
        if response == "transport":
            raise httpx.ReadError("sensitive upstream detail")
        if response == "retry_after":
            return httpx.Response(429, headers={"Retry-After": "1000"})
        return httpx.Response(200, content=b"x" * (5000 if response == "large" else 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DeliveryUnavailable):
            await PostHogDelivery(client, "https://posthog.example", "token").deliver(
                parse_batch(envelope)
            )
    assert len(calls) <= 2


def test_retry_dates_and_session_mapping(envelope):
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    from analytics_service.adapters.posthog import accepted, map_event, retry_delay

    assert 0.05 <= retry_delay(None) <= 0.15
    assert 0.05 <= retry_delay("invalid") <= 0.15
    assert retry_delay("2") == 2
    assert retry_delay(format_datetime(datetime.now(UTC) + timedelta(seconds=10))) > 8
    assert not accepted(b"true") and not accepted(b'{"status":true}')
    event = envelope["events"][0]
    event["id_scope"] = "session"
    del event["persistent_id"]
    batch = parse_batch(envelope)
    mapped = map_event(batch.events[0], batch)
    assert isinstance(mapped["properties"], dict)
    assert mapped["properties"]["distinct_id"] == "sf:session:" + event["session_id"]
