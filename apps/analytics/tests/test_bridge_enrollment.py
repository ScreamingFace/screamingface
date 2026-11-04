"""Automatic enrollment may never reverse a stored decline."""

from http.cookies import SimpleCookie

import pytest
from test_api import Recorder
from test_bridge import ORIGIN, accept, browser, config

from analytics_service.api import create_app
from analytics_service.bridge import CONSENT


async def test_enrollment_sets_preference_without_creating_identity():
    async with browser(create_app(config(), Recorder())) as client:
        response = await client.post("/bridge/consent/enroll", json={"consent_version": "1"})
        assert response.status_code == 200
        assert response.json() == {"choice": "accepted", "consent_version": "1"}
        cookies = SimpleCookie()
        for header in response.headers.get_list("set-cookie"):
            attributes = header.split("; ")
            # Python 3.12/3.13 cannot parse Partitioned; verify it separately.
            assert attributes.pop() == "Partitioned"
            cookies.load("; ".join(attributes))
        assert set(cookies) == {CONSENT}
        assert cookies[CONSENT].value == "1.accepted"
        assert cookies[CONSENT]["max-age"] == str(config().bridge_cookie_max_age)
        assert response.headers["cache-control"] == "no-store"
        identity = await client.post("/bridge/id", json={})
        assert identity.status_code == 200


async def test_enrollment_preserves_decline_saved_after_initial_state_read():
    async with browser(create_app(config(), Recorder())) as client:
        assert (await client.get("/bridge/consent/state")).json()["choice"] == "unknown"
        await client.post("/bridge/consent", json={"choice": "declined", "consent_version": "1"})
        response = await client.post("/bridge/consent/enroll", json={"consent_version": "1"})
        assert response.status_code == 200
        assert response.json()["choice"] == "declined"
        assert "set-cookie" not in response.headers
        assert (await client.post("/bridge/id", json={})).status_code == 403


async def test_enrollment_preserves_existing_identity():
    async with browser(create_app(config(), Recorder())) as client:
        identifier = await accept(client)
        response = await client.post("/bridge/consent/enroll", json={"consent_version": "1"})
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        assert (await client.post("/bridge/id", json={})).json()["persistent_id"] == identifier


@pytest.mark.parametrize("value", ["0.declined", "2.accepted", "invalid", ""])
async def test_enrollment_does_not_replace_unrecognized_cookie(value):
    async with browser(create_app(config(), Recorder())) as client:
        client.cookies.set(CONSENT, value, domain="analytics.example", path="/bridge")
        response = await client.post("/bridge/consent/enroll", json={"consent_version": "1"})
        assert response.status_code == 200
        assert response.json()["choice"] == "unknown"
        assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "body", [{}, {"consent_version": "2"}, {"consent_version": "1", "extra": 1}]
)
async def test_enrollment_validates_body(body):
    async with browser(create_app(config(), Recorder())) as client:
        response = await client.post("/bridge/consent/enroll", json=body)
        assert response.status_code == 422


async def test_enrollment_rejects_foreign_origin():
    async with browser(create_app(config(), Recorder())) as client:
        response = await client.post(
            "/bridge/consent/enroll",
            json={"consent_version": "1"},
            headers={"Origin": ORIGIN + ".evil"},
        )
        assert response.status_code == 403
