from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

_UNIT_ROOT = Path(__file__).resolve().parent
# AIDEV-NOTE: keep new API-key validation tests in new modules outside this frozen allowlist
# so they exercise the real validation service unless they install an explicit test double.
_LEGACY_API_KEY_ROUTE_MODULES = frozenset(
    {
        "test_api_key_routes.py",
        "test_auth_routes.py",
        "test_oauth_connection_api_key_routes.py",
        "huggingface/test_huggingface_gateway_acceptance.py",
        "openrouter/test_chat_debug_control_strip.py",
        "openrouter/test_chat_exception_boundary.py",
        "openrouter/test_openrouter_benign_error.py",
        "openrouter/test_openrouter_control_plane_isolation.py",
        "openrouter/test_openrouter_dispatch.py",
        "openrouter/test_openrouter_embedded_retry.py",
        "openrouter/test_openrouter_embedded_retry_conversion.py",
        "openrouter/test_openrouter_error_policy.py",
        "openrouter/test_openrouter_litellm_contract.py",
        "openrouter/test_openrouter_security.py",
        "openrouter/test_openrouter_toplevel_conversion_retry.py",
    }
)

_EXPLICIT_API_KEY_VALIDATION_TESTS = frozenset(
    {
        "test_openrouter_insufficient_credits_recovers_after_real_success",
        "test_openrouter_auth_rejection_projects_needs_reauth_without_lifecycle_error",
        "test_openrouter_outcome_persistence_failure_preserves_the_provider_response",
        "test_unclassified_openrouter_401_falls_back_to_legacy_connection_handling",
    }
)


@pytest.fixture(autouse=True)
def _legacy_api_key_validation_success(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative_path = Path(request.node.path).resolve().relative_to(_UNIT_ROOT).as_posix()
    if (
        relative_path not in _LEGACY_API_KEY_ROUTE_MODULES
        or request.node.name in _EXPLICIT_API_KEY_VALIDATION_TESTS
    ):
        return

    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(
        _self: ApiKeyValidationService,
        _plugin: Any,
        _provider: str,
        _api_key: str,
    ) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID,
            stage=ApiKeyValidationStage.READINESS,
        )

    # INVARIANT: only frozen pre-OME-307 modules receive this compatibility success.
    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


@pytest.fixture(scope="session")
def accounting_schema() -> dict[str, Any]:
    """The packaged Engine handoff schema (``usage_accounting.schema.json``), loaded once."""
    import json
    from importlib.resources import files

    resource = files("aigateway.plugins.taxonomy").joinpath("usage_accounting.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


@pytest.fixture
def valid_api_key_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt a module outside the frozen legacy allowlist in to a VALID readiness result.

    For tests whose subject is not key validation. Request it explicitly (or wrap it in a
    module-level autouse fixture); it is never applied implicitly.
    """
    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(_self: Any, _plugin: Any, _provider: str, _api_key: str):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


@pytest.fixture
def cache_chat_client(monkeypatch: pytest.MonkeyPatch, client: Any) -> Any:
    """An admin-authenticated client with OpenRouter enabled and the request cache on."""
    from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
    from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    response = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client
