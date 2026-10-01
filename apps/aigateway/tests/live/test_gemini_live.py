"""Live Gemini gateway smoke test pinned to gemini-2.5-flash.

Skipped unless AIGW_LIVE=1. Uses a gateway-owned gemini-cli:default OAuth
profile when present, otherwise falls back to GEMINI_API_KEY / GOOGLE_API_KEY.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aigateway.main import create_app

pytestmark = pytest.mark.live

_database_prepared = False


def _live_enabled() -> bool:
    return os.environ.get("AIGW_LIVE") == "1"


def _prepare_live_database() -> None:
    global _database_prepared
    if _database_prepared:
        return
    app_dir = Path(__file__).resolve().parents[2]
    try:
        subprocess.run(
            [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", "migrate"],
            cwd=app_dir,
            env=os.environ.copy(),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        pytest.fail(
            "failed to migrate live AIGateway database before Gemini live test\n"
            f"stdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
        )
    _database_prepared = True


def _live_admin_password() -> str:
    password = os.environ.get("AIGW_LIVE_ADMIN_PASSWORD") or os.environ.get(
        "AIGATEWAY_ADMIN_PASSWORD"
    )
    if not password:
        pytest.skip("Live auth tests require AIGW_LIVE_ADMIN_PASSWORD or AIGATEWAY_ADMIN_PASSWORD")
    assert password is not None
    return password


def _login_admin(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/login", json={"username": "admin", "password": _live_admin_password()}
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})


def _live_client() -> TestClient:
    _prepare_live_database()
    return TestClient(create_app())


def _gemini_request_headers(client: TestClient) -> dict[str, str]:
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return {}

    listing = client.get("/v1/auth/profiles")
    assert listing.status_code == 200, listing.text
    profile = next(
        (
            p
            for p in listing.json()["profiles"]
            if p["provider"] == "gemini-cli" and p["name"] == "default"
        ),
        None,
    )
    if profile is None:
        pytest.skip("Gemini live test requires GEMINI_API_KEY/GOOGLE_API_KEY or gemini-cli:default")
    assert profile is not None
    if profile["state"] != "authenticated":
        pytest.skip(f"gemini-cli:default profile is {profile['state']!r}, not 'authenticated'")
    return {}


@pytest.mark.skipif(not _live_enabled(), reason="AIGW_LIVE=1 not set")
def test_gemini_flash_round_trip() -> None:
    _live_admin_password()
    with _live_client() as client:
        _login_admin(client)
        resp = client.post(
            "/v1/chat/completions",
            headers=_gemini_request_headers(client),
            json={
                "model": "gemini-cli/gemini-2.5-flash",
                "messages": [{"role": "user", "content": "Reply with the single word 'pong'."}],
                "max_tokens": 10,
            },
        )

    assert resp.status_code == 200, resp.text
    assert "pong" in resp.json()["choices"][0]["message"]["content"].lower()
