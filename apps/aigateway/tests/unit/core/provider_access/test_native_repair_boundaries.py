"""Boundaries of a native repair of a migrated pair (OME-1209, E1b, review round 2).

# FEATURE: Stage E spec R6 — a native repair uses the Connection side only.
# INVARIANT: no repair branch reads or writes the legacy Profile document (R6, §8 Q7): the OAuth
# replacement, the same-identity retirement and the API-key takeover all leave it byte-identical.
# INVARIANT: a repair that signs into the identity of another row of the pair retires that row
# under its lock and activates its own fresh row, so a stale failure of the retired row (before
# or after the commit) never breaks the repaired pair; a failed repair leaves that row untouched.
"""

from __future__ import annotations

from typing import Any

import pytest
from connection_backed_admin_probes import (
    blob_at_connection_address,
    connection,
    marker,
)
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import access_token_of, callback, use_tokens
from provider_access_harness import ANTHROPIC, PROVIDER

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.oauth.identity import AccountIdentity
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.routes import auth as auth_routes
from tests.unit.seed_state import SeedState

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
    h.seed_credential(state=SeedState.AUTHENTICATED)
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
    h.seed_credential(state=SeedState.AUTHENTICATED)
    old = h.migrated["default"]

    repair(h, monkeypatch)

    assert _effective(h) != old


def test_a_same_identity_repair_leaves_the_profile_document_untouched(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = migrated
    _old, _sibling = _live_sibling(h, monkeypatch)

    use_tokens(h, "new-tok")
    repair = _start(h, "work")
    assert callback(h, repair["state"]).status_code == 200

    assert _effective(h) == str(repair["connection_id"])


# --- the same-identity row retires; its stale failures cannot break the repair -------------------


def test_a_same_identity_row_broken_before_the_repair_stays_broken_and_the_repair_lands(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: a refresh failure that reached the row first cleared its identity (`mark_error`), so
    # the repair's identity-scoped lock no longer matches it and its new row takes the identity.
    h = migrated
    _old, sibling = _live_sibling(h, monkeypatch)
    h.call(OAuthConnectionStore().mark_error, connection(h, sibling), "refresh rejected")
    use_tokens(h, "new-tok")
    repair = _start(h, "work")

    assert callback(h, repair["state"]).status_code == 200

    new = str(repair["connection_id"])
    assert _effective(h) == new
    assert (connection(h, sibling).status, connection(h, sibling).identity_sub) == ("error", None)
    assert (connection(h, new).status, connection(h, new).identity_sub) == ("active", "user-1")
    assert access_token_of(blob_at_connection_address(h, new)) == "new-tok"


def test_a_stale_refresh_failure_after_the_repair_cannot_break_the_repaired_pair(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: a refresh that started on the sibling's old tokens fails only after the repair commits.
    h = migrated
    _old, sibling = _live_sibling(h, monkeypatch)
    stale = connection(h, sibling)
    use_tokens(h, "new-tok")
    repair = _start(h, "work")
    assert callback(h, repair["state"]).status_code == 200

    assert h.call(OAuthConnectionStore().mark_error, stale, "refresh rejected") is None

    new = str(repair["connection_id"])
    assert _effective(h) == new
    assert connection(h, new).status == "active"
    assert access_token_of(blob_at_connection_address(h, new)) == "new-tok"


def test_a_failed_same_identity_repair_leaves_the_sibling_untouched(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = migrated
    old, sibling = _live_sibling(h, monkeypatch)
    before = marker(h)

    async def outage(*_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("database went away")

    monkeypatch.setattr(auth_routes, "_persist_connection_credentials", outage)
    use_tokens(h, "new-tok")
    repair = _start(h, "work")

    response = callback(h, repair["state"])

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "connection_activation_failed"
    assert marker(h) == before
    assert _effective(h) == old
    assert (connection(h, sibling).status, connection(h, sibling).identity_sub) == (
        "active",
        "user-1",
    )
    assert access_token_of(blob_at_connection_address(h, sibling)) == "sibling-tok"
    pending = connection(h, str(repair["connection_id"]))
    assert (pending.status, pending.label.startswith("error:")) == ("error", True)
