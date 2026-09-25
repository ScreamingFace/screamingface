import httpx
import pytest
from test_api import Recorder, settings

from analytics_service.api import create_app
from analytics_service.settings import Settings

LIVE = "https://6ernmmrpvem-496ff2e9c6d22116-0-colab.googleusercontent.com"
ORIGIN = "https://analytics.example"


def config():
    return settings(bridge_enabled=True, bridge_origin=ORIGIN, bridge_colab_enabled=True)


@pytest.mark.parametrize(
    "origin", [LIVE, "https://rb49gy8dleg-496ff2e9c6d22116-0-colab.googleusercontent.com"]
)
async def test_colab_page_csp_uses_exact_validated_parent(origin):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app(config(), Recorder())), base_url=ORIGIN
    ) as c:
        r = await c.get("/bridge/consent", params={"parent_origin": origin})
        assert r.status_code == 200
        csp = r.headers["content-security-policy"]
        assert f"frame-ancestors https://colab.research.google.com {origin};" in csp
        assert "*" not in csp and "set-cookie" not in r.headers
        assert origin not in r.text


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "https://googleusercontent.com",
        "https://attacker.googleusercontent.com",
        LIVE + ".evil.test",
        LIVE + "/path",
        LIVE + ":443",
        LIVE.replace("https:", "http:"),
        LIVE.replace("6ernmmrpvem", "a.b"),
        LIVE.replace("496ff2e9c6d22116", "not-a-hex-token"),
        LIVE + "\n",
        LIVE.replace("https://", "https://user@"),
        LIVE.replace("6ernmmrpvem", "x" * 64),
    ],
)
async def test_colab_origin_rejects_lookalikes(origin):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app(config(), Recorder())), base_url=ORIGIN
    ) as c:
        r = await c.get("/bridge/consent", params={"parent_origin": origin})
        assert r.status_code == 400
        assert "set-cookie" not in r.headers


async def test_no_parent_is_not_broadly_embeddable():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app(config(), Recorder())), base_url=ORIGIN
    ) as c:
        r = await c.get("/bridge/consent")
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        r = await c.get(
            "/bridge/consent", params=[("parent_origin", LIVE), ("parent_origin", LIVE)]
        )
        assert r.status_code == 400
        r = await c.get("/bridge/consent", params={"parent_origin": LIVE, "extra": "x"})
        assert r.status_code == 400


def test_colab_profile_does_not_enable_bridge_or_replace_service_origin():
    assert Settings(bridge_colab_enabled=True).bridge_enabled is False
    with pytest.raises(ValueError):
        Settings(bridge_enabled=True, bridge_colab_enabled=True)


def test_shipped_js_colab_origin_policy():
    import os
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        ["node", "--test", "tests/browser/colab-origins.test.cjs"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        env={**os.environ, "SF_TEST_PYTHON": sys.executable},
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
