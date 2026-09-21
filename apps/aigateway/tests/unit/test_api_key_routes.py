"""Route tests for the profile API-key path (SF-244).

Mirrors the OAuth route tests: authenticated_client + the credential_blobs
probe (which decrypts through the same master key as the app's ORMStore).
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import httpx
import pytest

import aigateway.core.provider_access.profile_admin as profile_admin_module
from aigateway.core.credential_blob.store import CredentialBlobMutationConflict
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    Profile,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.plugins.gemini_provider.auth import (
    credential_service_for as gemini_credential_service_for,
)

ANTHROPIC_KEY = "sk-ant-api03-test-key-1234"


@contextmanager
def _server_errors_as_responses(client) -> Iterator[None]:
    transport = getattr(client, "_transport")
    previous = transport.raise_server_exceptions
    transport.raise_server_exceptions = False
    try:
        yield
    finally:
        transport.raise_server_exceptions = previous


def _oauth_token_factory():
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(
            200,
            json={
                "access_token": "oauth-tok",
                "refresh_token": "oauth-rt",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
    )
    return lambda: httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _put_api_key(client, provider: str, name: str, api_key: str, **extra):
    return client.put(
        f"/v1/auth/{provider}/profiles/{name}/api-key",
        json={"api_key": api_key, **extra},
    )


def test_set_api_key_creates_authenticated_profile(authenticated_client, credential_blobs) -> None:
    account_id = _account_id(authenticated_client)

    resp = _put_api_key(authenticated_client, "anthropic", "keyed", ANTHROPIC_KEY)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "authenticated"
    assert body["auth_type"] == "api_key"
    assert body["account_label"].endswith("1234")
    # The raw key is never echoed back.
    assert ANTHROPIC_KEY not in resp.text

    service = credential_service_for(credential_name_for(account_id, "keyed"))
    blob = credential_blobs.read(service, "default")
    assert blob is not None
    assert json.loads(blob) == {"auth_type": "api_key", "api_key": ANTHROPIC_KEY}

    status = authenticated_client.get("/v1/auth/anthropic/profiles/keyed/status")
    assert status.status_code == 200
    assert status.json()["state"] == "authenticated"
    assert status.json()["auth_type"] == "api_key"


def test_set_api_key_replaces_existing_key(authenticated_client, credential_blobs) -> None:
    account_id = _account_id(authenticated_client)
    assert (
        _put_api_key(authenticated_client, "anthropic", "keyed", ANTHROPIC_KEY).status_code == 200
    )

    resp = _put_api_key(authenticated_client, "anthropic", "keyed", "sk-ant-api03-rotated-9999")

    assert resp.status_code == 200
    assert resp.json()["account_label"].endswith("9999")
    service = credential_service_for(credential_name_for(account_id, "keyed"))
    assert json.loads(credential_blobs.read(service, "default"))["api_key"] == (
        "sk-ant-api03-rotated-9999"
    )


def test_set_api_key_deletes_new_blob_when_profile_index_update_fails(
    authenticated_client, credential_blobs, monkeypatch
) -> None:
    account_id = _account_id(authenticated_client)
    service = credential_service_for(credential_name_for(account_id, "keyed"))

    async def _boom(_profile) -> None:
        raise RuntimeError("profile index unavailable")

    monkeypatch.setattr(authenticated_client.app.state.profile_index, "upsert", _boom)

    with _server_errors_as_responses(authenticated_client):
        resp = _put_api_key(authenticated_client, "anthropic", "keyed", ANTHROPIC_KEY)

    assert resp.status_code == 500
    assert credential_blobs.read(service, "default") is None
    assert authenticated_client.get("/v1/auth/anthropic/profiles/keyed").status_code == 404


def test_set_api_key_profile_index_conflict_returns_retryable_503(
    authenticated_client, credential_blobs, monkeypatch
) -> None:
    account_id = _account_id(authenticated_client)
    service = credential_service_for(credential_name_for(account_id, "keyed"))

    async def _boom(_profile) -> None:
        raise CredentialBlobMutationConflict("forced contention")

    monkeypatch.setattr(authenticated_client.app.state.profile_index, "upsert", _boom)

    with _server_errors_as_responses(authenticated_client):
        resp = _put_api_key(authenticated_client, "anthropic", "keyed", ANTHROPIC_KEY)

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "profile_index_conflict"
    assert "forced contention" not in resp.text
    assert credential_blobs.read(service, "default") is None


@pytest.mark.asyncio
async def test_set_api_key_restores_oauth_blob_when_profile_index_update_fails(
    authenticated_client, credential_blobs, monkeypatch
) -> None:
    account_id = _account_id(authenticated_client)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="oauth",
            account_label="user@example.com",
            scopes=["user:inference"],
        )
    )
    service = credential_service_for(credential_name_for(account_id, "default"))
    previous = json.dumps(
        {
            "access_token": "oauth-tok",
            "refresh_token": "oauth-rt",
            "expires_at_ms": 1,
            "token_type": "Bearer",
        }
    )
    credential_blobs.write(service, "default", previous)

    # Faithful double of ProfileIndexStore.upsert: the observed-existing update path passes
    # require_present=True (OME-307 Unit 3), so the stub tolerates that keyword.
    async def _boom(_profile, **_kwargs) -> None:
        raise RuntimeError("profile index unavailable")

    monkeypatch.setattr(authenticated_client.app.state.profile_index, "upsert", _boom)

    with _server_errors_as_responses(authenticated_client):
        resp = _put_api_key(authenticated_client, "anthropic", "default", ANTHROPIC_KEY)

    assert resp.status_code == 500
    assert credential_blobs.read(service, "default") == previous
    profile = await idx.get(account_id, "anthropic", "default")
    assert profile is not None
    assert profile.auth_type == "oauth"


@pytest.mark.asyncio
async def test_set_api_key_failure_preserves_concurrent_slot_write_via_rollback(
    authenticated_client, credential_blobs, monkeypatch
) -> None:
    """OME-307 Blocker 4: transaction rollback is the SOLE atomicity mechanism for a failed
    API-key publication. There is deliberately NO post-rollback credential compensation — a
    second, out-of-transaction mutate would be redundant with rollback AND could clobber a
    concurrent task that legitimately owns the same slot (an ABA defect). Replaces the retired
    compensation-sanitization tests: a value a CONCURRENT owner committed to the shared slot
    must survive the failed publication untouched, and no compensating mutate may run.

    STORY: as an operator whose key rotation on a profile fails mid-publish, a teammate's
    concurrent, successful write to the same slot is never silently reverted by my failure.
    """
    account_id = _account_id(authenticated_client)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )
    service = credential_service_for(credential_name_for(account_id, "default"))
    # The value a concurrent owner committed to the shared slot; it must NOT be clobbered.
    concurrent_owned = json.dumps(
        {"auth_type": "api_key", "api_key": "sk-ant-api03-concurrent-owner-9999"}
    )
    credential_blobs.write(service, "default", concurrent_owned)

    # Faithful double of ProfileIndexStore.upsert: the observed-existing update path passes
    # require_present=True (OME-307 Unit 3), so the stub tolerates that keyword.
    async def _boom(_profile, **_kwargs) -> None:
        raise RuntimeError("profile index unavailable")

    # INVARIANT: a failed publication performs NO out-of-transaction credential mutate. The spy
    # records every call, so a reintroduced post-rollback compensation would fail this test.
    mutate_calls: list[tuple[str, str]] = []
    real_mutate = authenticated_client.app.state.credential_store.mutate

    async def _spy_mutate(svc: str, acct: str, mutator) -> None:
        mutate_calls.append((svc, acct))
        return await real_mutate(svc, acct, mutator)

    monkeypatch.setattr(authenticated_client.app.state.profile_index, "upsert", _boom)
    monkeypatch.setattr(authenticated_client.app.state.credential_store, "mutate", _spy_mutate)

    with _server_errors_as_responses(authenticated_client):
        resp = _put_api_key(authenticated_client, "anthropic", "default", ANTHROPIC_KEY)

    assert resp.status_code == 500
    # Rollback alone preserved the concurrent owner's value; no compensation ran to clobber it.
    assert credential_blobs.read(service, "default") == concurrent_owned
    assert mutate_calls == []
    # Neither the caller's key nor the concurrent owner's key leaks into the response.
    assert ANTHROPIC_KEY not in resp.text
    assert "9999" not in resp.text


def test_set_api_key_rollback_does_not_compensate_over_same_key_external_commit(
    authenticated_client,
    credential_blobs,
    monkeypatch,
) -> None:
    """S2's identical key must survive after S1 rolls back and handles its failure.

    INVARIANT: plaintext equality cannot prove write ownership. Any post-rollback compensation
    from S1 is delayed until S2 commits the same key, making the ABA clobber deterministic if
    compensation is ever reintroduced.
    """
    account_id = _account_id(authenticated_client)
    previous_key = "sk-ant-api03-previous-key-0000"
    assert (
        _put_api_key(authenticated_client, "anthropic", "default", previous_key).status_code == 200
    )
    service = credential_service_for(credential_name_for(account_id, "default"))

    s1_wrote = threading.Event()
    release_s1_failure = threading.Event()
    s2_completed = threading.Event()
    persist_count = 0
    persist_count_lock = threading.Lock()
    compensation_calls: list[str] = []
    s1_task = None
    s1_initial_write = False
    # OME-1230 (F2, owner 2026-09-18): the API-key body moved behind the provider-credential
    # admin boundary, so the persistence seam this race patches is the admin module's.
    persist_credentials = profile_admin_module.persist_credentials_or_refuse
    credential_store = authenticated_client.app.state.credential_store
    write = credential_store.write
    delete = credential_store.delete
    mutate = credential_store.mutate

    async def _fail_first_after_write(*args, **kwargs) -> None:
        nonlocal persist_count, s1_initial_write, s1_task
        with persist_count_lock:
            persist_count += 1
            call_number = persist_count
        if call_number == 1:
            s1_task = asyncio.current_task()
            s1_initial_write = True
        await persist_credentials(*args, **kwargs)
        if call_number == 1:
            s1_initial_write = False
            s1_wrote.set()
            if not await asyncio.to_thread(release_s1_failure.wait, 5):
                raise TimeoutError("S1 failure was not released")
            raise RuntimeError("S1 publication failed after its transactional write")

    async def _record_s1_compensation(operation: str, service_name: str) -> None:
        if service_name == service and asyncio.current_task() is s1_task and not s1_initial_write:
            compensation_calls.append(operation)
            if not await asyncio.to_thread(s2_completed.wait, 5):
                raise TimeoutError("S2 did not commit before compensation")

    async def _delay_compensating_write(service_name, account, value) -> None:
        await _record_s1_compensation("write", service_name)
        await write(service_name, account, value)

    async def _delay_compensating_delete(service_name, account) -> None:
        await _record_s1_compensation("delete", service_name)
        await delete(service_name, account)

    async def _delay_compensating_mutate(service_name, account, mutator) -> None:
        await _record_s1_compensation("mutate", service_name)
        await mutate(service_name, account, mutator)

    monkeypatch.setattr(
        profile_admin_module, "persist_credentials_or_refuse", _fail_first_after_write
    )
    monkeypatch.setattr(credential_store, "write", _delay_compensating_write)
    monkeypatch.setattr(credential_store, "delete", _delay_compensating_delete)
    monkeypatch.setattr(credential_store, "mutate", _delay_compensating_mutate)

    with (
        _server_errors_as_responses(authenticated_client),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        request_s1 = executor.submit(
            _put_api_key,
            authenticated_client,
            "anthropic",
            "default",
            ANTHROPIC_KEY,
        )
        assert s1_wrote.wait(5), "S1 never wrote its transactional credential"
        request_s2 = executor.submit(
            _put_api_key,
            authenticated_client,
            "anthropic",
            "default",
            ANTHROPIC_KEY,
        )
        release_s1_failure.set()
        response_s2 = request_s2.result(timeout=10)
        s2_completed.set()
        response_s1 = request_s1.result(timeout=10)

    assert response_s1.status_code == 500
    assert response_s2.status_code == 200
    assert compensation_calls == []
    assert json.loads(credential_blobs.read(service, "default")) == {
        "auth_type": "api_key",
        "api_key": ANTHROPIC_KEY,
    }


@pytest.mark.asyncio
async def test_set_api_key_over_oauth_profile_flips_auth_type(
    authenticated_client, credential_blobs
) -> None:
    """A profile is exactly one auth at a time: setting a key on an EXISTING
    authenticated OAuth profile replaces the token blob in the shared
    credential slot and flips auth_type/account_label/scopes (audit F17/F24)."""
    account_id = _account_id(authenticated_client)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="oauth",
            account_label="user@example.com",
            scopes=["org:create_api_key"],
        )
    )
    service = credential_service_for(credential_name_for(account_id, "default"))
    credential_blobs.write(
        service,
        "default",
        json.dumps(
            {
                "access_token": "tok",
                "refresh_token": "rt",
                "expires_at_ms": 1,
                "token_type": "Bearer",
            }
        ),
    )

    resp = _put_api_key(authenticated_client, "anthropic", "default", ANTHROPIC_KEY)

    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_type"] == "api_key"
    assert body["account_label"] == "API key ····1234"
    assert body["scopes"] == []  # OAuth scopes are meaningless for API keys
    assert json.loads(credential_blobs.read(service, "default")) == {
        "auth_type": "api_key",
        "api_key": ANTHROPIC_KEY,
    }


def test_set_api_key_accepts_defaults(authenticated_client) -> None:
    resp = _put_api_key(
        authenticated_client,
        "anthropic",
        "keyed",
        ANTHROPIC_KEY,
        defaults={"max_tokens": 2048},
    )

    assert resp.status_code == 200
    assert resp.json()["defaults"]["max_tokens"] == 2048


def test_set_api_key_unknown_provider_404(authenticated_client) -> None:
    resp = _put_api_key(authenticated_client, "nope", "keyed", ANTHROPIC_KEY)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "unknown_provider"


def test_set_api_key_codex_unsupported_400(authenticated_client) -> None:
    resp = _put_api_key(authenticated_client, "codex", "keyed", "sk-proj-test-key-1234")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "api_key_not_supported"


def test_set_api_key_too_short_400(authenticated_client) -> None:
    resp = _put_api_key(authenticated_client, "anthropic", "keyed", "  abc  ")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_api_key"


def test_set_api_key_requires_auth(client) -> None:
    resp = client.put(
        "/v1/auth/anthropic/profiles/keyed/api-key",
        json={"api_key": ANTHROPIC_KEY},
    )
    assert resp.status_code == 401


def test_gemini_profile_api_key_supported(authenticated_client, credential_blobs) -> None:
    account_id = _account_id(authenticated_client)

    resp = _put_api_key(authenticated_client, "gemini-cli", "keyed", "AIzaSyTestKey1234")

    assert resp.status_code == 200, resp.text
    assert resp.json()["auth_type"] == "api_key"
    service = gemini_credential_service_for(credential_name_for(account_id, "keyed"))
    assert json.loads(credential_blobs.read(service, "default"))["api_key"] == "AIzaSyTestKey1234"


def test_delete_api_key_profile_removes_blob(authenticated_client, credential_blobs) -> None:
    account_id = _account_id(authenticated_client)
    assert (
        _put_api_key(authenticated_client, "anthropic", "keyed", ANTHROPIC_KEY).status_code == 200
    )
    service = credential_service_for(credential_name_for(account_id, "keyed"))
    assert credential_blobs.read(service, "default") is not None

    resp = authenticated_client.delete("/v1/auth/anthropic/profiles/keyed")

    assert resp.status_code == 204
    assert credential_blobs.read(service, "default") is None
    listed = authenticated_client.get("/v1/auth/anthropic/profiles").json()["profiles"]
    assert all(p["name"] != "keyed" for p in listed)


def test_refresh_api_key_profile_is_noop(authenticated_client, credential_blobs) -> None:
    account_id = _account_id(authenticated_client)
    assert (
        _put_api_key(authenticated_client, "anthropic", "keyed", ANTHROPIC_KEY).status_code == 200
    )

    resp = authenticated_client.post("/v1/auth/anthropic/profiles/keyed/refresh")

    assert resp.status_code == 200
    assert resp.json()["state"] == "authenticated"
    assert resp.json()["auth_type"] == "api_key"
    service = credential_service_for(credential_name_for(account_id, "keyed"))
    assert json.loads(credential_blobs.read(service, "default"))["api_key"] == ANTHROPIC_KEY


def test_refresh_api_key_profile_with_missing_blob_marks_error(
    authenticated_client, credential_blobs
) -> None:
    """Refresh must not report success when the key blob is gone: the
    strategy re-validates the blob and the lifecycle flips ERROR (audit F09)."""
    account_id = _account_id(authenticated_client)
    assert (
        _put_api_key(authenticated_client, "anthropic", "keyed", ANTHROPIC_KEY).status_code == 200
    )
    service = credential_service_for(credential_name_for(account_id, "keyed"))
    credential_blobs.delete(service, "default")

    resp = authenticated_client.post("/v1/auth/anthropic/profiles/keyed/refresh")

    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "auth_required"
    status = authenticated_client.get("/v1/auth/anthropic/profiles/keyed/status")
    assert status.json()["state"] == "error"


def test_set_api_key_cancels_pending_oauth_flow(authenticated_client, credential_blobs) -> None:
    """A late OAuth callback (pending TTL 600s) must not overwrite a key that
    was stored after the flow began (audit F10)."""
    account_id = _account_id(authenticated_client)
    authenticated_client.app.state.anthropic_http_factory = _oauth_token_factory()
    start = authenticated_client.post("/v1/auth/anthropic/profiles", json={"name": "keyed"})
    assert start.status_code == 201
    state = start.json()["state"]

    assert (
        _put_api_key(authenticated_client, "anthropic", "keyed", ANTHROPIC_KEY).status_code == 200
    )

    auth_header = authenticated_client.headers.pop("Authorization")
    try:
        late = authenticated_client.get("/callback", params={"code": "late-code", "state": state})
    finally:
        authenticated_client.headers["Authorization"] = auth_header
    assert late.status_code == 400  # pending state was consumed by the key PUT

    service = credential_service_for(credential_name_for(account_id, "keyed"))
    assert json.loads(credential_blobs.read(service, "default")) == {
        "auth_type": "api_key",
        "api_key": ANTHROPIC_KEY,
    }
    profile = authenticated_client.get("/v1/auth/anthropic/profiles/keyed").json()
    assert profile["auth_type"] == "api_key"
    assert profile["state"] == "authenticated"


def test_oauth_completion_flips_auth_type_back_to_oauth(
    authenticated_client, credential_blobs
) -> None:
    """Re-OAuth of a former api_key profile must flip the discriminator back
    (audit F11), and starting the flow must NOT desync it beforehand (F08)."""
    account_id = _account_id(authenticated_client)
    assert (
        _put_api_key(authenticated_client, "anthropic", "keyed", ANTHROPIC_KEY).status_code == 200
    )
    authenticated_client.app.state.anthropic_http_factory = _oauth_token_factory()

    start = authenticated_client.post("/v1/auth/anthropic/profiles", json={"name": "keyed"})
    assert start.status_code == 201
    started = authenticated_client.get("/v1/auth/anthropic/profiles/keyed").json()
    # Flow START keeps the api_key identity (only state goes pending) — F08.
    assert started["auth_type"] == "api_key"
    assert started["account_label"] == "API key ····1234"
    assert started["state"] == "pending"

    auth_header = authenticated_client.headers.pop("Authorization")
    try:
        cb = authenticated_client.get(
            "/callback", params={"code": "auth-code", "state": start.json()["state"]}
        )
    finally:
        authenticated_client.headers["Authorization"] = auth_header
    assert cb.status_code == 200

    profile = authenticated_client.get("/v1/auth/anthropic/profiles/keyed").json()
    assert profile["auth_type"] == "oauth"
    assert profile["state"] == "authenticated"
    service = credential_service_for(credential_name_for(account_id, "keyed"))
    assert json.loads(credential_blobs.read(service, "default"))["access_token"] == "oauth-tok"


def test_patch_profile_preserves_api_key_auth_type(authenticated_client) -> None:
    """PATCHing defaults must not reset the discriminator (audit F12)."""
    assert (
        _put_api_key(authenticated_client, "anthropic", "keyed", ANTHROPIC_KEY).status_code == 200
    )

    resp = authenticated_client.patch(
        "/v1/auth/anthropic/profiles/keyed",
        json={"defaults": {"max_tokens": 1024}},
    )

    assert resp.status_code == 200
    assert resp.json()["auth_type"] == "api_key"
    assert resp.json()["defaults"]["max_tokens"] == 1024


def test_legacy_profile_index_defaults_to_oauth_auth_type(
    authenticated_client, credential_blobs
) -> None:
    """Index blobs written before the auth_type field deserialize with the
    'oauth' default — the no-migration-friction constraint."""
    account_id = _account_id(authenticated_client)
    credential_blobs.write(
        "aigateway:index",
        "default",
        json.dumps(
            {
                "version": 1,
                "profiles": [
                    {
                        "id": f"{account_id}:anthropic:legacy",
                        "account_id": account_id,
                        "provider": "anthropic",
                        "name": "legacy",
                        "state": "authenticated",
                    }
                ],
            }
        ),
    )

    listed = authenticated_client.get("/v1/auth/anthropic/profiles")

    assert listed.status_code == 200
    (profile,) = [p for p in listed.json()["profiles"] if p["name"] == "legacy"]
    assert profile["auth_type"] == "oauth"
