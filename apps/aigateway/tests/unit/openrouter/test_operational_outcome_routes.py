from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException
from litellm.exceptions import AuthenticationError

from aigateway.core.oauth.store import credential_key_for
from aigateway.core.provider_access import PairAuthorityStore
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings


@pytest.fixture(autouse=True)
def _explicit_api_key_validation(valid_api_key_readiness: None) -> None:
    """Keep this new module outside the frozen legacy validation allowlist."""


@pytest.fixture
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


@contextmanager
def _server_errors_as_responses(client: Any) -> Iterator[None]:
    transport = getattr(client, "_transport")
    previous = transport.raise_server_exceptions
    transport.raise_server_exceptions = False
    try:
        yield
    finally:
        transport.raise_server_exceptions = previous


def _account_id(client: Any) -> str:
    return cast(str, client.get("/v1/auth/me").json()["id"])


def _create_effective_connection(client: Any) -> tuple[str, str]:
    account_id = _account_id(client)
    response = client.post(
        "/v1/oauth/connections/api-key",
        json={
            "provider": "openrouter",
            "label": "work-openrouter",
            "api_key": "sk-or-v1-operational-outcome-test",
        },
    )
    assert response.status_code == 201, response.text
    connection_id = cast(str, response.json()["id"])

    async def migrate() -> None:
        markers = PairAuthorityStore()
        current = await markers.read(account_id, "openrouter")
        await markers.advance(
            account_id,
            "openrouter",
            expected_generation=current.generation,
            migration_state="migrated",
            effective_connection_id=UUID(connection_id),
        )

    client.portal.call(migrate)
    return account_id, connection_id


def _chat(client: Any, content: str = "hello") -> Any:
    return client.post(
        "/v1/chat/completions",
        json={
            "model": "openrouter/anthropic/claude-fable-5",
            "messages": [{"role": "user", "content": content}],
        },
    )


@pytest.mark.parametrize("neutral_status", [429, 500])
def test_neutral_route_failures_do_not_replace_the_last_classified_outcome(
    enabled_openrouter: None, authenticated_client: Any, neutral_status: int
) -> None:
    account_id, connection_id = _create_effective_connection(authenticated_client)
    attempt = 0

    async def fail(_self: Any, _body: dict[str, Any]) -> None:
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise HTTPException(
                status_code=402,
                detail={"code": "insufficient_credits", "message": "quota"},
            )
        raise HTTPException(status_code=neutral_status, detail={"code": "transient"})

    with patch(
        "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion",
        fail,
    ):
        assert _chat(authenticated_client, "quota").status_code == 402
        before = authenticated_client.portal.call(
            authenticated_client.app.state.credential_store.operational_state,
            f"aigateway:openrouter:{credential_key_for(account_id, connection_id)}",
            "default",
        )
        assert _chat(authenticated_client, "transient").status_code == neutral_status
        after = authenticated_client.portal.call(
            authenticated_client.app.state.credential_store.operational_state,
            f"aigateway:openrouter:{credential_key_for(account_id, connection_id)}",
            "default",
        )

    assert before is not None and after is not None
    assert after.outcome == before.outcome == "insufficient_credits"
    assert after.last_outcome_sequence == before.last_outcome_sequence


