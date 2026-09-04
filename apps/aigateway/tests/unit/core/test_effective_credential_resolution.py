"""OME-1026 U1 — ONE effective provider credential, resolved implicitly.

FEATURE: the confirmed product contract has one implicit credential per provider.
``sf.models.list()`` sends no ``X-Profile``, so AIGateway resolves each provider's
effective credential automatically: hosted mode through the provider's ``default``
Profile, local mode through the sole active Connection — exactly the policy chat
already applies. This module pins that policy as ONE shared resolver so listing,
model parameters and chat cannot drift apart.

STORY: as a Python Client user with one stored Anthropic key, I call
``sf.models.list()`` and the gateway uses my key — without me naming a profile,
in hosted and local deployments alike.

INVARIANT: with more than one active local Connection the resolver NEVER picks
one arbitrarily — the credential is ambiguous and no discovery may be funded by a
guess. Zero candidates resolve to no credential at all.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.core.effective_credential import (
    AmbiguousCredential,
    EffectiveCredential,
    UnknownConnectionLabel,
    resolve_effective_credential,
)
from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.profile_models import (
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.routes.chat_credentials import _credential_target_for_chat


def _accept_any_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


def _portal(client: TestClient):
    portal = client.portal
    assert portal is not None, "the TestClient must be entered as a context manager"
    return portal


def _detail(exc: HTTPException) -> dict:
    assert isinstance(exc.detail, dict), exc.detail
    return exc.detail


def _quiet_discovery(client: TestClient) -> None:
    """Resolution is the subject here — no test in this module may fund a dial."""
    app = cast(FastAPI, client.app)
    app.state.profile_model_catalog = None


def _account_id(client: TestClient) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _resolve(
    client: TestClient,
    *,
    provider: str = "anthropic",
    profile_name: str = "default",
    account_id: str | None = None,
) -> Any:
    app = cast(FastAPI, client.app)
    resolved_account = _account_id(client) if account_id is None else account_id

    async def _run() -> Any:
        return await resolve_effective_credential(
            account_id=resolved_account,
            provider=provider,
            profile_name=profile_name,
            profile_index=app.state.profile_index,
            connections=OAuthConnectionStore(),
        )

    return _portal(client).call(_run)


def _store_profile_key(client: TestClient, name: str, api_key: str) -> None:
    response = client.put(f"/v1/auth/anthropic/profiles/{name}/api-key", json={"api_key": api_key})
    assert response.status_code == 200, response.text


def _create_connection(client: TestClient, label: str, api_key: str) -> str:
    response = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "anthropic", "label": label, "api_key": api_key},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _put_profile(client: TestClient, *, state: ProfileState, name: str = "default") -> None:
    app = cast(FastAPI, client.app)
    account_id = _account_id(client)
    profile = Profile(
        id=profile_id_for(account_id, "anthropic", name),
        account_id=account_id,
        provider="anthropic",
        name=name,
        state=state,
        auth_type="api_key",
    )
    _portal(client).call(app.state.profile_index.upsert, profile)


def _chat_target(client: TestClient, *, profile_name: str = "default") -> Any:
    app = cast(FastAPI, client.app)
    plugin = app.state.providers.get("anthropic")
    request = cast(Any, SimpleNamespace(app=app))
    account_id = _account_id(client)

    async def _run() -> Any:
        return await _credential_target_for_chat(
            request,
            account_id=account_id,
            provider="anthropic",
            profile_name=profile_name,
            plugin=plugin,
        )

    return _portal(client).call(_run)


# ── hosted: the provider's ``default`` Profile ─────────────────────────────────


def test_hosted_default_profile_is_the_effective_credential(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    _store_profile_key(authenticated_client, "default", "sk-ant-hosted")
    account_id = _account_id(authenticated_client)

    resolution = _resolve(authenticated_client)

    assert isinstance(resolution, EffectiveCredential)
    assert resolution.profile is not None and resolution.connection is None
    assert resolution.provider == "anthropic"
    assert resolution.account_id == account_id
    assert resolution.profile_name == "default"
    assert resolution.auth_type == "api_key"
    assert resolution.authenticated is True
    assert resolution.credential_name == credential_name_for(account_id, "default")
    # Non-secret cache identity: the durable profile revision, never key material.
    assert resolution.credential_revision
    assert "sk-ant" not in resolution.credential_revision


def test_a_pending_profile_resolves_unauthenticated_and_chat_says_409(
    authenticated_client: TestClient,
) -> None:
    _quiet_discovery(authenticated_client)
    _put_profile(authenticated_client, state=ProfileState.PENDING)

    resolution = _resolve(authenticated_client)
    assert isinstance(resolution, EffectiveCredential)
    assert resolution.authenticated is False

    with pytest.raises(HTTPException) as excinfo:
        _chat_target(authenticated_client)
    assert excinfo.value.status_code == 409
    assert _detail(excinfo.value)["code"] == "profile_pending_auth"


def test_an_errored_profile_resolves_unauthenticated_and_chat_says_401(
    authenticated_client: TestClient,
) -> None:
    _quiet_discovery(authenticated_client)
    _put_profile(authenticated_client, state=ProfileState.ERROR)

    resolution = _resolve(authenticated_client)
    assert isinstance(resolution, EffectiveCredential)
    assert resolution.authenticated is False

    with pytest.raises(HTTPException) as excinfo:
        _chat_target(authenticated_client)
    assert excinfo.value.status_code == 401
    assert _detail(excinfo.value)["code"] == "auth_required"


# ── local: the sole active Connection is the implicit default ──────────────────


def test_local_sole_active_connection_is_the_implicit_default(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The label does NOT matter: one active connection IS the default credential."""
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    connection_id = _create_connection(authenticated_client, "personal", "sk-ant-local")
    account_id = _account_id(authenticated_client)

    resolution = _resolve(authenticated_client)

    assert isinstance(resolution, EffectiveCredential)
    assert resolution.connection is not None and resolution.profile is None
    assert str(resolution.connection.id) == connection_id
    assert resolution.profile_name == "default"
    assert resolution.auth_type == "api_key"
    assert resolution.authenticated is True
    assert resolution.defaults == ProfileDefaults()
    assert resolution.credential_name == credential_key_for(account_id, connection_id)
    assert resolution.credential_revision
    assert "sk-ant" not in resolution.credential_revision


