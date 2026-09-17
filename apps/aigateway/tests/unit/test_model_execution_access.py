"""OME-1195: discovery distinguishes configured access from keyless datasheets."""

from unittest.mock import AsyncMock, Mock

import pytest

from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import AuthType, Profile, ProfileState, profile_id_for

_MODEL = "anthropic/claude-opus-4-8"
_GEMINI = "gemini-cli/gemini-2.5-flash"


@pytest.fixture(autouse=True)
def no_execution(authenticated_client, monkeypatch):
    # INVARIANT: discovery must never inject/refresh credentials or run inference.
    import litellm

    from aigateway.core.provider_access import ProfileBackedProviderAccess

    # WHY: public schema discovery is independent of access configuration.
    monkeypatch.setattr(authenticated_client.app.state, "discovery_runtime", None)
    # OME-1207: the tripwire moved to the PORT's authorize (op 4) — the one operation that
    # can hand a credential to a request. The datasheet route resolves a target and reads its
    # auth mode; it must never take the next step.
    inject = AsyncMock(side_effect=AssertionError("discovery injected credentials"))
    monkeypatch.setattr(ProfileBackedProviderAccess, "authorize", inject)
    monkeypatch.setattr(
        litellm, "acompletion", AsyncMock(side_effect=AssertionError("discovery ran inference"))
    )
    yield
    inject.assert_not_called()


def _details(client, model=_MODEL, *, profile=None):
    return client.get(
        "/v1/model-parameters",
        params={"model": model},
        headers={"X-Profile": profile} if profile else {},
    )


def _assert_access(response, expected):
    assert response.status_code == 200, response.text
    assert response.json()["context"]["execution_access"] == expected
    assert response.headers["cache-control"] == "private, no-store"
    assert "X-Profile" in response.headers["vary"]
    assert "Authorization" in response.headers["vary"]


def test_missing_access_still_returns_datasheet(authenticated_client):
    response = _details(authenticated_client)
    _assert_access(response, "missing")
    assert response.json()["parameters"]


@pytest.mark.parametrize("env_name", ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
def test_profileless_environment_access_is_live_and_secret_free(
    authenticated_client, monkeypatch, env_name
):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    _assert_access(_details(authenticated_client, _GEMINI), "missing")
    monkeypatch.setenv(env_name, "private-provider-secret")
    configured = _details(authenticated_client, _GEMINI)
    _assert_access(configured, "configured")
    assert "private-provider-secret" not in configured.text
    monkeypatch.delenv(env_name)
    _assert_access(_details(authenticated_client, _GEMINI), "missing")


async def _profile(
    credential_blobs,
    account_id,
    *,
    name="default",
    auth_type: AuthType = "api_key",
    state=ProfileState.AUTHENTICATED,
):
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", name),
            account_id=account_id,
            provider="anthropic",
            name=name,
            state=state,
            auth_type=auth_type,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_type", ["api_key", "oauth"])
async def test_stored_target_is_configured_without_credential_validation(
    authenticated_client, credential_blobs, auth_type
):
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    await _profile(credential_blobs, account_id, name="chosen", auth_type=auth_type)
    # WHY: a profile record is configuration, not proof that its secret is valid.
    response = _details(authenticated_client, profile="chosen")
    _assert_access(response, "configured")
    assert account_id not in response.text
    _assert_access(_details(authenticated_client), "missing")


@pytest.mark.asyncio
async def test_other_account_profile_does_not_grant_access(authenticated_client, credential_blobs):
    await _profile(credential_blobs, "different-account")
    _assert_access(_details(authenticated_client), "missing")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "status", "code"),
    [
        (ProfileState.PENDING, 409, "profile_pending_auth"),
        (ProfileState.ERROR, 401, "auth_required"),
    ],
)
async def test_profile_failures_remain_typed(
    authenticated_client, credential_blobs, state, status, code
):
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    await _profile(credential_blobs, account_id, state=state)
    response = _details(authenticated_client)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert response.headers["cache-control"] == "private, no-store"


def test_named_missing_profile_remains_error(authenticated_client):
    response = _details(authenticated_client, profile="absent")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "profile_not_found"


def test_no_auth_provider_is_configured(authenticated_client, monkeypatch):
    from aigateway.core.plugin_base import ModelEntry
    from aigateway.plugins.ollama_provider.plugin import OllamaProviderPlugin

    monkeypatch.setattr(
        OllamaProviderPlugin,
        "register_models",
        Mock(return_value=[ModelEntry(model_name="ollama/test", litellm_params={})]),
    )
    _assert_access(_details(authenticated_client, "ollama/test"), "configured")


def test_active_connection_and_ambiguous_selection(authenticated_client):
    from functools import partial
    from uuid import uuid4

    from aigateway.core.oauth.store import OAuthConnectionStore

    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    # WHY: keep connection setup on the app loop so teardown closes its DB worker.
    store = OAuthConnectionStore()
    authenticated_client.portal.call(
        partial(
            store.create_api_key,
            account_id=account_id,
            provider="anthropic",
            label="one",
            connection_id=uuid4(),
        )
    )
    # INVARIANT: chat's single-connection default fallback also grants discovery access.
    _assert_access(_details(authenticated_client), "configured")
    authenticated_client.portal.call(
        partial(
            store.create_api_key,
            account_id=account_id,
            provider="anthropic",
            label="two",
            connection_id=uuid4(),
        )
    )
    response = _details(authenticated_client)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "connection_ambiguous"
    _assert_access(_details(authenticated_client, profile="two"), "configured")
    response = _details(authenticated_client, profile="absent")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "connection_not_found"


@pytest.mark.parametrize("env_name", ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
def test_access_only_changes_preserve_parameter_contract_identity(
    authenticated_client, monkeypatch, env_name
):
    from aigateway.core.provider_access import profile_backed

    # WHY: real Gemini key changes can also select a different auth mode. Hold
    # that independent digest input fixed to isolate the access-only contract.
    # OME-1207: pinned at the port's op 3 (`contract_auth_mode`), where the route now reads it.
    monkeypatch.setattr(profile_backed, "contract_auth_mode", Mock(return_value="api_key"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    missing = _details(authenticated_client, _GEMINI)
    _assert_access(missing, "missing")
    before = missing.json()

    monkeypatch.setenv(env_name, "private-provider-secret")
    configured = _details(authenticated_client, _GEMINI)
    _assert_access(configured, "configured")
    monkeypatch.delenv(env_name)
    missing_again = _details(authenticated_client, _GEMINI)
    _assert_access(missing_again, "missing")

    for response in (configured, missing_again):
        after = response.json()
        assert after["context"]["auth_mode"] == before["context"]["auth_mode"] == "api_key"
        assert after["parameters"] == before["parameters"]
        assert after["contract_id"] == before["contract_id"]
        assert after["context"]["revision"] == before["context"]["revision"]