def test_dispatch_sequence_is_reserved_before_credential_authorization(
    enabled_openrouter: None,
    authenticated_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_effective_connection(authenticated_client)
    access = authenticated_client.app.state.provider_access
    original_begin = access.begin_dispatch
    original_authorize = access.authorize
    events: list[str] = []

    async def begin(*args: Any, **kwargs: Any) -> Any:
        events.append("reserve")
        return await original_begin(*args, **kwargs)

    async def authorize(*args: Any, **kwargs: Any) -> Any:
        events.append("authorize")
        return await original_authorize(*args, **kwargs)

    monkeypatch.setattr(access, "begin_dispatch", begin)
    monkeypatch.setattr(access, "authorize", authorize)

    async def succeed(_self: Any, _body: dict[str, Any]) -> Any:
        return SimpleNamespace(model_dump=lambda: {"id": "ok", "choices": []})

    with patch(
        "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion",
        succeed,
    ):
        response = _chat(authenticated_client)

    assert response.status_code == 200, response.text
    assert events == ["reserve", "authorize"]


def test_dispatch_admission_store_failure_is_retryable_and_fail_closed(
    enabled_openrouter: None,
    authenticated_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_effective_connection(authenticated_client)

    async def unavailable(_service: str, _account: str) -> None:
        raise RuntimeError("database secret")

    monkeypatch.setattr(
        authenticated_client.app.state.credential_store, "begin_dispatch", unavailable
    )

    response = _chat(authenticated_client)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["detail"]["code"] == "credential_store_unavailable"
    assert "database secret" not in response.text


@pytest.mark.parametrize(
    "method,path", [("post", "/v1/chat/completions"), ("get", "/v1/provider-access")]
)
def test_operational_state_read_failure_is_a_retryable_sanitized_503(
    enabled_openrouter: None,
    authenticated_client: Any,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    _create_effective_connection(authenticated_client)

    async def unavailable(_service: str, _account: str) -> None:
        raise RuntimeError("database secret")

    monkeypatch.setattr(
        authenticated_client.app.state.credential_store, "operational_state", unavailable
    )
    kwargs = (
        {
            "json": {
                "model": "openrouter/anthropic/claude-fable-5",
                "messages": [{"role": "user", "content": "hello"}],
            }
        }
        if method == "post"
        else {}
    )

    with _server_errors_as_responses(authenticated_client):
        response = getattr(authenticated_client, method)(path, **kwargs)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["detail"]["code"] == "credential_store_unavailable"
    assert "database secret" not in response.text


def test_model_admission_relays_operational_store_failure_as_retryable_503(
    enabled_openrouter: None,
    authenticated_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_effective_connection(authenticated_client)

    async def unavailable(_service: str, _account: str) -> None:
        raise RuntimeError("database secret")

    monkeypatch.setattr(
        authenticated_client.app.state.credential_store, "operational_state", unavailable
    )

    response = authenticated_client.post(
        "/v1/models/admit", json={"model_id": "openrouter/review/round-two"}
    )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["detail"]["code"] == "credential_store_unavailable"
    assert "database secret" not in response.text


def test_disabled_plugin_does_not_fabricate_a_reauthentication_outcome(
    enabled_openrouter: None,
    authenticated_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_effective_connection(authenticated_client)
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN,
        "settings",
        OpenRouterPluginSettings(enabled=False),
    )

    response = authenticated_client.get("/v1/provider-access")

    assert response.status_code == 200, response.text
    statuses = {row["provider"]: row["status"] for row in response.json()["providers"]}
    assert statuses["openrouter"] == "connected"


def test_persisted_insufficient_credits_preserves_the_provider_detail(
    enabled_openrouter: None,
    authenticated_client: Any,
) -> None:
    account_id, connection_id = _create_effective_connection(authenticated_client)
    detail = {"code": "insufficient_credits", "message": "credits exhausted"}

    async def insufficient(_self: Any, _body: dict[str, Any]) -> None:
        raise HTTPException(status_code=402, detail=detail)

    with patch(
        "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion",
        insufficient,
    ):
        response = _chat(authenticated_client)

    state = authenticated_client.portal.call(
        authenticated_client.app.state.credential_store.operational_state,
        f"aigateway:openrouter:{credential_key_for(account_id, connection_id)}",
        "default",
    )
    assert response.status_code == 402
    assert response.json()["detail"] == detail
    assert state is not None and state.outcome == "insufficient_credits"


def test_litellm_authentication_error_records_needs_reauth(
    enabled_openrouter: None,
    authenticated_client: Any,
) -> None:
    account_id, connection_id = _create_effective_connection(authenticated_client)

    async def rejected(_self: Any, _body: dict[str, Any]) -> None:
        raise AuthenticationError(
            message="invalid provider key",
            llm_provider="openrouter",
            model="openrouter/review/round-two",
        )

    with patch(
        "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion",
        rejected,
    ):
        response = _chat(authenticated_client)

    state = authenticated_client.portal.call(
        authenticated_client.app.state.credential_store.operational_state,
        f"aigateway:openrouter:{credential_key_for(account_id, connection_id)}",
        "default",
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "auth_required"
    assert state is not None and state.outcome == "needs_reauth"


def test_success_response_is_fail_open_when_outcome_persistence_fails(
    enabled_openrouter: None,
    authenticated_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_effective_connection(authenticated_client)
    attempts = 0

    async def unavailable(*_args: Any, **_kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("database secret")

    async def succeed(_self: Any, _body: dict[str, Any]) -> Any:
        return SimpleNamespace(model_dump=lambda: {"id": "paid", "choices": []})

    monkeypatch.setattr(
        authenticated_client.app.state.credential_store,
        "record_dispatch_outcome",
        unavailable,
    )
    with patch(
        "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion",
        succeed,
    ):
        response = _chat(authenticated_client)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == "paid"
    assert attempts == 1
    assert "database secret" not in response.text


def test_success_response_records_operational_outcome_once(
    enabled_openrouter: None,
    authenticated_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_effective_connection(authenticated_client)
    attempts = 0

    async def recorded(*_args: Any, **_kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1

    async def succeed(_self: Any, _body: dict[str, Any]) -> Any:
        return SimpleNamespace(model_dump=lambda: {"id": "paid", "choices": []})

    monkeypatch.setattr(
        authenticated_client.app.state.credential_store,
        "record_dispatch_outcome",
        recorded,
    )
    with patch(
        "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion",
        succeed,
    ):
        response = _chat(authenticated_client)

    assert response.status_code == 200, response.text
    assert attempts == 1


def test_missing_blob_at_dispatch_admission_refuses_before_provider_call(
    enabled_openrouter: None,
    authenticated_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_effective_connection(authenticated_client)

    async def missing(_service: str, _account: str) -> None:
        return None

    monkeypatch.setattr(authenticated_client.app.state.credential_store, "begin_dispatch", missing)
    with patch(
        "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion"
    ) as dispatched:
        response = _chat(authenticated_client)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "auth_required"
    assert dispatched.call_count == 0
