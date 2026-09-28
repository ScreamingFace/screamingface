"""End-to-end live BYOK smoke against openrouter.ai (OME-428 Phase 4, optional).

Owner-gated: skipped unless AIGW_LIVE=1 AND AIGW_LIVE_OPENROUTER_KEY is set —
the key is a real OpenRouter API key supplied by the owner for this run only.
It is stored through the normal encrypted connection lifecycle (never via env
fallback inside the gateway: the poisoned-globals contract tests pin that) and
never echoed by any response.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx
import litellm
import pytest
from fastapi.testclient import TestClient
from litellm.caching.caching import Cache
from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER
from litellm.types.utils import CredentialItem

from aigateway.main import create_app
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

pytestmark = pytest.mark.live

_CONNECTION_LABEL = "live-openrouter-smoke"

_database_prepared = False


def _live_enabled() -> bool:
    return os.environ.get("AIGW_LIVE") == "1"


def _disposable_live_enabled() -> bool:
    # INVARIANT: setting this flag declares that the key will be revoked
    # immediately after the owner-gated adversarial run.
    return _live_enabled() and os.environ.get("AIGW_LIVE_OPENROUTER_DISPOSABLE_KEY") == "1"


def _live_openrouter_key() -> str:
    key = os.environ.get("AIGW_LIVE_OPENROUTER_KEY")
    if not key:
        pytest.skip("Live OpenRouter test requires AIGW_LIVE_OPENROUTER_KEY")
    assert key is not None
    return key


def _live_model() -> str:
    return os.environ.get("AIGW_LIVE_OPENROUTER_MODEL", "openrouter/google/gemma-4-26b-a4b-it:free")


def _disposable_free_model() -> str:
    if not _disposable_live_enabled():
        pytest.skip("Disposable-key tests require AIGW_LIVE_OPENROUTER_DISPOSABLE_KEY=1")
    model = _live_model()
    if not model.endswith(":free"):
        pytest.skip("Disposable-key tests require an explicit :free model")
    return model


def _assert_live_key_not_returned(response_text: str, api_key: str) -> None:
    if api_key in response_text:
        pytest.fail("OpenRouter credential appeared in the AIGateway response", pytrace=False)


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
            "failed to migrate live AIGateway database before OpenRouter live test\n"
            f"stdout:\n{exc.stdout}\n"
            f"stderr:\n{exc.stderr}"
        )

    _database_prepared = True


def _live_client() -> TestClient:
    _prepare_live_database()
    return TestClient(create_app())


def _login_admin(client: TestClient) -> None:
    password = _live_admin_password()
    response = client.post("/v1/auth/login", json={"username": "admin", "password": password})
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})


def _live_admin_password() -> str:
    password = os.environ.get("AIGW_LIVE_ADMIN_PASSWORD") or os.environ.get(
        "AIGATEWAY_ADMIN_PASSWORD"
    )
    if not password:
        pytest.skip("Live auth tests require AIGW_LIVE_ADMIN_PASSWORD or AIGATEWAY_ADMIN_PASSWORD")
    assert password is not None
    return password


def _ensure_connection(client: TestClient, api_key: str) -> None:
    """Create the smoke connection, or refresh its key so reruns stay green.

    PUT api-key re-activates an errored connection, so a previous failed run
    (e.g. a revoked key that tripped the local-401 invalidation) self-heals.
    """
    listing = client.get("/v1/oauth/connections", params={"provider": "openrouter"})
    _assert_live_key_not_returned(listing.text, api_key)
    assert listing.status_code == 200, f"unexpected listing status: {listing.status_code}"
    connections = listing.json()["connections"]
    active_others = [
        connection
        for connection in connections
        if connection["status"] == "active" and connection["label"] != _CONNECTION_LABEL
    ]
    if active_others:
        pytest.skip("OpenRouter live smoke requires one effective Connection; remove active extras")
    existing = next(
        (connection for connection in connections if connection["label"] == _CONNECTION_LABEL),
        None,
    )
    if existing is None:
        created = client.post(
            "/v1/oauth/connections/api-key",
            json={"provider": "openrouter", "label": _CONNECTION_LABEL, "api_key": api_key},
        )
        _assert_live_key_not_returned(created.text, api_key)
        assert created.status_code == 201, f"unexpected create status: {created.status_code}"
        return
    replaced = client.put(
        f"/v1/oauth/connections/{existing['id']}/api-key",
        json={"api_key": api_key},
    )
    _assert_live_key_not_returned(replaced.text, api_key)
    assert replaced.status_code == 200, f"unexpected replace status: {replaced.status_code}"


@pytest.mark.skipif(not _live_enabled(), reason="AIGW_LIVE=1 not set")
def test_openrouter_byok_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    api_key = _live_openrouter_key()
    _live_admin_password()
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )

    with _live_client() as client:
        _login_admin(client)
        _ensure_connection(client, api_key)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": _live_model(),
                "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
                "max_tokens": 16,
            },
        )
        _assert_live_key_not_returned(resp.text, api_key)
        assert resp.status_code == 200, f"unexpected completion status: {resp.status_code}"
        data = resp.json()

        # Native metadata survives the gateway (D10): OpenRouter generation id,
        # text, finish reason, and token usage are all present.
        assert str(data.get("id", "")), data
        content = data["choices"][0]["message"]["content"]
        assert content and content.strip()
        assert data["choices"][0]["finish_reason"]
        usage = data.get("usage")
        assert isinstance(usage, dict), data
        assert usage.get("prompt_tokens", 0) > 0
        assert usage.get("completion_tokens", 0) > 0


@pytest.mark.skipif(not _live_enabled(), reason="AIGW_LIVE=1 not set")
def test_openrouter_byok_round_trip_ignores_ambient_and_request_routing_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Poisoned caller and ambient routing cannot divert a real BYOK request."""
    api_key = _live_openrouter_key()
    model = _live_model()
    if not model.endswith(":free"):
        pytest.skip("The additional hardening smoke requires an explicit :free model")
    _live_admin_password()
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-poisoned-openrouter")
    monkeypatch.setenv("OR_API_KEY", "sk-or-poisoned-or")
    monkeypatch.setenv("OPENROUTER_API_BASE", "http://127.0.0.1:9/v1")

    with _live_client() as client:
        _login_admin(client)
        _ensure_connection(client, api_key)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
                "max_tokens": 32,
                "temperature": 0,
                "api_key": "sk-or-caller-poisoned",
                "api_base": "http://127.0.0.1:9/v1",
                "base_url": "http://127.0.0.1:9/v1",
                "extra_headers": {
                    "Authorization": "Bearer sk-or-header-poisoned",
                },
            },
        )

        _assert_live_key_not_returned(resp.text, api_key)
        assert resp.status_code == 200, f"unexpected completion status: {resp.status_code}"
        data = resp.json()
        assert str(data.get("id", "")), data
        assert data["choices"][0]["message"]["content"], data
        assert data["choices"][0]["finish_reason"], data
        usage = data.get("usage")
        assert isinstance(usage, dict), data
        assert usage.get("prompt_tokens", 0) > 0
        assert usage.get("completion_tokens", 0) > 0


