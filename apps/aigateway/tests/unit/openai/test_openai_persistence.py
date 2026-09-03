"""Direct OpenAI through both generic encrypted API-key persistence surfaces."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import patch

from aigateway.core.api_key_strategy import ApiKeyStrategy
from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.oauth.store import credential_key_for
from aigateway.core.profile_models import credential_name_for
from aigateway.plugins.openai_provider.plugin import PLUGIN

_OLD_KEY = "sk-openai-synthetic-old-key-1234"
_NEW_KEY = "sk-openai-synthetic-new-key-5678"
_REJECTED_KEY = "sk-openai-synthetic-rejected-key-9012"


@dataclass
class _StubValidationService:
    result: ApiKeyValidationResult
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def validate(self, _plugin, provider: str, api_key: str) -> ApiKeyValidationResult:
        self.calls.append((provider, api_key))
        return self.result


def _valid_result() -> ApiKeyValidationResult:
    return ApiKeyValidationResult(
        ApiKeyValidationState.VALID,
        stage=ApiKeyValidationStage.READINESS,
        probe_model="openai/gpt-5-nano",
    )


def _service_for(name: str) -> str:
    strategy = PLUGIN.api_key_strategy_for(name)
    assert isinstance(strategy, ApiKeyStrategy)
    return strategy.credential_service()


def test_profile_create_failed_replace_and_delete_preserve_atomic_key_state(
    authenticated_client,
    credential_blobs,
) -> None:
    validation = _StubValidationService(_valid_result())
    authenticated_client.app.state.api_key_validation_service = validation
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    profile_name = "direct-openai"
    service = _service_for(credential_name_for(account_id, profile_name))

    created = authenticated_client.put(
        f"/v1/auth/openai/profiles/{profile_name}/api-key",
        json={"api_key": _OLD_KEY},
    )

    assert created.status_code == 200, created.text
    assert created.json()["auth_type"] == "api_key"
    assert created.json()["state"] == "authenticated"
    assert _OLD_KEY not in created.text
    before = credential_blobs.read(service, "default")
    assert json.loads(before) == {"auth_type": "api_key", "api_key": _OLD_KEY}
    assert _OLD_KEY not in (credential_blobs.read_raw(service, "default") or "")

    replaced = authenticated_client.put(
        f"/v1/auth/openai/profiles/{profile_name}/api-key",
        json={"api_key": _NEW_KEY},
    )
    assert replaced.status_code == 200, replaced.text
    before = credential_blobs.read(service, "default")
    assert json.loads(before) == {"auth_type": "api_key", "api_key": _NEW_KEY}

    validation.result = ApiKeyValidationResult(
        ApiKeyValidationState.INVALID,
        stage=ApiKeyValidationStage.AUTHENTICATION,
    )
    failed = authenticated_client.put(
        f"/v1/auth/openai/profiles/{profile_name}/api-key",
        json={"api_key": _REJECTED_KEY},
    )

    assert failed.status_code == 422
    assert failed.json()["detail"]["code"] == "api_key_invalid"
    assert _REJECTED_KEY not in failed.text
    assert credential_blobs.read(service, "default") == before

    deleted = authenticated_client.delete(f"/v1/auth/openai/profiles/{profile_name}")
    assert deleted.status_code == 204
    assert credential_blobs.read(service, "default") is None
    assert validation.calls == [
        ("openai", _OLD_KEY),
        ("openai", _NEW_KEY),
        ("openai", _REJECTED_KEY),
    ]


def test_connection_create_failed_replace_and_delete_preserve_atomic_key_state(
    authenticated_client,
    credential_blobs,
) -> None:
    validation = _StubValidationService(_valid_result())
    authenticated_client.app.state.api_key_validation_service = validation

    created_response = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openai", "label": "direct-openai", "api_key": _OLD_KEY},
    )

    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["provider"] == "openai"
    assert created["auth_type"] == "api_key"
    assert created["status"] == "active"
    assert _OLD_KEY not in created_response.text
    credential_name = credential_key_for(created["account_id"], created["id"])
    service = _service_for(credential_name)
    before = credential_blobs.read(service, "default")
    assert json.loads(before) == {"auth_type": "api_key", "api_key": _OLD_KEY}
    assert _OLD_KEY not in (credential_blobs.read_raw(service, "default") or "")

    replaced = authenticated_client.put(
        f"/v1/oauth/connections/{created['id']}/api-key",
        json={"api_key": _NEW_KEY},
    )
    assert replaced.status_code == 200, replaced.text
    before = credential_blobs.read(service, "default")
    assert json.loads(before) == {"auth_type": "api_key", "api_key": _NEW_KEY}

    validation.result = ApiKeyValidationResult(
        ApiKeyValidationState.INVALID,
        stage=ApiKeyValidationStage.AUTHENTICATION,
    )
    failed = authenticated_client.put(
        f"/v1/oauth/connections/{created['id']}/api-key",
        json={"api_key": _REJECTED_KEY},
    )

    assert failed.status_code == 422
    assert failed.json()["detail"]["code"] == "api_key_invalid"
    assert _REJECTED_KEY not in failed.text
    assert credential_blobs.read(service, "default") == before

    deleted = authenticated_client.delete(f"/v1/oauth/connections/{created['id']}")
    assert deleted.status_code == 204
    assert credential_blobs.read(service, "default") is None
    assert validation.calls == [
        ("openai", _OLD_KEY),
        ("openai", _NEW_KEY),
        ("openai", _REJECTED_KEY),
    ]


def test_failed_initial_validation_writes_neither_surface(
    authenticated_client,
    monkeypatch,
) -> None:
    validation = _StubValidationService(
        ApiKeyValidationResult(
            ApiKeyValidationState.INVALID,
            stage=ApiKeyValidationStage.AUTHENTICATION,
        )
    )
    authenticated_client.app.state.api_key_validation_service = validation

    async def forbidden_write(*_args, **_kwargs) -> None:
        raise AssertionError("failed validation attempted credential persistence")

    monkeypatch.setattr(authenticated_client.app.state.credential_store, "write", forbidden_write)

    profile = authenticated_client.put(
        "/v1/auth/openai/profiles/rejected/api-key",
        json={"api_key": _REJECTED_KEY},
    )
    connection = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openai", "label": "rejected", "api_key": _REJECTED_KEY},
    )

    assert profile.status_code == 422
    assert connection.status_code == 422
    assert profile.json()["detail"]["code"] == "api_key_invalid"
    assert connection.json()["detail"]["code"] == "api_key_invalid"
    assert authenticated_client.get("/v1/auth/openai/profiles/rejected").status_code == 404
    assert authenticated_client.get("/v1/oauth/connections").json()["connections"] == []


def test_account_scoped_credential_names_do_not_collide() -> None:
    first = _service_for(credential_name_for("account-a", "default"))
    second = _service_for(credential_name_for("account-b", "default"))

    assert first != second
    assert first.startswith("aigateway:openai:")
    assert second.startswith("aigateway:openai:")


def test_chat_selects_openai_api_key_connection_by_label(authenticated_client) -> None:
    authenticated_client.app.state.api_key_validation_service = _StubValidationService(
        _valid_result()
    )
    selected = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openai", "label": "selected", "api_key": _OLD_KEY},
    )
    other = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openai", "label": "other", "api_key": _NEW_KEY},
    )
    assert selected.status_code == 201, selected.text
    assert other.status_code == 201, other.text
    plugin = authenticated_client.app.state.providers.get("openai")
    captured: dict = {}

    async def capture(body: dict):
        captured.update(body)
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-5.6-sol",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }

    # OME-884 (authorized test-isolation fix): a SCOPED ``patch.object``, never
    # ``monkeypatch.setattr``, on ``plugin`` — which IS the module-level ``PLUGIN``
    # singleton. monkeypatch reads the old value with ``getattr`` (resolving through the
    # CLASS) and restores it with ``setattr``, which permanently installs the original
    # BOUND METHOD as an INSTANCE attribute. That shadows every later class-level patch
    # of ``chat_completion``, so unrelated suites in this directory began passing or
    # failing by test ORDER. ``patch.object`` inspects ``__dict__`` and removes exactly
    # what it added.
    with patch.object(plugin, "chat_completion", new=capture):
        response = authenticated_client.post(
            "/v1/chat/completions",
            headers={"X-Profile": "selected"},
            json={
                "model": "openai/gpt-5.6-sol",
                "messages": [{"role": "user", "content": "ping"}],
            },
        )

    # INVARIANT: the shared singleton is left exactly as it was found. Without this
    # assertion the leak above is invisible from inside this file — it only ever showed
    # up as a failure somewhere else.
    assert "chat_completion" not in vars(plugin)
    assert response.status_code == 200, response.text
    assert captured["api_key"] == _OLD_KEY
    assert captured["api_base"] == "https://api.openai.com/v1"
    assert "client" not in captured
    assert response.headers["X-AIGW-Cache"] == "bypass"
    metadata = response.json()["_aigw"]
    assert metadata["usage_accounting"]["capture_status"] == "accounting_not_supported"
    assert metadata["usage_accounting"]["observed_attempts"] == 0
    assert metadata["request_economics"]["direct_cost_status"] == "not_applicable"


def test_openai_profiles_are_account_isolated(
    authenticated_client,
    provisioned_user_factory,
) -> None:
    authenticated_client.app.state.api_key_validation_service = _StubValidationService(
        _valid_result()
    )
    created = authenticated_client.put(
        "/v1/auth/openai/profiles/private/api-key",
        json={"api_key": _OLD_KEY},
    )
    assert created.status_code == 200, created.text

    provisioned_user_factory("openai-other", "other-pass1")
    login = authenticated_client.post(
        "/v1/auth/login",
        json={"username": "openai-other", "password": "other-pass1"},
    )
    authenticated_client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})

    assert authenticated_client.get("/v1/auth/openai/profiles").json() == {"profiles": []}
    assert authenticated_client.get("/v1/auth/openai/profiles/private").status_code == 404


def test_chat_selects_named_openai_profile(authenticated_client) -> None:
    authenticated_client.app.state.api_key_validation_service = _StubValidationService(
        _valid_result()
    )
    for name, key in (("first", _OLD_KEY), ("second", _NEW_KEY)):
        created = authenticated_client.put(
            f"/v1/auth/openai/profiles/{name}/api-key",
            json={"api_key": key},
        )
        assert created.status_code == 200, created.text
    plugin = authenticated_client.app.state.providers.get("openai")
    captured: dict = {}

    async def capture(body: dict):
        captured.update(body)
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-5.6-sol",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }

    # OME-884 (authorized test-isolation fix): scoped, for the reason spelled out in
    # ``test_chat_selects_openai_api_key_connection_by_label`` above.
    with patch.object(plugin, "chat_completion", new=capture):
        response = authenticated_client.post(
            "/v1/chat/completions",
            headers={"X-Profile": "second"},
            json={
                "model": "openai/gpt-5.6-sol",
                "messages": [{"role": "user", "content": "ping"}],
            },
        )

    assert "chat_completion" not in vars(plugin)
    assert response.status_code == 200, response.text
    assert captured["api_key"] == _NEW_KEY
