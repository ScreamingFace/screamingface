"""Phase 3 (OME-479): GET /v1/model-parameters — profile-bound detailed contract.

Exercises the real app/registry so the endpoint is proven end-to-end WITHOUT
hardcoding any provider inventory: canonical-id lookup, reuse of the existing
account/profile/auth resolution, caller-declared auth being impossible, the
private/no-store + Vary headers, deterministic revision-sensitive opaque IDs,
and non-exposure of account identity or secrets.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    AuthType,
    Profile,
    ProfileState,
    profile_id_for,
)

_MODEL = "anthropic/claude-opus-4-8"


def _account_id(client: TestClient) -> str:
    return client.get("/v1/auth/me").json()["id"]


async def _seed_profile(credential_blobs, account_id: str, *, auth_type: AuthType) -> None:
    # The detailed contract only needs the profile RECORD (auth mode + state) —
    # it never injects a credential — so no credential blob is written here.
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type=auth_type,
        )
    )


def _get(client: TestClient, model: str = _MODEL, **params: str):
    return client.get("/v1/model-parameters", params={"model": model, **params})


@pytest.mark.asyncio
async def test_returns_locked_headers_and_v1_envelope(credential_blobs, authenticated_client):
    account_id = _account_id(authenticated_client)
    await _seed_profile(credential_blobs, account_id, auth_type="api_key")

    resp = _get(authenticated_client)
    assert resp.status_code == 200, resp.text
    # Locked cache/vary headers: a profile-bound contract must never be shared.
    assert resp.headers["cache-control"] == "private, no-store"
    vary = resp.headers["vary"]
    assert "Authorization" in vary and "X-Profile" in vary

    body = resp.json()
    assert body["schema_version"] == 1
    assert body["contract_id"].startswith("pc_")
    assert body["model"]["id"] == _MODEL
    assert body["model"]["gateway_provider"] == "anthropic"
    assert body["model"]["upstream_id"] == "claude-opus-4-8"
    assert body["context"]["scope"] == "account_profile"
    assert body["context"]["auth_mode"] == "api_key"
    assert body["context"]["revision"].startswith("ctx_")
    for section in ("parameters", "tools", "transport"):
        assert isinstance(body[section], dict)


def test_unprefixed_model_is_rejected(authenticated_client):
    # A bare id with no provider segment cannot be routed to a plugin: the
    # provider is selected SOLELY by the canonical prefix, never guessed.
    resp = _get(authenticated_client, model="claude-opus-4-8")
    assert resp.status_code == 400
    assert "provider-prefixed" in resp.json()["detail"]


def test_unknown_provider_is_rejected(authenticated_client):
    # Distinct from the unprefixed case: a slash IS present, but no plugin owns
    # that prefix, so the registry lookup — not the prefix check — rejects it.
    resp = _get(authenticated_client, model="bogus/whatever")
    assert resp.status_code == 400
    assert "unknown provider" in resp.json()["detail"]


def test_unknown_model_under_known_provider_is_rejected_before_profile(authenticated_client):
    # cross-provider / non-existent id fails as model_not_found, and does so
    # BEFORE any profile resolution (no profile is seeded here).
    resp = _get(authenticated_client, model="anthropic/not-a-real-model")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "model_not_found"


def test_missing_default_profile_answers_the_keyless_datasheet(authenticated_client):
    # FEATURE: keyless parameter preflight (OME-1167). Reading the contract is a
    # datasheet lookup, not a credentialed action — with no profile and no
    # connection the DEFAULT binding answers 200 instead of chat's 404.
    # (This flips the pre-OME-1167 pin that expected profile_not_found here;
    # the flip is the ticket's mandated behavior change.)
    # INVARIANT: the published auth mode is the provider's FIRST declared mode,
    # so the binding is visible and deterministic — anthropic declares
    # ("api_key", "oauth").
    resp = _get(authenticated_client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["context"]["auth_mode"] == "api_key"
    assert body["model"]["id"] == _MODEL
    # The answer stays per-account on the wire even though its content is static.
    _assert_private_cache_policy(resp)


@pytest.mark.asyncio
async def test_keyless_answer_equals_the_credentialed_static_contract(
    credential_blobs, authenticated_client
):
    # INVARIANT (don't-regress, OME-1167): no credentialed data may leak into the
    # uncredentialed answer — and none may be MISSING from it either. The keyless
    # datasheet and an api_key-profile answer are the same static contract; only
    # the context identity (and hence the opaque ids) may differ.
    keyless = _get(authenticated_client)
    assert keyless.status_code == 200, keyless.text

    account_id = _account_id(authenticated_client)
    await _seed_profile(credential_blobs, account_id, auth_type="api_key")
    credentialed = _get(authenticated_client)
    assert credentialed.status_code == 200, credentialed.text

    keyless_body = keyless.json()
    credentialed_body = credentialed.json()
    for section in ("parameters", "tools", "transport", "model"):
        assert keyless_body[section] == credentialed_body[section]
    assert keyless_body["context"]["auth_mode"] == credentialed_body["context"]["auth_mode"]


def test_missing_default_profile_on_chat_still_404s(authenticated_client):
    # INVARIANT (don't-regress, OME-1167): only the datasheet went keyless —
    # dispatch still refuses an account with no stored credential target.
    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "profile_not_found"


@pytest.mark.asyncio
async def test_auth_mode_is_derived_from_profile_not_caller_declared(
    credential_blobs, authenticated_client
):
    account_id = _account_id(authenticated_client)
    await _seed_profile(credential_blobs, account_id, auth_type="oauth")

    # A caller-supplied auth_type query param must be ignored entirely.
    resp = _get(authenticated_client, auth_type="api_key")
    assert resp.status_code == 200, resp.text
    assert resp.json()["context"]["auth_mode"] == "oauth"


@pytest.mark.asyncio
async def test_contract_id_is_deterministic_and_changes_with_auth_mode(
    credential_blobs, authenticated_client
):
    account_id = _account_id(authenticated_client)

    await _seed_profile(credential_blobs, account_id, auth_type="api_key")
    first = _get(authenticated_client).json()["contract_id"]
    again = _get(authenticated_client).json()["contract_id"]
    assert first == again  # deterministic for identical context

    await _seed_profile(credential_blobs, account_id, auth_type="oauth")  # re-key same profile
    after = _get(authenticated_client).json()["contract_id"]
    assert after != first  # auth-mode change is a relevant revision change


@pytest.mark.asyncio
async def test_response_never_exposes_account_id_or_secrets(credential_blobs, authenticated_client):
    account_id = _account_id(authenticated_client)
    await _seed_profile(credential_blobs, account_id, auth_type="api_key")

    resp = _get(authenticated_client)
    assert resp.status_code == 200, resp.text
    # opaque IDs are one-way: the account id (a digest input) never appears raw.
    assert account_id not in resp.text


# --- private cache policy on ERROR exits (OME-598) ---------------------------
#
# INVARIANT: the private cache policy is a property of the ROUTE, not of its happy
# path. Every response it produces — success or error — must be marked
# unshareable, because the error bodies are the ones carrying caller-identifying
# data (the requested profile name and a profile-specific reauth URL).
#
# WHY these need their own tests: in FastAPI the injected ``Response`` reaches the
# wire only on a normal return; a raised HTTPException is rendered from the
# EXCEPTION's headers instead. A policy set on the injected response is therefore
# structurally invisible to every raise, and no success-path assertion can catch it.


async def _seed_profile_record(
    credential_blobs,
    account_id: str,
    *,
    name: str,
    state: ProfileState,
    auth_type: AuthType = "api_key",
) -> None:
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


def _get_as_profile(client: TestClient, profile: str, model: str = _MODEL):
    return client.get(
        "/v1/model-parameters", params={"model": model}, headers={"X-Profile": profile}
    )


def _assert_private_cache_policy(resp) -> None:
    assert resp.headers.get("cache-control") == "private, no-store", resp.headers
    vary = resp.headers.get("vary") or ""
    assert "Authorization" in vary and "X-Profile" in vary, resp.headers


def test_unknown_provider_error_carries_private_cache_policy(authenticated_client):
    resp = _get(authenticated_client, model="bogus/whatever")
    assert resp.status_code == 400
    _assert_private_cache_policy(resp)


def test_unprefixed_model_error_carries_private_cache_policy(authenticated_client):
    resp = _get(authenticated_client, model="claude-opus-4-8")
    assert resp.status_code == 400
    _assert_private_cache_policy(resp)


def test_model_not_found_error_carries_private_cache_policy(authenticated_client):
    resp = _get(authenticated_client, model="anthropic/not-a-real-model")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "model_not_found"
    _assert_private_cache_policy(resp)


def test_profile_not_found_error_carries_private_cache_policy(authenticated_client):
    # Profile-dependent 404: the body echoes the requested profile name.
    resp = _get_as_profile(authenticated_client, "no-such-profile")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["code"] == "profile_not_found"
    assert detail["name"] == "no-such-profile"
    _assert_private_cache_policy(resp)


@pytest.mark.asyncio
async def test_pending_profile_conflict_carries_private_cache_policy(
    credential_blobs, authenticated_client
):
    # A DISTINCT X-Profile value (not "default") proves the policy is not tied to
    # the default-profile path, and that Vary: X-Profile is truthful on errors.
    account_id = _account_id(authenticated_client)
    await _seed_profile_record(
        credential_blobs, account_id, name="staging", state=ProfileState.PENDING
    )

    resp = _get_as_profile(authenticated_client, "staging")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "profile_pending_auth"
    assert detail["name"] == "staging"
    _assert_private_cache_policy(resp)


@pytest.mark.asyncio
async def test_auth_required_error_keeps_reauth_url_and_private_cache_policy(
    credential_blobs, authenticated_client
):
    # The most sensitive error body: it carries a profile-specific reauth URL.
    # The boundary must ADD headers without disturbing the detail payload.
    account_id = _account_id(authenticated_client)
    await _seed_profile_record(
        credential_blobs, account_id, name="broken", state=ProfileState.ERROR
    )

    resp = _get_as_profile(authenticated_client, "broken")
    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail["code"] == "auth_required"
    assert detail["reauth_url"] == "/v1/auth/anthropic/profiles/broken"
    _assert_private_cache_policy(resp)


def test_boundary_preserves_raiser_headers_but_wins_on_the_cache_policy(
    authenticated_client, monkeypatch
):
    # INVARIANT (the merge direction): a raising helper keeps its own headers, but
    # this route's cache policy is authoritative on the keys it owns — fail closed,
    # so no future raise can emit the contract with a weaker cache directive.
    # No raiser sets headers today, so the semantics are pinned with a synthetic one.
    from fastapi import HTTPException

    from aigateway.routes import model_parameters as route_mod

    async def _raise_with_headers(*_args, **_kwargs):
        raise HTTPException(
            status_code=503,
            detail={"code": "synthetic"},
            headers={"Retry-After": "5", "Cache-Control": "public, max-age=600"},
        )

    monkeypatch.setattr(route_mod, "_contract_document", _raise_with_headers)

    resp = _get(authenticated_client)
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "5"  # raiser's own header survives
    _assert_private_cache_policy(resp)  # ...but the weaker directive is overridden
