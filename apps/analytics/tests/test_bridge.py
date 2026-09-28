from uuid import uuid4

import httpx
import pytest
from test_api import Recorder, settings

from analytics_service.api import create_app
from analytics_service.settings import Settings

ORIGIN = "https://analytics.example"
PARENT = "https://output.example"


def config(**kwargs):
    return settings(
        bridge_enabled=True,
        bridge_origin=ORIGIN,
        bridge_parent_origins=PARENT,
        bridge_ancestor_origins=PARENT,
        **kwargs,
    )


def browser(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )


async def accept(c):
    response = await c.post("/bridge/consent", json={"choice": "accepted", "consent_version": "1"})
    assert response.status_code == 200
    response = await c.post("/bridge/id", json={})
    assert response.status_code == 200
    return response.json()["persistent_id"]


async def test_consent_only_never_creates_id_or_emits():
    recorder = Recorder()
    async with browser(create_app(config(), recorder)) as c:
        for path in ("/bridge/consent", "/bridge/consent/state"):
            response = await c.get(path)
            assert response.status_code == 200
            assert "set-cookie" not in response.headers
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["referrer-policy"] == "no-referrer"
        assert (await c.get("/bridge/consent/state")).json()["choice"] == "unknown"
        assert (await c.post("/bridge/id", json={})).status_code == 403
        response = await c.post(
            "/bridge/consent", json={"choice": "accepted", "consent_version": "1"}
        )
        assert "__Secure-sf_bridge_id=;" in response.headers.get("set-cookie", "")
        assert "Max-Age=0" in response.headers.get("set-cookie", "")
        assert not recorder.batches


async def test_cookie_continuity_decline_and_reenable():
    async with browser(create_app(config(), Recorder())) as c:
        identity = await accept(c)
        response = await c.post("/bridge/id", json={})
        assert response.json()["persistent_id"] == identity
        cookie = response.headers["set-cookie"]
        for attribute in (
            "Secure",
            "HttpOnly",
            "SameSite=None",
            "Partitioned",
            "Path=/bridge/id",
            "Max-Age=15552000",
        ):
            assert attribute in cookie
        assert "Domain=" not in cookie
        response = await c.post(
            "/bridge/consent", json={"choice": "declined", "consent_version": "1"}
        )
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert (await c.get("/bridge/consent/state")).json()["choice"] == "declined"
        assert (await c.post("/bridge/id", json={})).status_code == 403
        assert (await c.post("/bridge/id/revoke", json={})).status_code == 200
        assert await accept(c) != identity


async def test_browser_delivery_and_shared_cookie_revocation(envelope):
    recorder = Recorder()
    app = create_app(config(), recorder)
    async with browser(app) as c:
        identity = await accept(c)
        event = envelope["events"][0]
        event.update(origin="colab", id_scope="browser", persistent_id=identity)
        response = await c.post("/bridge/id/events", json=envelope)
        assert response.status_code == 202
        assert recorder.batches[0].events[0].persistent_id == identity
        await c.post("/bridge/consent", json={"choice": "declined", "consent_version": "1"})
        assert (await c.post("/bridge/id/events", json=envelope)).status_code == 403
        await accept(c)
        # INVARIANT: queued events from before opt-out cannot join the replacement ID.
        assert (await c.post("/bridge/id/events", json=envelope)).status_code == 422
        assert len(recorder.batches) == 1


@pytest.mark.parametrize("origin", [None, "null", "https://evil.example", ORIGIN + ".evil"])
async def test_foreign_origins_cannot_read_or_mutate(origin):
    async with browser(create_app(config(), Recorder())) as c:
        if origin is None:
            del c.headers["Origin"]
        else:
            c.headers["Origin"] = origin
        for path in ("/bridge/consent", "/bridge/id", "/bridge/id/revoke", "/bridge/id/events"):
            response = await c.post(path, json={})
            assert response.status_code == 403
            assert "set-cookie" not in response.headers
            assert "access-control-allow-origin" not in response.headers


async def test_bridge_disabled_by_default():
    async with browser(create_app(settings(), Recorder())) as c:
        for path in ("/bridge/consent", "/bridge/consent/state"):
            assert (await c.get(path)).status_code == 404
        assert (await c.post("/bridge/id", json={})).status_code == 404


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"bridge_origin": "http://analytics.example"},
        {"bridge_parent_origins": "*"},
        {"bridge_parent_origins": "https://example/extra"},
        {"bridge_ancestor_origins": "https://x; *"},
    ],
)
def test_enabled_bridge_requires_exact_https_origins(values):
    args = dict(
        bridge_enabled=True,
        bridge_origin=ORIGIN,
        bridge_parent_origins=PARENT,
        bridge_ancestor_origins=PARENT,
    )
    if not values:
        args.pop("bridge_origin")
    args.update(values)
    with pytest.raises(ValueError):
        Settings.model_validate(args)


async def test_stale_consent_and_invalid_id_fail_closed():
    async with browser(create_app(config(), Recorder())) as c:
        c.cookies.set(
            "__Secure-sf_bridge_consent", "0.accepted", domain="analytics.example", path="/bridge"
        )
        c.cookies.set(
            "__Secure-sf_bridge_id", str(uuid4()), domain="analytics.example", path="/bridge/id"
        )
        assert (await c.get("/bridge/consent/state")).json()["choice"] == "unknown"
        assert (await c.post("/bridge/id", json={})).status_code == 403
        await c.post("/bridge/consent", json={"choice": "accepted", "consent_version": "1"})
        c.cookies.set(
            "__Secure-sf_bridge_id", "malformed", domain="analytics.example", path="/bridge/id"
        )
        response = await c.post("/bridge/id", json={})
        assert response.status_code == 200 and response.json()["persistent_id"] != "malformed"


