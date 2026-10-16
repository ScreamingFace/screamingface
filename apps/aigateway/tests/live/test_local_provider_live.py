from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient

from aigateway.main import create_app
from aigateway.plugins.local_provider.settings import LocalPluginSettings

pytestmark = pytest.mark.live


def _enabled() -> bool:
    return os.environ.get("AIGW_LIVE") == "1" and os.environ.get("AIGW_LIVE_LOCAL_OPENAI") == "1"


def _prepare_database() -> None:
    app_dir = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", "migrate"],
        cwd=app_dir,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            "failed to migrate live AIGateway database\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _selected_model(settings: LocalPluginSettings) -> str:
    if not settings.enabled:
        pytest.fail("AIGW_LOCAL_ENABLED=true is required")
    selected = os.environ.get("AIGW_LIVE_LOCAL_MODEL")
    if not selected:
        pytest.fail("AIGW_LIVE_LOCAL_MODEL must name the downloaded chat model")
    try:
        response = httpx.get(
            f"{settings.base_url}/models",
            timeout=3.0,
            follow_redirects=False,
            trust_env=False,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        pytest.fail(f"local OpenAI-compatible server unavailable: {type(exc).__name__}")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        pytest.fail("local /v1/models response is malformed")
    available = {
        row["id"] for row in data if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    if selected not in available:
        pytest.fail("AIGW_LIVE_LOCAL_MODEL is not present in the local model listing")
    return selected


def _login_if_needed(client: TestClient) -> None:
    app = cast(Any, client.app)
    if app.state.settings.auth_mode == "disabled":
        return
    password = os.environ.get("AIGW_LIVE_ADMIN_PASSWORD") or os.environ.get(
        "AIGATEWAY_ADMIN_PASSWORD"
    )
    if not password:
        pytest.fail("live auth requires AIGW_LIVE_ADMIN_PASSWORD")
    response = client.post(
        "/v1/auth/login",
        json={"username": "admin", "password": password},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})


@pytest.mark.skipif(not _enabled(), reason="local provider live gates are not enabled")
def test_downloaded_local_model_completes_a_strict_gateway_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Live means live: remove the suite-wide no-egress guard installed by conftest.
    monkeypatch.undo()
    settings = LocalPluginSettings()
    model = _selected_model(settings)
    _prepare_database()

    with TestClient(
        create_app(),
        base_url="http://127.0.0.1:9105",
        client=("127.0.0.1", 50000),
    ) as client:
        _login_if_needed(client)
        listing = client.get("/v1/models")
        assert listing.status_code == 200, listing.text
        assert f"local/{model}" in {row["id"] for row in listing.json()["data"]}
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": f"local/{model}",
                "messages": [{"role": "user", "content": "Reply with the word pong."}],
                "max_tokens": 16,
            },
        )

    # The outer env gate may skip the test. Once explicitly enabled, every prerequisite
    # and provider failure is real and must fail this strict smoke.
    assert response.status_code == 200, response.text
    content = response.json()["choices"][0]["message"]["content"]
    assert isinstance(content, str) and content.strip()
