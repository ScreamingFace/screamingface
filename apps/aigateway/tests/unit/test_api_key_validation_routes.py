from __future__ import annotations

from dataclasses import dataclass, field

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.core.credential_strategy_cache import credential_strategy_cache

_KEY = "sk-ant-api03-synthetic-route-secret"


@dataclass
class _StubValidationService:
    result: ApiKeyValidationResult | None
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def validate(self, _plugin, provider: str, api_key: str):
        self.calls.append((provider, api_key))
        return self.result


def _install(authenticated_client, result: ApiKeyValidationResult | None) -> _StubValidationService:
    service = _StubValidationService(result)
    authenticated_client.app.state.api_key_validation_service = service
    return service


def test_validation_endpoint_returns_stable_non_persisting_result(
    authenticated_client,
    monkeypatch,
) -> None:
    service = _install(
        authenticated_client,
        ApiKeyValidationResult(
            state=ApiKeyValidationState.RATE_LIMITED,
            stage=ApiKeyValidationStage.READINESS,
            retry_after_seconds=12,
            probe_model="claude-haiku-4-5",
        ),
    )

    def forbidden_sync(*_args, **_kwargs):
        raise AssertionError("validation endpoint must not mutate local state")

    async def forbidden_async(*_args, **_kwargs):
        raise AssertionError("validation endpoint must not persist state")

    monkeypatch.setattr(authenticated_client.app.state.pending_auth, "pop_for_pair", forbidden_sync)
    monkeypatch.setattr(authenticated_client.app.state.profile_index, "upsert", forbidden_async)
    monkeypatch.setattr(authenticated_client.app.state.credential_store, "write", forbidden_async)
    monkeypatch.setattr(
        credential_strategy_cache(authenticated_client.app), "evict", forbidden_sync
    )

    response = authenticated_client.post(
        "/v1/oauth/connections/api-key/validate",
        json={"provider": "anthropic", "api_key": _KEY},
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "anthropic",
        "state": "rate_limited",
        "message": "The provider rate-limited validation. Try again later.",
        "retryable": True,
        "stage": "readiness",
        "retry_after_seconds": 12,
        "probe_model": "claude-haiku-4-5",
    }
    assert service.calls == [("anthropic", _KEY)]
    assert authenticated_client.get("/v1/oauth/connections").json()["connections"] == []


def test_validation_endpoint_rejects_short_key_without_service_call(authenticated_client) -> None:
    service = _install(authenticated_client, ApiKeyValidationResult(ApiKeyValidationState.VALID))

    response = authenticated_client.post(
        "/v1/oauth/connections/api-key/validate",
        json={"provider": "anthropic", "api_key": "short"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_api_key"
    assert service.calls == []


def test_validation_endpoint_hides_secret_on_schema_error(authenticated_client) -> None:
    response = authenticated_client.post(
        "/v1/oauth/connections/api-key/validate",
        json={"api_key": _KEY},
    )

    assert response.status_code == 422
    assert _KEY not in response.text


def test_disabled_openrouter_is_unsupported_without_network(authenticated_client) -> None:
    authenticated_client.app.state.api_key_validation_service = ApiKeyValidationService()

    response = authenticated_client.post(
        "/v1/oauth/connections/api-key/validate",
        json={"provider": "openrouter", "api_key": "sk-or-v1-synthetic"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "api_key_not_supported",
        "provider": "openrouter",
    }


def test_create_non_valid_key_returns_actionable_error_without_row(authenticated_client) -> None:
    service = _install(
        authenticated_client,
        ApiKeyValidationResult(
            state=ApiKeyValidationState.INVALID,
            stage=ApiKeyValidationStage.AUTHENTICATION,
        ),
    )

    response = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "anthropic", "label": "invalid", "api_key": _KEY},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "api_key_invalid",
        "provider": "anthropic",
        "state": "invalid",
        "message": "The provider rejected this API key. Check or replace it.",
        "retryable": False,
        "stage": "authentication",
        "retry_after_seconds": None,
        "probe_model": None,
    }
    assert service.calls == [("anthropic", _KEY)]
    assert authenticated_client.get("/v1/oauth/connections").json()["connections"] == []


def test_replace_non_valid_key_preserves_existing_connection_and_blob(
    authenticated_client,
    credential_blobs,
    monkeypatch,
) -> None:
    service = _install(
        authenticated_client,
        ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID,
            stage=ApiKeyValidationStage.READINESS,
        ),
    )
    created = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "anthropic", "label": "replace", "api_key": _KEY},
    ).json()
    locator = created["credential_locator"]
    before = credential_blobs.read(locator["service"], locator["account"])
    service.result = ApiKeyValidationResult(
        state=ApiKeyValidationState.NO_QUOTA,
        stage=ApiKeyValidationStage.READINESS,
        probe_model="claude-haiku-4-5",
    )

    def forbidden_evict(*_args, **_kwargs):
        raise AssertionError("validation failure must not evict credential cache")

    monkeypatch.setattr(
        credential_strategy_cache(authenticated_client.app),
        "evict",
        forbidden_evict,
    )

    response = authenticated_client.put(
        f"/v1/oauth/connections/{created['id']}/api-key",
        json={"api_key": "sk-ant-api03-new-secret"},
    )

    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "api_key_no_quota"
    assert credential_blobs.read(locator["service"], locator["account"]) == before
    after = authenticated_client.get(f"/v1/oauth/connections/{created['id']}").json()
    assert after == created


def test_validation_endpoint_requires_authentication(client) -> None:
    response = client.post(
        "/v1/oauth/connections/api-key/validate",
        json={"provider": "anthropic", "api_key": _KEY},
    )

    assert response.status_code == 401


def test_validation_endpoint_documents_readiness_cost(authenticated_client) -> None:
    operation = authenticated_client.get("/openapi.json").json()["paths"][
        "/v1/oauth/connections/api-key/validate"
    ]["post"]

    description = operation.get("description", "").lower()
    # INVARIANT: callers can discover that validation performs billable upstream work.
    assert "readiness" in description
    assert "quota" in description
    assert "credit" in description


def test_validation_endpoint_rejects_unknown_provider_before_service(
    authenticated_client,
) -> None:
    service = _install(
        authenticated_client,
        ApiKeyValidationResult(ApiKeyValidationState.VALID),
    )

    response = authenticated_client.post(
        "/v1/oauth/connections/api-key/validate",
        json={"provider": "unknown", "api_key": _KEY},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "unknown_provider", "provider": "unknown"}
    assert service.calls == []
