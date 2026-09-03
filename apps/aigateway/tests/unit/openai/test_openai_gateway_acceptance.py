"""Gateway-level direct OpenAI catalog and pre-credential rejection guarantees."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)

_KEY = "sk-openai-synthetic-gateway-key-1234"


@dataclass
class _ValidValidationService:
    async def validate(self, _plugin, _provider: str, _api_key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID,
            stage=ApiKeyValidationStage.READINESS,
            probe_model="openai/gpt-5-nano",
        )


def test_models_and_detail_publish_the_same_minimal_contract(authenticated_client) -> None:
    listing = authenticated_client.get("/v1/models")

    assert listing.status_code == 200, listing.text
    openai_models = [row for row in listing.json()["data"] if row["owned_by"] == "openai"]
    assert len(openai_models) == 14
    assert {row["id"] for row in openai_models} >= {
        "openai/gpt-5.6-sol",
        "openai/gpt-5.6-terra",
        "openai/gpt-5.6-luna",
        "openai/gpt-5.5",
        "openai/gpt-5-nano",
        "openai/gpt-4o",
    }
    assert all(row["supported_parameters"] == ["max_tokens"] for row in openai_models)
    assert all(row["supported_tools"] == [] for row in openai_models)

    authenticated_client.app.state.api_key_validation_service = _ValidValidationService()
    created = authenticated_client.put(
        "/v1/auth/openai/profiles/default/api-key",
        json={"api_key": _KEY},
    )
    assert created.status_code == 200, created.text

    detail = authenticated_client.get(
        "/v1/model-parameters",
        params={"model": "openai/gpt-5.6-sol", "auth_type": "api_key"},
    )

    assert detail.status_code == 200, detail.text
    parameters = detail.json()["parameters"]
    assert parameters["max_tokens"]["gateway"]["status"] == "enabled"
    # OME-884 (authorized contract change): the PUBLISHED disposition follows the rule.
    # A caller reading this contract can now rely on two identical effective requests
    # sharing one stored response, and on two different ceilings never doing so.
    assert parameters["max_tokens"]["gateway"]["cache_behavior"] == "keyed"
    assert parameters["max_tokens"]["provider"]["source"] == "openai:locked-runtime"
    assert all(
        entry["gateway"]["status"] != "enabled"
        for path, entry in parameters.items()
        if path != "max_tokens"
    )


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        # OME-884 (authorized contract change): ``openai/unregistered`` is ROUTE VALID
        # and is now forwarded to OpenAI, which is the authority on whether it exists.
        # That is proven in ``test_openai_route_global_cache.py`` by
        # ``test_a_route_valid_unsupported_model_misses_is_refused_by_openai_and_stores_nothing``
        # (cycle 2: the name here was stale and pointed at no existing test). What is
        # still refused locally, before any credential is read, is a model ID the
        # grammar rejects; that refusal is what keeps a malformed id out of the cache.
        (
            {"model": "openai/gpt 5", "messages": []},
            "invalid_model",
        ),
        (
            {"model": "openai/gpt-5.6-sol", "messages": [], "temperature": 0.1},
            "unsupported_parameters",
        ),
        (
            {"model": "openai/gpt-5.6-sol", "messages": [], "stream": True},
            "streaming_not_supported",
        ),
    ],
)
def test_rejected_request_never_reads_openai_credential(
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
    body: dict,
    expected_code: str,
) -> None:
    authenticated_client.app.state.api_key_validation_service = _ValidValidationService()
    created = authenticated_client.put(
        "/v1/auth/openai/profiles/default/api-key",
        json={"api_key": _KEY},
    )
    assert created.status_code == 200, created.text

    credential_store = authenticated_client.app.state.credential_store
    real_read = credential_store.read

    async def guarded_read(service: str, account: str) -> str | None:
        if service.startswith("aigateway:openai:"):
            raise AssertionError("rejected request read the OpenAI credential")
        return await real_read(service, account)

    monkeypatch.setattr(credential_store, "read", guarded_read)

    response = authenticated_client.post("/v1/chat/completions", json=body)

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == expected_code