@pytest.mark.skipif(not _live_enabled(), reason="AIGW_LIVE=1 not set")
def test_disposable_key_named_credential_cannot_leave_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Block any non-OpenRouter destination before it reaches network transport."""
    api_key = _live_openrouter_key()
    model = _disposable_free_model()
    _live_admin_password()
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )
    original_send = httpx.AsyncClient.send
    blocked_destinations = 0

    async def official_openrouter_only(self, request, *args, **kwargs):  # noqa: ANN001
        nonlocal blocked_destinations
        if request.url.host != "openrouter.ai":
            blocked_destinations += 1
            return httpx.Response(418, request=request)
        return await original_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", official_openrouter_only)
    monkeypatch.setattr(
        litellm,
        "credential_list",
        [
            CredentialItem(
                credential_name="disposable-local-sink",
                credential_info={},
                credential_values={"base_url": "https://attacker.invalid/v1"},
            )
        ],
    )

    with _live_client() as client:
        _login_admin(client)
        _ensure_connection(client, api_key)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
                "max_tokens": 32,
                "litellm_credential_name": "disposable-local-sink",
            },
        )
        _assert_live_key_not_returned(response.text, api_key)
        assert blocked_destinations == 0
        assert response.status_code == 200, f"unexpected completion status: {response.status_code}"


@pytest.mark.skipif(not _live_enabled(), reason="AIGW_LIVE=1 not set")
def test_disposable_key_unsafe_globals_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = _live_openrouter_key()
    model = _disposable_free_model()
    _live_admin_password()
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )

    def allow_rule(_input: str) -> bool:
        return True

    unsafe_states: tuple[tuple[str, object], ...] = (
        ("model_alias_map", {model: model}),
        ("callbacks", [object()]),
        ("pre_call_rules", [allow_rule]),
        ("post_call_rules", [allow_rule]),
    )

    with _live_client() as client:
        _login_admin(client)
        _ensure_connection(client, api_key)
        for attribute, value in unsafe_states:
            original = getattr(litellm, attribute)
            setattr(litellm, attribute, value)
            try:
                response = client.post(
                    "/v1/chat/completions",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
                        "max_tokens": 16,
                    },
                )
            finally:
                setattr(litellm, attribute, original)
            _assert_live_key_not_returned(response.text, api_key)
            assert response.status_code == 503
            assert response.json() == {
                "detail": {
                    "code": "provider_unavailable",
                    "message": "OpenRouter dispatch is unavailable",
                }
            }


@pytest.mark.skipif(not _live_enabled(), reason="AIGW_LIVE=1 not set")
def test_disposable_key_retries_synthetic_503_then_reaches_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = _live_openrouter_key()
    model = _disposable_free_model()
    _live_admin_password()
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )
    original_send = httpx.AsyncClient.send
    calls = 0

    async def send_with_first_attempt_failure(self, request, *args, **kwargs):  # noqa: ANN001
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                503,
                headers={"Retry-After": "0"},
                json={"error": {"code": 503, "message": "synthetic disposable-key retry"}},
                request=request,
            )
        return await original_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", send_with_first_attempt_failure)
    with _live_client() as client:
        _login_admin(client)
        _ensure_connection(client, api_key)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
                "max_tokens": 32,
            },
        )
        _assert_live_key_not_returned(response.text, api_key)
        assert response.status_code == 200, f"unexpected completion status: {response.status_code}"
        assert calls == 2


@pytest.mark.skipif(not _live_enabled(), reason="AIGW_LIVE=1 not set")
def test_disposable_key_bypasses_global_litellm_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = _live_openrouter_key()
    model = _disposable_free_model()
    _live_admin_password()
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )
    callback_fields = (
        "callbacks",
        "input_callback",
        "success_callback",
        "failure_callback",
        "_async_input_callback",
        "_async_success_callback",
        "_async_failure_callback",
    )
    callback_snapshots = {field: list(getattr(litellm, field)) for field in callback_fields}
    original_cache = litellm.cache
    monkeypatch.setattr(litellm, "cache", Cache())

    try:
        with _live_client() as client:
            try:
                _login_admin(client)
                _ensure_connection(client, api_key)
                responses = [
                    client.post(
                        "/v1/chat/completions",
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
                            "max_tokens": 32,
                            "temperature": 0,
                        },
                    )
                    for _ in range(2)
                ]
                for response in responses:
                    _assert_live_key_not_returned(response.text, api_key)
                    assert response.status_code == 200, (
                        f"unexpected completion status: {response.status_code}"
                    )
                assert responses[0].json()["id"] != responses[1].json()["id"]
            finally:
                portal = client.portal
                assert portal is not None
                portal.call(GLOBAL_LOGGING_WORKER.flush)
    finally:
        for field, snapshot in callback_snapshots.items():
            getattr(litellm, field)[:] = snapshot
        litellm.cache = original_cache
