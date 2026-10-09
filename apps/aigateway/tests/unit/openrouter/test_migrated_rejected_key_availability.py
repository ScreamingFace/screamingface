"""OME-1389 — a migrated slot whose key was rejected is never listed `connected`, and says why.

# FEATURE: OME-1389 (bug) — the ticket's path on a slot migrated FROM a legacy Profile: the
# provider rejects the stored key, the listing must stop saying `connected`, and every later call
# is refused without reaching the provider. The listing part is held by the availability overlay
# (#1029) and the OpenRouter `needs_reauth` outcome (#1240, OME-1250); these tests pin the whole
# path, which no earlier test walks end to end on a Profile-migrated slot.
# INVARIANT: a refusal that never reaches the provider writes one WARNING naming the pair, the
# effective Connection and its status — identifiers only, never a key, a locator or provider text.
"""

from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from litellm.exceptions import AuthenticationError

from aigateway.core.credential_blob.model import CredentialBlob
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import (
    OAuthConnectionStore,
    credential_key_for,
    credential_locator_for,
)
from aigateway.core.provider_access import PairAuthorityStore
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

PROVIDER = "openrouter"
KEY = "sk-or-v1-ome-1389-profile-key"
PROVIDER_TEXT = "invalid provider key from upstream"
LOGGER = "aigateway.core.provider_access.connection_backed"
_CHAT_COMPLETION = (
    "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin.chat_completion"
)


