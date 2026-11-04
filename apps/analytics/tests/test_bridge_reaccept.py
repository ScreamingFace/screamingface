"""Old automatic responses must not replace or delete a reaccepted identity."""

import asyncio

import httpx
import pytest
from test_api import Recorder
from test_bridge import ORIGIN, accept, browser, config
from test_bridge_enrollment_races import HoldResponse

from analytics_service.api import create_app
from analytics_service.bridge import IDENTITY


@pytest.mark.parametrize("path", ["/bridge/id", "/bridge/consent/enroll"])
async def test_late_response_after_reaccept_preserves_new_identity(path, envelope):
    recorder = Recorder()
    held = HoldResponse(create_app(config(), recorder))
    async with browser(held) as first:
        old = await accept(first) if path == "/bridge/id" else None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_app(config(), recorder)),
            base_url=ORIGIN,
            headers={"Origin": ORIGIN},
            cookies=first.cookies.jar,
        ) as second:
            held.path = path
            body = {} if path == "/bridge/id" else {"consent_version": "1"}
            pending = asyncio.create_task(first.post(path, json=body))
            try:
                await asyncio.wait_for(held.entered.wait(), 2)
                decline = await second.post(
                    "/bridge/consent", json={"choice": "declined", "consent_version": "1"}
                )
                assert decline.status_code == 200
                assert second.cookies.get(IDENTITY) is None
                new = await accept(second)
                assert new != old
                assert second.cookies.get(IDENTITY) == new
            finally:
                held.release.set()
                late = await pending
            assert late.status_code == 200
            assert second.cookies.get(IDENTITY) == new
            assert (await second.get("/bridge/consent/state")).json()["choice"] == "accepted"
            event = envelope["events"][0]
            event.update(origin="colab", id_scope="browser", persistent_id=new)
            assert (await second.post("/bridge/id/events", json=envelope)).status_code == 202
            if old is not None:
                event["persistent_id"] = old
                assert (await second.post("/bridge/id/events", json=envelope)).status_code == 422
            assert len(recorder.batches) == 1
            assert recorder.batches[0].events[0].persistent_id == new


async def test_existing_id_read_does_not_extend_identity_expiry():
    async with browser(create_app(config(), Recorder())) as client:
        identifier = await accept(client)
        before = next(cookie.expires for cookie in client.cookies.jar if cookie.name == IDENTITY)
        response = await client.post("/bridge/id", json={})
        assert response.json()["persistent_id"] == identifier
        names = [header.split("=", 1)[0] for header in response.headers.get_list("set-cookie")]
        assert IDENTITY not in names
        after = next(cookie.expires for cookie in client.cookies.jar if cookie.name == IDENTITY)
        assert after == before
