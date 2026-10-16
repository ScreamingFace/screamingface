"""Boundaries of a native repair of a migrated pair (OME-1209, E1b, review round 2).

# FEATURE: Stage E spec R6 — a native repair uses the Connection side only.
# INVARIANT: no repair branch reads or writes the legacy Profile document (R6, §8 Q7): the OAuth
# replacement, the same-identity promotion and the API-key takeover all leave it byte-identical.
# INVARIANT: a promoted row is still `active` under its row lock; a row that broke after the
# lookup is never made effective.
# INVARIANT: an unexpected failure of the promotion never strands this flow's `pending` row.
"""

from __future__ import annotations

from typing import Any

import pytest
from connection_backed_admin_probes import (
    blob_at_connection_address,
    connection,
    document,
    marker,
)
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import access_token_of, callback, use_tokens
from provider_access_harness import ANTHROPIC, PROVIDER
from tortoise.exceptions import IntegrityError

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.oauth.identity import AccountIdentity
from aigateway.core.oauth.models.oauth_connection import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.profile_models import ProfileState
from aigateway.routes import auth as auth_routes

KEY = "sk-ant-api03-e1b-boundaries-key-1111"


class _ValidKeys:
    async def validate(self, _plugin: Any, _provider: str, _key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )


@pytest.fixture
def migrated(
    authenticated_client, credential_blobs, monkeypatch: pytest.MonkeyPatch
) -> ConnectionBackedHarness:
    harness = ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)
    authenticated_client.app.state.api_key_validation_service = _ValidKeys()
    return harness


def _start(harness: ConnectionBackedHarness, label: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"provider": PROVIDER}
    if label is not None:
        body["label"] = label
    started = harness.client.post("/v1/oauth/connections", json=body)
    assert started.status_code == 201, started.text
    return started.json()


def _same_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    async def identity(*_args: Any, **_kwargs: Any) -> AccountIdentity:
        return AccountIdentity(sub="user-1")

    monkeypatch.setattr(type(ANTHROPIC), "extract_identity", identity)


def _live_sibling(h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """A working `default` effective row that then breaks, beside a live `sibling` of identity
    user-1. Returns (old effective id, sibling id)."""
    h.seed_profile(state=ProfileState.AUTHENTICATED)
    old = h.migrated["default"]
    _same_identity(monkeypatch)
    use_tokens(h, "sibling-tok")
    sibling = _start(h, "sibling")
    assert callback(h, sibling["state"]).status_code == 200
    h.call(OAuthConnectionStore().mark_error, connection(h, old), "rejected")
    return old, str(sibling["connection_id"])


def _effective(h: ConnectionBackedHarness) -> str | None:
    effective = marker(h).effective_connection_id
    return None if effective is None else str(effective)


# --- the legacy Profile document is not touched ---------------------------------------------------


def _replace_by_own_label(h: ConnectionBackedHarness, _monkeypatch: pytest.MonkeyPatch) -> None:
    use_tokens(h, "new-tok")
    started = _start(h, connection(h, h.migrated["default"]).label)
    assert callback(h, started["state"]).status_code == 200


def _replace_unlabelled(h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(type(ANTHROPIC), "requires_oauth_connection_label", lambda _self: False)
    use_tokens(h, "new-tok")
    started = _start(h, None)
    assert callback(h, started["state"]).status_code == 200


def _replace_broken(h: ConnectionBackedHarness, _monkeypatch: pytest.MonkeyPatch) -> None:
    h.call(OAuthConnectionStore().mark_error, connection(h, h.migrated["default"]), "rejected")
    use_tokens(h, "new-tok")
    started = _start(h, "work")
    assert callback(h, started["state"]).status_code == 200


def _replace_by_key(h: ConnectionBackedHarness, _monkeypatch: pytest.MonkeyPatch) -> None:
    label = connection(h, h.migrated["default"]).label
    created = h.client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": PROVIDER, "label": label, "api_key": KEY},
    )
    assert created.status_code == 201, created.text


@pytest.mark.parametrize(
    "repair",
    [_replace_by_own_label, _replace_unlabelled, _replace_broken, _replace_by_key],
    ids=["own-label", "unlabelled", "broken", "api-key"],
)
def test_a_native_repair_leaves_the_profile_document_untouched(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch, repair: Any
) -> None:
    h = migrated
    h.seed_profile(state=ProfileState.AUTHENTICATED)
    old = h.migrated["default"]
    before = document(h)
    assert before is not None

    repair(h, monkeypatch)

    assert _effective(h) != old
    assert document(h) == before


def test_a_same_identity_promotion_leaves_the_profile_document_untouched(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = migrated
    _old, sibling = _live_sibling(h, monkeypatch)
    before = document(h)

    use_tokens(h, "new-tok")
    repair = _start(h, "work")
    assert callback(h, repair["state"]).status_code == 200

    assert _effective(h) == sibling
    assert document(h) == before


# --- a sibling that broke after the lookup is not promoted ---------------------------------------


def test_a_sibling_that_breaks_before_its_lock_is_not_made_effective(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: the identity lookup runs before the transaction; a refresh failure in between leaves
    # the sibling `error`. Promoting it would point the pair at a row chat refuses.
    h = migrated
    old, sibling = _live_sibling(h, monkeypatch)
    before = marker(h)
    find_by_identity = OAuthConnectionStore.find_by_identity

    async def breaks_after_lookup(self: Any, *args: Any, **kwargs: Any) -> Any:
        found = await find_by_identity(self, *args, **kwargs)
        if found is not None and str(found.id) == sibling:
            stale = await OAuthConnection.get(id=found.id)
            await OAuthConnectionStore().mark_error(stale, "refresh rejected")
        return found

    monkeypatch.setattr(OAuthConnectionStore, "find_by_identity", breaks_after_lookup)
    use_tokens(h, "new-tok")
    repair = _start(h, "work")

    response = callback(h, repair["state"])

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "connection_conflict"
    assert marker(h) == before
    assert _effective(h) == old
    assert connection(h, sibling).status == "error"
    assert access_token_of(blob_at_connection_address(h, sibling)) == "sibling-tok"
    assert connection(h, str(repair["connection_id"])).status == "revoked"


# --- an unexpected promotion failure does not strand the pending row ------------------------------


def test_an_unexpected_promotion_failure_retires_the_pending_row(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = migrated
    old, sibling = _live_sibling(h, monkeypatch)
    before = marker(h)

    async def outage(*_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("database went away")

    monkeypatch.setattr(auth_routes, "promote_live_row", outage)
    use_tokens(h, "new-tok")
    repair = _start(h, "work")

    response = callback(h, repair["state"])

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "connection_activation_failed"
    assert marker(h) == before
    pending = connection(h, str(repair["connection_id"]))
    assert (pending.status, pending.label.startswith("error:")) == ("error", True)
    assert access_token_of(blob_at_connection_address(h, sibling)) == "sibling-tok"
    assert _effective(h) == old


def test_a_promotion_integrity_conflict_retires_the_pending_row(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = migrated
    old, _sibling = _live_sibling(h, monkeypatch)

    async def collide(*_args: Any, **_kwargs: Any) -> None:
        raise IntegrityError("unique constraint")

    monkeypatch.setattr(auth_routes, "promote_live_row", collide)
    use_tokens(h, "new-tok")
    repair = _start(h, "work")

    response = callback(h, repair["state"])

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "connection_conflict"
    assert connection(h, str(repair["connection_id"])).status == "revoked"
    assert _effective(h) == old
