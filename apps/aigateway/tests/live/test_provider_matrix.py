"""Live provider consistency matrix for AIGateway chat completions.

Opt-in only: set ``AIGW_LIVE=1``. By default the suite starts an in-process
gateway using the local live database settings. Set ``AIGW_LIVE_BASE_URL`` to
target a hosted gateway, for example ``https://gateway.screamingface.ai``.

The matrix intentionally checks the OpenAI-compatible AIGateway surface rather
than provider-specific internals. Providers skip cleanly when credentials,
models, or local services are unavailable.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from aigateway.main import create_app

pytestmark = pytest.mark.live

_REQUEST_TIMEOUT = 45.0
_database_prepared = False


@dataclass(frozen=True)
class ProviderCase:
    provider: str
    model: str | None
    supports_streaming: bool


PROVIDERS = (
    ProviderCase("anthropic", "anthropic/claude-haiku-4-5", True),
    ProviderCase("codex", "codex/gpt-5.4-mini", False),
    ProviderCase("gemini-cli", "gemini-cli/gemini-2.5-flash-lite", False),
    ProviderCase("antigravity", "antigravity/gemini-3-flash", False),
    ProviderCase("ollama", None, True),
)


def _live_enabled() -> bool:
    return os.environ.get("AIGW_LIVE") == "1"


def _live_admin_password() -> str:
    password = os.environ.get("AIGW_LIVE_ADMIN_PASSWORD") or os.environ.get(
        "AIGATEWAY_ADMIN_PASSWORD"
    )
    if not password:
        pytest.skip("live matrix requires AIGW_LIVE_ADMIN_PASSWORD or AIGATEWAY_ADMIN_PASSWORD")
        raise AssertionError("unreachable after pytest.skip")
    return password


def _prepare_live_database() -> None:
    global _database_prepared
    if _database_prepared:
        return
    app_dir = Path(__file__).resolve().parents[2]
    command = [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", "migrate"]
    try:
        subprocess.run(
            command,
            cwd=app_dir,
            env=os.environ.copy(),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        pytest.fail(
            "failed to migrate live AIGateway database before provider matrix\n"
            f"stdout:\n{exc.stdout}\n"
            f"stderr:\n{exc.stderr}"
        )
    _database_prepared = True


@pytest.fixture(scope="module")
def live_gateway() -> Generator[httpx.Client | TestClient, None, None]:
    if not _live_enabled():
        pytest.skip("AIGW_LIVE=1 not set")

    base_url = os.environ.get("AIGW_LIVE_BASE_URL")
    if base_url:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=_REQUEST_TIMEOUT) as client:
            _login_admin(client)
            yield client
        return

    _prepare_live_database()
    with TestClient(create_app()) as client:
        _login_admin(client)
        yield client


def _login_admin(client: httpx.Client | TestClient) -> None:
    response = client.post(
        "/v1/auth/login",
        json={"username": "admin", "password": _live_admin_password()},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})


@pytest.fixture(scope="module")
def model_ids(live_gateway: httpx.Client | TestClient) -> set[str]:
    response = live_gateway.get("/v1/models")
    assert response.status_code == 200, response.text
    payload = response.json()
    return {
        item["id"]
        for item in payload.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _provider_id(case: ProviderCase) -> str:
    return case.provider


def _model_for(case: ProviderCase, model_ids: set[str]) -> str:
    if case.provider == "ollama":
        for model in sorted(model_ids):
            if model.startswith("ollama/"):
                return model
        pytest.skip("ollama has no discovered models in /v1/models")
        raise AssertionError("unreachable after pytest.skip")

    assert case.model is not None
    if case.model in model_ids:
        return case.model

    _, slug = case.model.split("/", 1)
    if slug in model_ids:
        return case.model
    pytest.skip(f"{case.provider} model {case.model!r} not present in /v1/models")
    raise AssertionError("unreachable after pytest.skip")


def _provider_headers(client: httpx.Client | TestClient, case: ProviderCase) -> dict[str, str]:
    if case.provider == "ollama":
        return {}

    connection = _single_active_connection(client, case.provider)
    if connection is not None:
        return {}

    if _default_profile_authenticated(client, case.provider):
        return {}

    if case.provider == "gemini-cli":
        # Gemini can also run through gateway-owned API-key fallback. If absent,
        # the first chat request will return auth_required and be skipped.
        return {}

    pytest.skip(f"{case.provider} has no active OAuth connection or authenticated default profile")
    raise AssertionError("unreachable after pytest.skip")


def _single_active_connection(
    client: httpx.Client | TestClient,
    provider: str,
) -> dict[str, Any] | None:
    response = client.get(
        "/v1/oauth/connections",
        params={"provider": provider, "status": "active"},
    )
    if response.status_code != 200:
        return None
    connections = response.json().get("connections", [])
    if not connections:
        return None
    if len(connections) > 1:
        pytest.skip(f"{provider} has multiple active OAuth connections; remove extras before retry")
    connection = connections[0]
    if not isinstance(connection.get("label"), str) or not connection["label"]:
        pytest.skip(f"{provider} active OAuth connection has no usable label")
    return connection


def _default_profile_authenticated(client: httpx.Client | TestClient, provider: str) -> bool:
    response = client.get(f"/v1/auth/{provider}/profiles/default/status")
    if response.status_code != 200:
        return False
    body = response.json()
    return body.get("state") == "authenticated" or body.get("authenticated") is True


def _chat_json(
    client: httpx.Client | TestClient,
    case: ProviderCase,
    model_ids: set[str],
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 80,
) -> dict[str, Any]:
    response = client.post(
        "/v1/chat/completions",
        headers=_provider_headers(client, case),
        json={"model": _model_for(case, model_ids), "messages": messages, "max_tokens": max_tokens},
    )
    _ensure_success_or_skip(response, case.provider, scenario="chat")
    return response.json()


def _message_text(body: dict[str, Any]) -> str:
    message = body["choices"][0]["message"]
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts).strip()
    return ""


def _ensure_success_or_skip(response: httpx.Response, provider: str, *, scenario: str) -> None:
    if response.status_code == 200:
        return
    detail = _response_detail(response)
    code = detail.get("code") if isinstance(detail, dict) else None
    if response.status_code in {401, 403, 404}:
        pytest.skip(
            f"{provider} credentials unavailable for {scenario}: {code or response.status_code}"
        )
    if response.status_code == 409:
        pytest.skip(
            f"{provider} profile/connection unavailable for {scenario}: {code or 'conflict'}"
        )
    if response.status_code == 429 or code == "rate_limited":
        pytest.skip(f"{provider} rate limited during {scenario}")
    if scenario == "streaming" and code == "streaming_not_supported":
        pytest.skip(f"{provider} streaming is not supported by this gateway plugin")
    if provider == "ollama" and response.status_code >= 500:
        pytest.skip(f"local Ollama unavailable during {scenario}: {code or response.status_code}")
    assert response.status_code == 200, response.text[:500]


def _response_detail(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload.get("detail") if isinstance(payload, dict) else None


def _json_from_text(text: str) -> Any:
    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


@contextmanager
def _stream_response(
    client: httpx.Client | TestClient,
    case: ProviderCase,
    model_ids: set[str],
) -> Iterator[httpx.Response]:
    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=_provider_headers(client, case),
        json={
            "model": _model_for(case, model_ids),
            "messages": [{"role": "user", "content": "Reply with the word stream."}],
            "max_tokens": 20,
            "stream": True,
        },
    ) as response:
        yield response


@pytest.mark.parametrize("case", PROVIDERS, ids=_provider_id)
def test_simple_completion(
    live_gateway: httpx.Client | TestClient,
    model_ids: set[str],
    case: ProviderCase,
) -> None:
    body = _chat_json(
        live_gateway,
        case,
        model_ids,
        [{"role": "user", "content": "Say hello in one word."}],
        max_tokens=30,
    )
    text = _message_text(body)
    assert text
    assert len(text) <= 30


@pytest.mark.parametrize("case", PROVIDERS, ids=_provider_id)
def test_json_mode(
    live_gateway: httpx.Client | TestClient,
    model_ids: set[str],
    case: ProviderCase,
) -> None:
    body = _chat_json(
        live_gateway,
        case,
        model_ids,
        [
            {
                "role": "user",
                "content": 'Return only valid compact JSON exactly like {"ok":true}.',
            }
        ],
        max_tokens=60,
    )
    parsed = _json_from_text(_message_text(body))
    assert isinstance(parsed, dict)
    assert parsed.get("ok") is True


@pytest.mark.parametrize("case", PROVIDERS, ids=_provider_id)
def test_multi_turn(
    live_gateway: httpx.Client | TestClient,
    model_ids: set[str],
    case: ProviderCase,
) -> None:
    body = _chat_json(
        live_gateway,
        case,
        model_ids,
        [
            {"role": "user", "content": "Remember the code word orchid."},
            {"role": "assistant", "content": "I will remember the code word orchid."},
            {"role": "user", "content": "What code word did I ask you to remember?"},
        ],
        max_tokens=40,
    )
    assert "orchid" in _message_text(body).lower()


@pytest.mark.parametrize("case", PROVIDERS, ids=_provider_id)
def test_streaming(
    live_gateway: httpx.Client | TestClient,
    model_ids: set[str],
    case: ProviderCase,
) -> None:
    if not case.supports_streaming:
        pytest.skip(f"{case.provider} plugin does not support streaming yet")

    with _stream_response(live_gateway, case, model_ids) as response:
        _ensure_success_or_skip(response, case.provider, scenario="streaming")
        data_lines = [
            line.removeprefix("data: ")
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]

    assert data_lines
    assert data_lines[-1] == "[DONE]"
    chunks = [json.loads(line) for line in data_lines[:-1]]
    text = "".join(
        choice.get("delta", {}).get("content") or ""
        for chunk in chunks
        for choice in chunk.get("choices", [])
    )
    assert chunks
    assert text.strip()
