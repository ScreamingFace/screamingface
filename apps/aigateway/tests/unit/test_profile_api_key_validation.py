from __future__ import annotations

import json
from dataclasses import dataclass

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.profile_models import credential_name_for
from aigateway.plugins.anthropic_provider.auth import credential_service_for

_OLD_KEY = "sk-ant-api03-existing-profile-secret"
_NEW_KEY = "sk-ant-api03-rejected-profile-secret"


@dataclass
class _StubValidationService:
    result: ApiKeyValidationResult

    async def validate(self, _plugin, _provider: str, _api_key: str):
        return self.result


def test_profile_validation_failure_precedes_every_side_effect(
    authenticated_client,
    credential_blobs,
    monkeypatch,
) -> None:
    service = _StubValidationService(
        ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID,
            stage=ApiKeyValidationStage.READINESS,
        )
    )
    authenticated_client.app.state.api_key_validation_service = service
    created = authenticated_client.put(
        "/v1/auth/anthropic/profiles/work/api-key",
        json={"api_key": _OLD_KEY},
    )
    assert created.status_code == 200
    before_profile = created.json()
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    credential_service = credential_service_for(credential_name_for(account_id, "work"))
    before_blob = credential_blobs.read(credential_service, "default")
    assert json.loads(before_blob)["api_key"] == _OLD_KEY

    service.result = ApiKeyValidationResult(
        state=ApiKeyValidationState.INVALID,
        stage=ApiKeyValidationStage.AUTHENTICATION,
    )

    def forbidden_pending_call(*_args, **_kwargs):
        raise AssertionError("pending OAuth state must not be touched")

    async def forbidden_upsert(*_args, **_kwargs):
        raise AssertionError("profile index must not be touched")

    async def forbidden_write(*_args, **_kwargs):
        raise AssertionError("credential blob must not be touched")

    monkeypatch.setattr(
        authenticated_client.app.state.pending_auth,
        "pop_for_profile",
        forbidden_pending_call,
    )
    monkeypatch.setattr(authenticated_client.app.state.profile_index, "upsert", forbidden_upsert)
    monkeypatch.setattr(authenticated_client.app.state.credential_store, "write", forbidden_write)
    plugin = authenticated_client.app.state.providers.get("anthropic")
    monkeypatch.setattr(plugin, "invalidate_profile_session", forbidden_pending_call)

    response = authenticated_client.put(
        "/v1/auth/anthropic/profiles/work/api-key",
        json={"api_key": _NEW_KEY},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "api_key_invalid"
    assert _NEW_KEY not in response.text
    assert authenticated_client.get("/v1/auth/anthropic/profiles/work").json() == before_profile
    assert credential_blobs.read(credential_service, "default") == before_blob