@pytest.fixture(autouse=True)
def _openrouter_ready(valid_api_key_readiness: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


def _account(client: Any) -> str:
    return cast(str, client.get("/v1/auth/me").json()["id"])


def _migrated_profile_slot(
    client: Any, *, status: str = "active", effective: bool = True
) -> str | None:
    """A legacy api-key Profile, then the backfill's `profile_only` migration onto its blob."""
    resp = client.put(f"/v1/auth/{PROVIDER}/profiles/default/api-key", json={"api_key": KEY})
    assert resp.status_code in (200, 201), resp.text
    account_id = _account(client)

    async def migrate() -> str | None:
        store = OAuthConnectionStore()
        connection: OAuthConnection = await store.create_pending(
            account_id=account_id,
            provider=PROVIDER,
            label="default",
            connection_id=uuid4(),
            credential_provider=PROVIDER,
        )
        connection.credential_locator = credential_locator_for(PROVIDER, account_id, "default")
        await connection.save(update_fields=["credential_locator"])
        connection = await store.set_auth_type(connection, "api_key") or connection
        if status != "pending":
            connection = await store.complete(connection, label="default", identity=None) or (
                connection
            )
        if status == "error":
            # WHY: what the pre-#1240 op 5 left behind on the ticket's account.
            connection = await store.mark_error(connection, PROVIDER_TEXT) or connection
        markers = PairAuthorityStore()
        current = await markers.read(account_id, PROVIDER)
        await markers.advance(
            account_id,
            PROVIDER,
            expected_generation=current.generation,
            migration_state="migrated",
            effective_connection_id=connection.id if effective else None,
            migration_note="profile_only",
        )
        return str(connection.id) if effective else None

    return cast("str | None", client.portal.call(migrate))


def _listed(client: Any) -> str:
    resp = client.get("/v1/provider-access")
    assert resp.status_code == 200, resp.text
    return {row["provider"]: row["status"] for row in resp.json()["providers"]}[PROVIDER]


def _chat(client: Any) -> Any:
    return client.post(
        "/v1/chat/completions",
        json={
            "model": "openrouter/anthropic/claude-fable-5",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )


def _status(client: Any, connection_id: str) -> str:
    account_id = _account(client)

    async def read() -> str:
        connection = await OAuthConnectionStore().get(account_id, connection_id)
        assert connection is not None
        return connection.status

    return cast(str, client.portal.call(read))


def _refusals(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == LOGGER and record.getMessage().startswith("provider access refused")
    ]


class _RejectingProvider:
    """The provider answers every call with an authentication failure; counts the calls.

    WHY `method`: `patch` replaces a class attribute, so the stand-in must be a plain function to
    bind as a method; an instance with `__call__` would not receive `self`.
    """

    def __init__(self) -> None:
        self.calls = 0

        async def method(_plugin: Any, _body: dict[str, Any]) -> None:
            self.calls += 1
            raise AuthenticationError(message=PROVIDER_TEXT, llm_provider=PROVIDER, model="m")

        self.method = method


# --- the ticket's path ------------------------------------------------------------------------


def test_a_rejected_key_on_a_profile_migrated_slot_is_listed_needs_reauth(
    authenticated_client: Any,
) -> None:
    client = authenticated_client
    connection_id = _migrated_profile_slot(client)
    assert connection_id is not None
    assert _listed(client) == "connected"
    provider = _RejectingProvider()

    with patch(_CHAT_COMPLETION, provider.method):
        first = _chat(client)
        listed = _listed(client)
        second = _chat(client)

    assert first.status_code == 401
    assert first.json()["detail"]["code"] == "auth_required"
    # WHY `active`: the rejection is the key's operational outcome (#1240), not a lifecycle error,
    # so a replaced key clears it without touching the Connection.
    assert _status(client, connection_id) == "active"
    assert listed == "needs_reauth"
    assert second.status_code == 401
    assert second.json()["detail"]["code"] == "auth_required"
    assert provider.calls == 1


def test_a_row_errored_before_the_outcome_register_is_listed_error(
    authenticated_client: Any,
) -> None:
    client = authenticated_client
    _migrated_profile_slot(client, status="error")
    provider = _RejectingProvider()

    with patch(_CHAT_COMPLETION, provider.method):
        resp = _chat(client)

    assert _listed(client) == "error"
    assert resp.status_code == 401
    assert provider.calls == 0


# --- the refusal says why ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "effective", "refusal", "logged_status", "http_status"),
    [
        ("error", True, "TargetReauthRequired", "error", 401),
        ("pending", True, "TargetPending", "pending", 409),
        ("active", False, "TargetMissing", "none", 404),
    ],
    ids=["errored-row", "pending-row", "no-effective-connection"],
)
def test_a_refused_resolve_logs_the_pair_and_its_connection(
    authenticated_client: Any,
    caplog: pytest.LogCaptureFixture,
    status: str,
    effective: bool,
    refusal: str,
    logged_status: str,
    http_status: int,
) -> None:
    client = authenticated_client
    connection_id = _migrated_profile_slot(client, status=status, effective=effective)
    account_id = _account(client)
    caplog.set_level(logging.WARNING, logger=LOGGER)

    with patch(_CHAT_COMPLETION, _RejectingProvider().method):
        resp = _chat(client)

    assert resp.status_code == http_status, resp.text
    [record] = _refusals(caplog)
    message = record.getMessage()
    assert record.levelno == logging.WARNING
    assert f"provider={PROVIDER}" in message
    assert f"account={account_id}" in message
    assert f"connection={connection_id or 'none'}" in message
    assert f"status={logged_status}" in message
    assert f"refusal={refusal}" in message
    assert "policy=dispatch" in message


def test_a_needs_reauth_refusal_logs_the_still_active_connection(
    authenticated_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client = authenticated_client
    connection_id = _migrated_profile_slot(client)
    with patch(_CHAT_COMPLETION, _RejectingProvider().method):
        assert _chat(client).status_code == 401
        caplog.clear()
        caplog.set_level(logging.WARNING, logger=LOGGER)
        assert _chat(client).status_code == 401

    [record] = _refusals(caplog)
    message = record.getMessage()
    assert f"connection={connection_id}" in message
    assert "status=active" in message
    assert "refusal=TargetReauthRequired" in message


def test_the_refusal_record_carries_no_secret_locator_or_provider_text(
    authenticated_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    # INVARIANT: identifiers and closed vocabularies only — provider text may carry anything.
    client = authenticated_client
    _migrated_profile_slot(client, status="error")
    account_id = _account(client)
    caplog.set_level(logging.WARNING, logger=LOGGER)

    with patch(_CHAT_COMPLETION, _RejectingProvider().method):
        _chat(client)

    [record] = _refusals(caplog)
    rendered = record.getMessage() + repr(record.args)
    assert KEY not in rendered
    assert credential_locator_for(PROVIDER, account_id, "default")["service"] not in rendered
    assert PROVIDER_TEXT not in rendered


def test_an_allowed_resolve_logs_no_refusal(
    authenticated_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client = authenticated_client
    _migrated_profile_slot(client)
    caplog.set_level(logging.WARNING, logger=LOGGER)

    async def answered(_self: Any, _body: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hi"},
                    "finish_reason": "stop",
                }
            ],
        }

    with patch(_CHAT_COMPLETION, answered):
        _chat(client)

    assert _refusals(caplog) == []


def test_a_refusal_without_a_document_logs_the_refused_connection_not_the_effective_one(
    authenticated_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    # WHY: with no legacy document the pair resolves its single ACTIVE Connection, which need not
    # be the effective one; the record must point the operator at the row that was refused.
    client = authenticated_client
    account_id = _account(client)
    created: dict[str, str] = {}
    for label in ("old", "work"):
        resp = client.post(
            "/v1/oauth/connections/api-key",
            json={"provider": PROVIDER, "label": label, "api_key": f"sk-or-v1-ome-1389-{label}"},
        )
        assert resp.status_code == 201, resp.text
        created[label] = cast(str, resp.json()["id"])

    async def errored_effective_and_a_lost_blob() -> None:
        store = OAuthConnectionStore()
        old = await store.get(account_id, created["old"])
        assert old is not None
        await store.mark_error(old, PROVIDER_TEXT)
        markers = PairAuthorityStore()
        current = await markers.read(account_id, PROVIDER)
        await markers.advance(
            account_id,
            PROVIDER,
            expected_generation=current.generation,
            migration_state="migrated",
            effective_connection_id=old.id,
        )
        await CredentialBlob.filter(
            service=f"aigateway:{PROVIDER}:{credential_key_for(account_id, created['work'])}"
        ).delete()

    client.portal.call(errored_effective_and_a_lost_blob)
    caplog.set_level(logging.WARNING, logger=LOGGER)

    with patch(_CHAT_COMPLETION, _RejectingProvider().method):
        refused = _chat(client)

    assert refused.status_code == 401, refused.text
    [record] = _refusals(caplog)
    message = record.getMessage()
    assert f"connection={created['work']}" in message
    assert "status=active" in message
    assert f"connection={created['old']}" not in message
