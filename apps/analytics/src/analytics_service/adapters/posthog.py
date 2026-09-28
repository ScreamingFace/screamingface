"""Public batch transport with a single end-to-end deadline."""

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from analytics_service.contract import Batch, Event
from analytics_service.ports import DeliveryUnavailable, UpstreamRejected


def map_event(event: Event, batch: Batch) -> dict[str, object]:
    properties = event.model_dump(exclude_none=True)
    properties.update(
        {
            "distinct_id": f"sf:{event.id_scope}:{event.persistent_id or event.session_id}",
            "schema_version": batch.schema_version,
            "consent_version": batch.consent_version,
            "$process_person_profile": False,
            "$geoip_disable": True,
        }
    )
    return {
        "uuid": event.event_id,
        "event": event.event,
        "timestamp": event.timestamp,
        "properties": properties,
    }


def retry_delay(value: str | None) -> float:
    delay = random.uniform(0.05, 0.15)
    if value is not None:
        try:
            delay = max(delay, float(value))
        except ValueError:
            try:
                delay = max(
                    delay, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
                )
            except (ValueError, TypeError, OverflowError):
                pass
    return delay


# The acknowledgements /batch/ is known to answer with. PostHog Cloud returns
# {"status":"Ok"}, verified live against us.i.posthog.com on 2026-09-09; the
# integer form is the older acknowledgement and stays accepted so a self-hosted
# or pinned deployment does not regress. Neither shape is documented, so this
# tuple is the whole contract and any addition belongs here.
ACKNOWLEDGEMENTS = ({"status": "Ok"}, {"status": 1})


def accepted(body: bytes) -> bool:
    # WHY: malformed/partial responses cannot acknowledge the whole batch.
    try:
        value = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return False
    if type(value) is not dict:
        return False
    # INVARIANT: exact match, so a response carrying extra keys is still
    # refused. The status type check is load-bearing on the integer form —
    # JSON true equals 1 in Python, so equality alone would accept
    # {"status": true}.
    return any(
        value == ack and type(value["status"]) is type(ack["status"]) for ack in ACKNOWLEDGEMENTS
    )


class PostHogDelivery:
    def __init__(
        self,
        client: httpx.AsyncClient,
        host: str,
        token: str,
        *,
        budget: float = 1.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.client, self.url, self.token = client, host.rstrip("/") + "/batch/", token
        self.budget, self.sleep = budget, sleep

    async def deliver(self, batch: Batch) -> None:
        # INVARIANT: serialize once; retry identity and timestamps stay byte-identical.
        body = json.dumps(
            {"api_key": self.token, "batch": [map_event(event, batch) for event in batch.events]}
        ).encode()
        try:
            async with asyncio.timeout(self.budget):
                await self.attempts(body)
        except TimeoutError:
            raise DeliveryUnavailable() from None

    async def attempts(self, body: bytes) -> None:
        for attempt in range(2):
            try:
                retry_after = await self.send(body)
            except (httpx.TransportError, httpx.DecodingError):
                # WHY: corrupt response encoding leaves upstream acceptance ambiguous.
                retry_after = "0"
            if retry_after is None:
                return
            if attempt == 0:
                delay = retry_delay(retry_after)
                if delay >= self.budget:
                    raise DeliveryUnavailable()
                await self.sleep(delay)
        raise DeliveryUnavailable()

    async def send(self, body: bytes) -> str | None:
        async with self.client.stream(
            "POST",
            self.url,
            content=body,
            headers={"Content-Type": "application/json"},
            follow_redirects=False,
            timeout=self.budget,
        ) as response:
            if response.status_code == 429 or response.status_code >= 500:
                return response.headers.get("Retry-After", "0")
            if not 200 <= response.status_code < 300:
                raise UpstreamRejected()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 4096:
                    raise DeliveryUnavailable()
            return None if accepted(bytes(content)) else "0"
