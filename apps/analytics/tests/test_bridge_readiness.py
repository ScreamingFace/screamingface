import pytest
from test_api import Recorder
from test_bridge import accept, browser, config

from analytics_service.api import create_app


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("bridge_enabled", [False, True])
@pytest.mark.parametrize("draining", [False, True])
async def test_readiness_covers_both_capabilities_and_drain(enabled, bridge_enabled, draining):
    conf = config().model_copy(update={"enabled": enabled, "bridge_enabled": bridge_enabled})
    app = create_app(conf, Recorder())
    app.state.ingestion.draining = draining
    async with browser(app) as client:
        response = await client.get("/readyz")
        expected = (enabled or bridge_enabled) and not draining
        assert response.status_code == (200 if expected else 503)
        assert response.json() == {"ready": expected}


async def test_bridge_only_stays_routable_without_enabling_delivery(envelope):
    recorder = Recorder()
    app = create_app(config().model_copy(update={"enabled": False}), recorder)
    async with app.router.lifespan_context(app), browser(app) as client:
        # INVARIANT: Kubernetes must retain the pod for opt-out, even with delivery off.
        assert (await client.get("/readyz")).status_code == 200
        identity = await accept(client)
        envelope["events"][0].update(origin="colab", id_scope="browser", persistent_id=identity)
        for path in ("/v1/events", "/bridge/id/events"):
            assert (await client.post(path, json=envelope)).status_code == 503
        response = await client.post(
            "/bridge/consent", json={"choice": "declined", "consent_version": "1"}
        )
        assert response.status_code == 200
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert (await client.get("/bridge/consent/state")).json()["choice"] == "declined"
        assert (await client.get("/readyz")).status_code == 200
        assert not recorder.batches
    async with browser(app) as client:
        assert (await client.get("/readyz")).status_code == 503
        assert (await client.get("/readyz")).json() == {"ready": False}
