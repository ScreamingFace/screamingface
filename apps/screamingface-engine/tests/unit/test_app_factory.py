from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport

from screamingface_engine import cli
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio

SECRET = "app-factory-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
T0 = datetime(2026, 7, 21, 9, 0, 0, tzinfo=UTC)


class _PresentGate:
    async def has_subscriber(self, topic: str) -> bool:
        return True


def _unconfigured_app() -> object:
    settings = Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S)
    return create_app(
        settings,
        stream=InMemoryEventStream(),
        job_runner=None,
        clock=lambda: T0,
        interest=_PresentGate(),
    )


def _cap(topic: str) -> dict[str, str]:
    return {"URL4-Capability": JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(topic, T0)}


@pytest.mark.anyio
async def test_run_start_without_job_runner_is_503_not_500() -> None:
    app = _unconfigured_app()
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/", params={"q": "'hi'!'go'"}, headers=_cap("topic-a"))

    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["status"] == 503


@pytest.mark.anyio
async def test_stop_without_job_runner_is_503_not_500() -> None:
    app = _unconfigured_app()
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/", params={"topic": "topic-a"}, headers=_cap("topic-a"))

    assert resp.status_code == 503


def test_prod_cli_serves_the_env_wired_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, object] = {}

    def _fake_run(app: object, **kwargs: object) -> None:
        recorded["app"] = app
        recorded.update(kwargs)

    monkeypatch.setattr("uvicorn.run", _fake_run)
    cli.main([])

    assert recorded["app"] == "screamingface_engine.app:create_app_from_env"
    assert recorded["factory"] is True