async def test_sanitized_validation_and_body_limits():
    async with browser(create_app(config(), Recorder())) as c:
        for payload in (
            {"choice": "maybe"},
            {"choice": "accepted", "consent_version": "0"},
            {"choice": "accepted", "consent_version": "1", "private": "secret"},
        ):
            r = await c.post("/bridge/consent", json=payload)
            assert r.status_code == 422 and "secret" not in r.text
        for body, status in [("{bad", 400), ('{"choice":1,"choice":2}', 422), ("x" * 1025, 413)]:
            r = await c.post(
                "/bridge/consent", content=body, headers={"Content-Type": "application/json"}
            )
            assert r.status_code == status
        assert (await c.post("/bridge/id", content="")).status_code == 415


async def test_page_security_and_static_script():
    async with browser(create_app(config(), Recorder())) as c:
        r = await c.get("/bridge/consent")
        assert "frame-ancestors https://output.example" in r.headers["content-security-policy"]
        assert "default-src 'none'" in r.headers["content-security-policy"]
        assert "script-src 'self'" in r.headers["content-security-policy"]
        assert '<script src="/bridge/script.js"></script>' in r.text
        assert "persistent_id" not in r.text
        r = await c.get("/bridge/script.js")
        assert r.status_code == 200 and "postMessage" in r.text
        assert r.headers["x-content-type-options"] == "nosniff"


async def test_stale_cookie_not_resurrected_by_fresh_acceptance():
    async with browser(create_app(config(), Recorder())) as c:
        old = str(uuid4())
        c.cookies.set("__Secure-sf_bridge_id", old, domain="analytics.example", path="/bridge/id")
        assert await accept(c) != old
        current = (await c.post("/bridge/id", json={})).json()["persistent_id"]
        assert await accept(c) == current


async def test_decline_works_while_event_delivery_disabled():
    conf = config().model_copy(update={"enabled": False})
    async with browser(create_app(conf, Recorder())) as c:
        r = await c.post("/bridge/consent", json={"choice": "declined", "consent_version": "1"})
        assert r.status_code == 200


async def test_bridge_other_validation_and_admission(envelope):
    async with browser(create_app(config(requests_per_minute=100), Recorder())) as c:
        assert (await c.post("/bridge/id/revoke", json={})).status_code == 409
        await accept(c)
        assert (await c.post("/bridge/id", json={"private": "no"})).status_code == 422
        assert (await c.post("/bridge/id/events", json=[])).status_code == 422
        assert (await c.post("/bridge/id/events", json={"events": [None]})).status_code == 422
        assert (await c.post("/bridge/id/events", json=envelope)).status_code == 422
        r = await c.post("/bridge/id", json={}, headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 403
    async with browser(create_app(config(requests_per_minute=1), Recorder())) as c:
        await c.post("/bridge/consent", json={"choice": "accepted", "consent_version": "1"})
        assert (await c.post("/bridge/id", json={})).status_code == 429


async def test_bridge_control_timeout_releases_admission():
    import asyncio

    async def body():
        await asyncio.sleep(2)
        yield b"{}"

    async with browser(create_app(config(), Recorder())) as c:
        response = await c.post(
            "/bridge/id", content=body(), headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 503


async def test_no_cookies_means_no_browser_delivery(envelope):
    recorder = Recorder()
    async with browser(create_app(config(), recorder)) as c:
        assert (await c.post("/bridge/id/events", json=envelope)).status_code == 403
        await c.post("/bridge/consent", json={"choice": "accepted", "consent_version": "1"})
        assert (await c.post("/bridge/id/events", json=envelope)).status_code == 403
    assert not recorder.batches


async def test_shared_browser_jar_across_two_replicas(envelope):
    first, second = Recorder(), Recorder()
    async with browser(create_app(config(), first)) as a:
        identity = await accept(a)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_app(config(), second)),
            base_url=ORIGIN,
            headers={"Origin": ORIGIN},
            cookies=a.cookies.jar,
        ) as b:
            envelope["events"][0].update(origin="colab", id_scope="browser", persistent_id=identity)
            assert (await b.post("/bridge/id/events", json=envelope)).status_code == 202
            await a.post("/bridge/consent", json={"choice": "declined", "consent_version": "1"})
            assert (await b.post("/bridge/id/events", json=envelope)).status_code == 403
            assert (await b.get("/bridge/consent/state")).json()["choice"] == "declined"
            assert len(second.batches) == 1
    assert not first.batches


async def test_disconnect_during_consent_body_is_sanitized():
    import asyncio

    app = create_app(config(), Recorder())
    messages = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/bridge/consent",
        "raw_path": b"/bridge/consent",
        "query_string": b"",
        "headers": [(b"origin", ORIGIN.encode()), (b"content-type", b"application/json")],
        "scheme": "https",
        "server": ("analytics.example", 443),
        "client": ("test", 1),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=1)
    assert messages[0]["status"] == 499