def test_profile_and_connection_backed_revisions_never_alias(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One identity triple may hold both backings over time; their revisions differ.

    # INVARIANT: the snapshot store is keyed by (identity, revision), so equal
    # revision strings for a Profile and a Connection would let one backing read the
    # other's private rows after a hosted/local representation switch.
    """
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    _create_connection(authenticated_client, "personal", "sk-ant-local")
    connection_backed = _resolve(authenticated_client)

    _store_profile_key(authenticated_client, "default", "sk-ant-hosted")
    profile_backed = _resolve(authenticated_client)

    assert isinstance(connection_backed, EffectiveCredential)
    assert isinstance(profile_backed, EffectiveCredential)
    assert profile_backed.profile is not None
    assert connection_backed.connection is not None
    assert profile_backed.credential_revision != connection_backed.credential_revision


def test_no_profile_and_no_connection_is_no_credential(
    authenticated_client: TestClient,
) -> None:
    _quiet_discovery(authenticated_client)

    assert _resolve(authenticated_client) is None


def test_two_active_connections_are_never_chosen_arbitrarily(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    _create_connection(authenticated_client, "work", "sk-ant-one")
    _create_connection(authenticated_client, "personal", "sk-ant-two")

    resolution = _resolve(authenticated_client)

    assert isinstance(resolution, AmbiguousCredential)
    assert sorted(resolution.valid_labels) == ["personal", "work"]

    with pytest.raises(HTTPException) as excinfo:
        _chat_target(authenticated_client)
    assert excinfo.value.status_code == 409
    assert _detail(excinfo.value)["code"] == "connection_ambiguous"


def test_a_default_label_never_bypasses_implicit_connection_ambiguity(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: ``default`` is not a tie-breaker for an implicit request."""
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    _create_connection(authenticated_client, "default", "sk-ant-one")
    _create_connection(authenticated_client, "other", "sk-ant-two")

    resolution = _resolve(authenticated_client)

    assert isinstance(resolution, AmbiguousCredential)
    assert sorted(resolution.valid_labels) == ["default", "other"]
    with pytest.raises(HTTPException) as excinfo:
        _chat_target(authenticated_client)
    assert excinfo.value.status_code == 409
    assert _detail(excinfo.value)["code"] == "connection_ambiguous"


def test_an_explicit_label_still_selects_its_connection(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chat's existing label selection survives the shared resolver unchanged."""
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    _create_connection(authenticated_client, "work", "sk-ant-one")
    wanted = _create_connection(authenticated_client, "personal", "sk-ant-two")

    resolution = _resolve(authenticated_client, profile_name="personal")

    assert isinstance(resolution, EffectiveCredential)
    assert resolution.connection is not None
    assert str(resolution.connection.id) == wanted


def test_an_unknown_label_reports_the_valid_labels(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    _create_connection(authenticated_client, "work", "sk-ant-one")

    resolution = _resolve(authenticated_client, profile_name="nope")

    assert isinstance(resolution, UnknownConnectionLabel)
    assert resolution.requested_label == "nope"
    assert resolution.valid_labels == ("work",)

    with pytest.raises(HTTPException) as excinfo:
        _chat_target(authenticated_client, profile_name="nope")
    assert excinfo.value.status_code == 404
    assert _detail(excinfo.value)["code"] == "connection_not_found"


def test_inactive_connections_never_resolve(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deleted (revoked) connection stops being the effective credential at once."""
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    connection_id = _create_connection(authenticated_client, "personal", "sk-ant-local")
    deleted = authenticated_client.delete(f"/v1/oauth/connections/{connection_id}")
    assert deleted.status_code == 204, deleted.text

    assert _resolve(authenticated_client) is None


# ── one target, three consumers ────────────────────────────────────────────────


def test_chat_observes_the_same_hosted_target_as_the_resolver(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    _store_profile_key(authenticated_client, "default", "sk-ant-hosted")

    resolution = _resolve(authenticated_client)
    profile, connection, defaults = _chat_target(authenticated_client)

    assert isinstance(resolution, EffectiveCredential)
    assert connection is None and profile is not None
    assert resolution.profile is not None
    assert profile.id == resolution.profile.id
    assert defaults == resolution.defaults


def test_chat_observes_the_same_local_target_as_the_resolver(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    _create_connection(authenticated_client, "personal", "sk-ant-local")

    resolution = _resolve(authenticated_client)
    profile, connection, defaults = _chat_target(authenticated_client)

    assert isinstance(resolution, EffectiveCredential)
    assert profile is None and connection is not None
    assert resolution.connection is not None
    assert connection.id == resolution.connection.id
    assert defaults == ProfileDefaults() == resolution.defaults


def test_a_credential_free_provider_resolves_to_no_credential(
    authenticated_client: TestClient,
) -> None:
    """Providers with auth mode ``none`` keep their credential-free behavior: the
    resolver reports no credential and chat's existing chatless allowance decides."""
    _quiet_discovery(authenticated_client)

    assert _resolve(authenticated_client, provider="ollama") is None
