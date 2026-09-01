"""API-key connection endpoints (SF-291 / D-AIGW-018).

POST /v1/oauth/connections/api-key       — create an api-key connection
PUT  /v1/oauth/connections/{id}/api-key  — replace the key

The key is written to the SAME credential-blob slot the chat path reads for a
connection (credential_key_for(account_id, connection.id)), encrypted at rest,
and never echoed back.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from aigateway.core.oauth.store import credential_key_for
from aigateway.plugins.anthropic_provider.auth import (
    credential_service_for as anthropic_service_for,
)

_KEY = "sk-ant-api03-test-connection-key"


@contextmanager
def _server_errors_as_responses(client) -> Iterator[None]:
    transport = getattr(client, "_transport")
    previous = transport.raise_server_exceptions
    transport.raise_server_exceptions = False
    try:
        yield
    finally:
        transport.raise_server_exceptions = previous


def _create(client, *, provider="anthropic", label: str | None = "work", api_key=_KEY):
    body: dict[str, str] = {"provider": provider, "api_key": api_key}
    if label is not None:
        body["label"] = label
    return client.post("/v1/oauth/connections/api-key", json=body)


def test_create_api_key_connection_is_active_and_typed(authenticated_client) -> None:
    resp = _create(authenticated_client)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "active"
    assert data["auth_type"] == "api_key"
    assert data["label"] == "work"
    assert data["provider"] == "anthropic"
    # The raw key must never be echoed back.
    assert _KEY not in resp.text


def test_create_api_key_connection_overrides_a_stale_insert_shape(
    authenticated_client,
    credential_blobs,
) -> None:
    from tortoise.backends.base.executor import EXECUTOR_CACHE

    cache_key = ("default", None, "oauth_connections")
    previous = EXECUTOR_CACHE.get(cache_key)
    old_columns = [
        "id",
        "provider",
        "label",
        "status",
        "identity_sub",
        "identity_email",
        "identity_name",
        "identity_raw",
        "credential_locator",
        "created_at",
        "last_used_at",
        "last_refreshed_at",
        "error_message",
        "account_id",
    ]
    old_insert = (
        'INSERT INTO "oauth_connections" '
        '("id","provider","label","status","identity_sub","identity_email",'
        '"identity_name","identity_raw","credential_locator","created_at",'
        '"last_used_at","last_refreshed_at","error_message","account_id") '
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    EXECUTOR_CACHE[cache_key] = (
        old_columns,
        old_insert,
        old_columns,
        old_insert,
        'DELETE FROM "oauth_connections" WHERE "id"=?',
        {},
    )
    try:
        resp = _create(authenticated_client, label="stale-shape")
    finally:
        if previous is None:
            EXECUTOR_CACHE.pop(cache_key, None)
        else:
            EXECUTOR_CACHE[cache_key] = previous

    assert resp.status_code == 201, resp.text
    with sqlite3.connect(credential_blobs.db_path) as conn:
        row = conn.execute(
            "select auth_type from oauth_connections where id = ?",
            (resp.json()["id"],),
        ).fetchone()
    assert row == ("api_key",)


def test_create_writes_key_to_chat_read_slot_encrypted(
    authenticated_client, credential_blobs
) -> None:
    resp = _create(authenticated_client)
    data = resp.json()
    service = anthropic_service_for(credential_key_for(data["account_id"], data["id"]))
    # Decrypted blob is the api-key blob the chat path expects.
    decrypted = credential_blobs.read(service, "default")
    assert json.loads(decrypted) == {"auth_type": "api_key", "api_key": _KEY}
    # At-rest ciphertext does not contain the plaintext key.
    assert _KEY not in (credential_blobs.read_raw(service, "default") or "")


def test_create_anthropic_requires_label(authenticated_client) -> None:
    resp = _create(authenticated_client, label=None)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "label_required"


def test_create_duplicate_label_conflicts(authenticated_client) -> None:
    assert _create(authenticated_client, label="dup").status_code == 201
    resp = _create(authenticated_client, label="dup")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "label_conflict"


def test_create_codex_is_api_key_not_supported(authenticated_client) -> None:
    resp = _create(authenticated_client, provider="codex", label="cdx")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "api_key_not_supported"


def test_create_short_key_rejected(authenticated_client) -> None:
    resp = _create(authenticated_client, api_key="short")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_api_key"


def test_replace_short_key_rejected(authenticated_client) -> None:
    """The replace (PUT) path enforces the same minimum-length rule as create
    (pins the shared _validate_api_key contract on both endpoints)."""
    created = _create(authenticated_client, label="shortput").json()
    resp = authenticated_client.put(
        f"/v1/oauth/connections/{created['id']}/api-key",
        json={"api_key": "short"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_api_key"


def test_create_requires_auth(client) -> None:
    resp = _create(client)
    assert resp.status_code == 401


def test_list_connections_exposes_auth_type(authenticated_client) -> None:
    _create(authenticated_client, label="listed")
    listing = authenticated_client.get("/v1/oauth/connections")
    assert listing.status_code == 200
    rows = listing.json()["connections"]
    assert any(c["label"] == "listed" and c["auth_type"] == "api_key" for c in rows)


def test_replace_key_updates_blob(authenticated_client, credential_blobs) -> None:
    created = _create(authenticated_client, label="rotate").json()
    new_key = "sk-ant-api03-rotated-key-value"
    resp = authenticated_client.put(
        f"/v1/oauth/connections/{created['id']}/api-key",
        json={"api_key": new_key},
    )
    assert resp.status_code == 200, resp.text
    assert new_key not in resp.text
    service = anthropic_service_for(credential_key_for(created["account_id"], created["id"]))
    assert json.loads(credential_blobs.read(service, "default"))["api_key"] == new_key


def test_replace_key_persist_failure_is_sanitized_and_keeps_old_blob(
    authenticated_client, credential_blobs, monkeypatch
) -> None:
    created = _create(authenticated_client, label="rotate-fail").json()
    service = anthropic_service_for(credential_key_for(created["account_id"], created["id"]))
    before = credential_blobs.read(service, "default")
    assert before is not None
    new_key = "sk-ant-api03-new-key-that-must-not-leak"

    async def _boom(*_a, **_k):
        raise RuntimeError(f"credential store failed for {new_key}")

    monkeypatch.setattr(authenticated_client.app.state.credential_store, "write", _boom)

    with _server_errors_as_responses(authenticated_client):
        resp = authenticated_client.put(
            f"/v1/oauth/connections/{created['id']}/api-key",
            json={"api_key": new_key},
        )

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "credential_store_unavailable"
    assert new_key not in resp.text
    assert credential_blobs.read(service, "default") == before


def test_delete_api_key_connection_removes_blob(authenticated_client, credential_blobs) -> None:
    """API-key connections use the shared connection delete path; deleting the
    connection must remove the same credential blob the chat path reads."""
    created = _create(authenticated_client, label="delete-key").json()
    service = anthropic_service_for(credential_key_for(created["account_id"], created["id"]))
    assert credential_blobs.read(service, "default") is not None

    resp = authenticated_client.delete(f"/v1/oauth/connections/{created['id']}")

    assert resp.status_code == 204
    assert credential_blobs.read(service, "default") is None


def test_replace_key_on_missing_connection_404(authenticated_client) -> None:
    resp = authenticated_client.put(
        "/v1/oauth/connections/00000000-0000-0000-0000-000000000000/api-key",
        json={"api_key": _KEY},
    )
    assert resp.status_code == 404


def test_replace_key_on_oauth_connection_has_actionable_message(authenticated_client) -> None:
    from uuid import uuid4

    from aigateway.core.oauth.store import OAuthConnectionStore

    seed = _create(authenticated_client, label="seed-for-oauth-replace-test").json()

    async def _create_oauth_connection() -> str:
        store = OAuthConnectionStore()
        conn = await store.create_pending(
            account_id=seed["account_id"],
            provider="anthropic",
            label="oauth-only",
            connection_id=uuid4(),
        )
        return str(conn.id)

    connection_id = authenticated_client.portal.call(_create_oauth_connection)
    resp = authenticated_client.put(
        f"/v1/oauth/connections/{connection_id}/api-key",
        json={"api_key": _KEY},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "code": "connection_not_api_key",
        "message": "Connection does not use API-key authentication",
    }


def test_replace_key_unknown_provider_error_includes_provider(
    authenticated_client, monkeypatch
) -> None:
    created = _create(authenticated_client, label="missing-provider").json()
    monkeypatch.setattr(authenticated_client.app.state.providers, "get", lambda _provider: None)

    resp = authenticated_client.put(
        f"/v1/oauth/connections/{created['id']}/api-key",
        json={"api_key": _KEY},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == {"code": "unknown_provider", "provider": "anthropic"}


def test_api_key_connection_token_endpoint_rejected(authenticated_client) -> None:
    """An api-key connection has no OAuth token; /token must 400, not mint one."""
    created = _create(authenticated_client, label="notoken").json()
    resp = authenticated_client.get(f"/v1/oauth/connections/{created['id']}/token")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "connection_not_oauth"


def test_refresh_on_api_key_connection_rejected_without_corrupting(authenticated_client) -> None:
    """/refresh is OAuth-only: an api-key connection must be rejected (400
    connection_not_oauth) and must NOT be flipped to error (review F2)."""
    created = _create(authenticated_client, label="norefresh").json()
    resp = authenticated_client.post(f"/v1/oauth/connections/{created['id']}/refresh")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "connection_not_oauth"
    after = authenticated_client.get(f"/v1/oauth/connections/{created['id']}").json()
    assert after["status"] == "active"
    assert after["auth_type"] == "api_key"


def test_create_missing_provider_does_not_echo_key(authenticated_client) -> None:
    """A malformed body (missing provider) must 422 WITHOUT echoing the raw key
    in the validation error input (review F1)."""
    resp = authenticated_client.post(
        "/v1/oauth/connections/api-key", json={"label": "w", "api_key": _KEY}
    )
    assert resp.status_code == 422
    assert _KEY not in resp.text
    for err in resp.json()["detail"]:
        assert "input" not in err


def test_errored_api_key_connection_recovers_via_replace_key(authenticated_client) -> None:
    """An api-key connection that errored (e.g. a bad key) keeps its label and
    is recoverable via Replace key, which re-activates it (review RF2-1)."""
    from uuid import UUID

    from aigateway.core.oauth.store import OAuthConnectionStore

    created = _create(authenticated_client, label="recover").json()
    cid = created["id"]
    account_id = created["account_id"]

    async def _force_error() -> None:
        store = OAuthConnectionStore()
        conn = await store.get(account_id, UUID(cid))
        assert conn is not None
        await store.mark_error(conn, "bad key")

    authenticated_client.portal.call(_force_error)

    errored = authenticated_client.get(f"/v1/oauth/connections/{cid}").json()
    assert errored["status"] == "error"
    assert errored["label"] == "recover"  # label preserved, NOT "error:<id>"
    assert errored["error_message"] == "bad key"

    resp = authenticated_client.put(
        f"/v1/oauth/connections/{cid}/api-key",
        json={"api_key": "sk-ant-api03-fresh-good-key"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert resp.json()["label"] == "recover"
    assert resp.json()["error_message"] is None  # reactivate clears the error


def test_create_api_key_atomic_on_persist_failure(authenticated_client, monkeypatch) -> None:
    """If the credential write fails, no active orphan connection row is left
    behind (review F4 — persist before activating the row)."""
    store = authenticated_client.app.state.credential_store

    async def _boom(*_a, **_k):
        raise RuntimeError("credential store unavailable")

    monkeypatch.setattr(store, "write", _boom)
    try:
        _create(authenticated_client, label="atomic")
    except RuntimeError:
        pass  # TestClient re-raises server exceptions; the invariant is what matters
    listing = authenticated_client.get("/v1/oauth/connections").json()["connections"]
    assert all(c["label"] != "atomic" for c in listing)


def test_create_api_key_persist_failure_returns_sanitized_5xx(
    authenticated_client, monkeypatch
) -> None:
    """Credential-store failures should be structured and must not echo the key."""
    leak_marker = "sk-ant-api03-create-key-that-must-not-leak"

    async def _boom(*_a, **_k):
        raise RuntimeError(f"credential store failed for {leak_marker}")

    monkeypatch.setattr(authenticated_client.app.state.credential_store, "write", _boom)

    with _server_errors_as_responses(authenticated_client):
        resp = _create(authenticated_client, label="atomic-http", api_key=leak_marker)

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "credential_store_unavailable"
    assert leak_marker not in resp.text
    listing = authenticated_client.get("/v1/oauth/connections").json()["connections"]
    assert all(c["label"] != "atomic-http" for c in listing)


def test_persist_failure_is_logged_for_ops_without_leaking_key(
    authenticated_client, monkeypatch, caplog
) -> None:
    """A credential-store failure must be observable to ops (which service
    failed + the exception type) so a silent 503 isn't undiagnosable — but the
    raw key and the underlying exception message (which a store could echo)
    must NEVER reach the log."""
    leak_marker = "sk-ant-api03-key-that-must-not-reach-logs"

    async def _boom(*_a, **_k):
        raise RuntimeError(f"store blew up with {leak_marker}")

    monkeypatch.setattr(authenticated_client.app.state.credential_store, "write", _boom)

    with (
        caplog.at_level(logging.ERROR),
        _server_errors_as_responses(authenticated_client),
    ):
        resp = _create(authenticated_client, label="logtest", api_key=leak_marker)

    assert resp.status_code == 503
    # Observable: ops can see a persist failure occurred and its type.
    assert any(
        "Failed to persist API-key credentials" in record.message for record in caplog.records
    )
    assert "RuntimeError" in caplog.text
    # Safe: neither the raw key nor the store's exception message is logged.
    assert leak_marker not in caplog.text


def test_create_api_key_deletes_blob_when_row_create_fails(
    authenticated_client, credential_blobs, monkeypatch
) -> None:
    """If the key persists but the row create fails (e.g. label race -> Integrity
    Error), the compensating cleanup deletes the orphan blob so no credential is
    left without a connection (review F4 cleanup path)."""
    from tortoise.exceptions import IntegrityError

    from aigateway.core.oauth.store import OAuthConnectionStore

    captured: dict = {}

    async def _boom(self, **kwargs):  # noqa: ANN001
        captured["account_id"] = kwargs["account_id"]
        captured["connection_id"] = kwargs["connection_id"]
        raise IntegrityError("label race")

    monkeypatch.setattr(OAuthConnectionStore, "create_api_key", _boom)
    resp = _create(authenticated_client, label="cleanup")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "label_conflict"
    # The key was persisted before create; the except-branch must have removed it.
    service = anthropic_service_for(
        credential_key_for(captured["account_id"], captured["connection_id"])
    )
    assert credential_blobs.read(service, "default") is None
