import httpx
import pytest
from pydantic import SecretStr

from analytics_service.api import create_app
from analytics_service.ports import DeliveryUnavailable, UpstreamRejected
from analytics_service.settings import Settings


class Recorder:
    def __init__(self, error=None):
        self.batches = []
        self.error = error

    async def deliver(self, batch):
        self.batches.append(batch)
        if self.error:
            raise self.error


def settings(**kwargs):
    return Settings(
        enabled=True,
        posthog_host="https://posthog.example",
        posthog_allowed_hosts="posthog.example",
        posthog_project_token=SecretStr("test-token"),
        env="test",
        **kwargs,
    )


async def test_http_success_health_and_drain(envelope):
    recorder = Recorder()
    app = create_app(settings(), recorder)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
        assert (await c.get("/healthz")).status_code == 200
        assert (await c.get("/readyz")).status_code == 200
        response = await c.post("/v1/events", json=envelope)
        assert response.status_code == 202
        assert response.json() == {"status": "upstream_accepted", "count": 1}
        assert len(recorder.batches) == 1
        app.state.ingestion.draining = True
        assert (await c.get("/readyz")).status_code == 503
        assert (await c.post("/v1/events", json=envelope)).status_code == 503


@pytest.mark.parametrize("error,status", [(DeliveryUnavailable(), 503), (UpstreamRejected(), 502)])
async def test_no_false_ack(envelope, error, status):
    app = create_app(settings(), Recorder(error))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
        assert (await c.post("/v1/events", json=envelope)).status_code == status


async def test_reject_before_forwarding(envelope, caplog):
    recorder = Recorder()
    app = create_app(settings(), recorder)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
        assert (await c.post("/v1/events", content="private")).status_code == 415
        headers = {"Content-Type": "application/json"}
        assert (await c.post("/v1/events", content="{private", headers=headers)).status_code == 400
        assert (
            await c.post("/v1/events", content=b"x" * 65537, headers=headers)
        ).status_code == 413
        assert (
            await c.post("/v1/events", json=envelope, headers={"Content-Encoding": "gzip"})
        ).status_code == 415
        envelope["events"][0]["email"] = "private@example.test"
        response = await c.post("/v1/events", json=envelope)
        assert response.status_code == 422 and "private" not in response.text
        response = await c.options("/v1/events", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in response.headers
    assert not recorder.batches
    assert "private@example.test" not in caplog.text


async def test_disabled_and_rate_limit(envelope):
    for config, expected in [(Settings(), 503), (settings(requests_per_minute=1), 429)]:
        recorder = Recorder()
        app = create_app(config, recorder)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            await c.post("/v1/events", json=envelope)
            response = await c.post("/v1/events", json=envelope)
            assert response.status_code == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"enabled": True},
        {"enabled": True, "posthog_host": "http://posthog.example"},
        {"enabled": True, "posthog_host": "https://user:secret@posthog.example"},
        {"max_inflight": 0},
        {"env": "unknown"},
    ],
)
def test_bad_settings(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


async def test_chunked_limit_and_duplicate_keys(envelope):
    recorder = Recorder()
    app = create_app(settings(), recorder)

    async def chunks():
        for _ in range(17):
            yield b" " * 4096

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
        headers = {"Content-Type": "application/json"}
        response = await c.post("/v1/events", content=chunks(), headers=headers)
        assert response.status_code == 413
        response = await c.post("/v1/events", content='{"events":[],"events":[]}', headers=headers)
        assert response.status_code == 422
        envelope["events"][0]["private"] = "x" * 5000
        assert (await c.post("/v1/events", json=envelope)).status_code == 413
    assert not recorder.batches


async def test_admission_exhaustion_and_reset():
    from analytics_service.ingestion import AdmissionRejected, Ingestion

    now = [0.0]
    ingestion = Ingestion(
        Recorder(), enabled=True, max_inflight=1, requests_per_minute=2, clock=lambda: now[0]
    )
    ingestion.enter()
    with pytest.raises(AdmissionRejected) as failure:
        ingestion.enter()
    assert failure.value.code == "busy"
    ingestion.leave()
    with pytest.raises(AdmissionRejected) as failure:
        ingestion.enter()
    assert failure.value.status == 429
    now[0] = 60
    ingestion.enter()
    ingestion.leave()
    assert ingestion.inflight == 0


async def test_disconnect_cancels_delivery(envelope):
    import asyncio
    import json

    started = asyncio.Event()
    cancelled = asyncio.Event()

    class WaitingDelivery:
        async def deliver(self, batch):
            started.set()
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()

    app = create_app(settings(), WaitingDelivery())
    body = json.dumps(envelope).encode()
    messages = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        await started.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/events",
        "raw_path": b"/v1/events",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=1)
    assert cancelled.is_set() and app.state.ingestion.inflight == 0
    assert messages[0]["status"] == 499


async def test_lifespan_and_main(monkeypatch):
    from analytics_service.main import build_app, main

    app = build_app(Settings())
    async with app.router.lifespan_context(app):
        assert not app.state.ingestion.draining
    assert app.state.ingestion.draining
    calls = []
    monkeypatch.setattr("analytics_service.main.uvicorn.run", lambda *a, **kw: calls.append(kw))
    main()
    assert calls[0]["access_log"] is False and calls[0]["proxy_headers"] is False
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("ANALYTICS_POSTHOG_PROJECT_TOKEN", "never-print-secret")
    with pytest.raises(SystemExit) as error:
        main()
    assert "never-print-secret" not in str(error.value)


@pytest.mark.parametrize("host", ["https://posthog.example:bad", "https://posthog.example:99999"])
def test_invalid_destination_port(host):
    with pytest.raises(ValueError):
        Settings(
            enabled=True,
            posthog_host=host,
            posthog_allowed_hosts="posthog.example",
            posthog_project_token=SecretStr("token"),
        )


async def test_lifespan_failure_still_closes_delivery():
    closed = []

    async def cleanup():
        closed.append(True)

    app = create_app(settings(), Recorder(), cleanup=cleanup)
    with pytest.raises(RuntimeError):
        async with app.router.lifespan_context(app):
            raise RuntimeError("shutdown")
    assert closed == [True] and app.state.ingestion.draining
