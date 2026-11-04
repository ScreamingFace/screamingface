"""Responses from other frames/replicas cannot silently reverse a saved decline."""

import asyncio
from http.cookies import SimpleCookie

import httpx
import pytest
from test_api import Recorder
from test_bridge import ORIGIN, accept, browser, config

from analytics_service.api import create_app
from analytics_service.bridge import CONSENT, IDENTITY

OPTOUT = "__Secure-sf_bridge_optout"


class HoldResponse:
    def __init__(self, app):
        self.app = app
        self.path: str | None = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, scope, receive, send):
        async def delayed(message):
            if message["type"] == "http.response.start" and scope["path"] == self.path:
                self.entered.set()
                await asyncio.wait_for(self.release.wait(), 2)
            await send(message)

        await self.app(scope, receive, delayed)


@pytest.mark.parametrize("path", ["/bridge/consent/enroll", "/bridge/id"])
async def test_late_automatic_response_cannot_reverse_other_replica_decline(path, envelope):
    recorder = Recorder()
    held = HoldResponse(create_app(config(), recorder))
    async with browser(held) as first:
        if path == "/bridge/id":
            await accept(first)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_app(config(), recorder)),
            base_url=ORIGIN,
            headers={"Origin": ORIGIN},
            cookies=first.cookies.jar,
        ) as second:
            held.path = path
            body = {"consent_version": "1"} if path.endswith("enroll") else {}
            pending = asyncio.create_task(first.post(path, json=body))
            try:
                await asyncio.wait_for(held.entered.wait(), 2)
                decline = await second.post(
                    "/bridge/consent", json={"choice": "declined", "consent_version": "1"}
                )
                assert decline.status_code == 200
                assert (await second.get("/bridge/consent/state")).json()["choice"] == "declined"
            finally:
                held.release.set()
                late = await pending
            assert late.status_code == 200
            # WHY: apply the old response last, as two independent browser frames can.
            assert first.cookies.get(CONSENT) == "1.accepted"
            assert (await second.get("/bridge/consent/state")).json()["choice"] == "declined"
            assert (await second.post("/bridge/id", json={})).status_code == 403
            envelope["events"][0].update(
                origin="colab",
                id_scope="browser",
                persistent_id=first.cookies.get(IDENTITY) or envelope["events"][0]["persistent_id"],
            )
            response = await second.post("/bridge/id/events", json=envelope)
            assert response.status_code == 403
            assert recorder.batches == []
            enrollment = await second.post("/bridge/consent/enroll", json={"consent_version": "1"})
            assert enrollment.json()["choice"] == "declined"
            assert "set-cookie" not in enrollment.headers
            await accept(second)
            assert (await second.get("/bridge/consent/state")).json()["choice"] == "accepted"


async def test_decline_marker_is_nonidentifying_and_only_explicit_accept_clears_it():
    async with browser(create_app(config(), Recorder())) as client:
        response = await client.post(
            "/bridge/consent", json={"choice": "declined", "consent_version": "1"}
        )
        cookies = SimpleCookie()
        for header in response.headers.get_list("set-cookie"):
            attributes = header.split("; ")
            assert attributes.pop() == "Partitioned"
            cookies.load("; ".join(attributes))
        marker = cookies[OPTOUT]
        assert marker.value == "1"
        assert marker["path"] == "/bridge"
        assert marker["max-age"] == str(config().bridge_cookie_max_age)
        assert marker["secure"] and marker["httponly"]
        assert marker["samesite"] == "None"
        assert marker["domain"] == ""
        # Storage loss of the legacy preference cannot erase the separate opt-out.
        client.cookies.delete(CONSENT)
        assert (await client.get("/bridge/consent/state")).json()["choice"] == "declined"
        enrollment = await client.post("/bridge/consent/enroll", json={"consent_version": "1"})
        assert enrollment.json()["choice"] == "declined"
        assert "set-cookie" not in enrollment.headers
        await accept(client)
        assert client.cookies.get(OPTOUT) is None
        assert (await client.get("/bridge/consent/state")).json()["choice"] == "accepted"


@pytest.mark.parametrize("value", ["", "invalid", "2"])
async def test_unrecognized_optout_marker_stays_untracked(value):
    async with browser(create_app(config(), Recorder())) as client:
        await accept(client)
        client.cookies.set(OPTOUT, value, domain="analytics.example", path="/bridge")
        response = await client.post("/bridge/consent/enroll", json={"consent_version": "1"})
        assert response.json()["choice"] == "unknown"
        assert "set-cookie" not in response.headers
        assert (await client.post("/bridge/id", json={})).status_code == 403
        await accept(client)
        assert client.cookies.get(OPTOUT) is None
