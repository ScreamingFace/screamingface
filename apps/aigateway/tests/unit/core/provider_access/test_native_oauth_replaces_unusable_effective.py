"""A native OAuth connection replaces a migrated pair's unusable effective row (OME-1209, E1b).

# FEATURE: Stage E spec R6 — once the Profile routes retire, `POST /v1/oauth/connections` is the
# only OAuth re-authorisation path. On a `migrated` pair whose effective Connection is `error` or
# `revoked` at start, that flow's callback makes its new row effective and revokes the old one.
# INVARIANT: the switch is fenced by the marker generation observed at start — a newer start, a
# delete or a key write in between makes the callback lose with 409 `connection_conflict`, and
# nothing is half-published (marker, both rows and the new blob unchanged).
# INVARIANT: a usable (`active` or `pending`) effective row is never displaced.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from connection_backed_admin_probes import blob_at_connection_address, connection, marker
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import access_token_of, callback, use_tokens
from fastapi import HTTPException
from provider_access_harness import ANTHROPIC, PROVIDER
from tortoise.exceptions import IntegrityError

from aigateway.core.oauth.identity import AccountIdentity
from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.profile_models import ProfileState
from aigateway.core.provider_access import PairAuthorityStore, Selector
from aigateway.routes import auth as auth_routes

CHAT_COMPLETION = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _seed(harness: ConnectionBackedHarness, state: ProfileState) -> str:
    harness.seed_profile(state=state)
    return harness.migrated["default"]


def _revoke(harness: ConnectionBackedHarness, connection_id: str) -> None:
    harness.call(OAuthConnectionStore().mark_revoked, connection(harness, connection_id), "gone")


def _start(harness: ConnectionBackedHarness, label: str = "work") -> Any:
    started = harness.client.post(
        "/v1/oauth/connections", json={"provider": PROVIDER, "label": label}
    )
    assert started.status_code == 201, started.text
    return started.json()


def _repair(harness: ConnectionBackedHarness, token: str = "new-tok", label: str = "work") -> str:
    use_tokens(harness, token)
    started = _start(harness, label=label)
    completed = callback(harness, started["state"])
    assert completed.status_code == 200, completed.text
    return str(started["connection_id"])


def _effective(harness: ConnectionBackedHarness) -> str | None:
    effective = marker(harness).effective_connection_id
    return None if effective is None else str(effective)


def _chat_key(harness: ConnectionBackedHarness) -> tuple[int, Any]:
    captured: dict[str, Any] = {}

    async def completion(_self: Any, body: dict[str, Any]) -> Any:
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    with patch(CHAT_COMPLETION, completion):
        response = harness.client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-haiku-4-5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    return response.status_code, captured.get("api_key")


def _assert_connection_conflict(response: Any) -> None:
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "connection_conflict"


# --- the repair -----------------------------------------------------------------------------


@pytest.mark.parametrize("unusable", ["error", "revoked"])
def test_a_native_flow_replaces_an_unusable_effective_row(
    migrated: ConnectionBackedHarness, unusable: str
) -> None:
    h = migrated
    old = _seed(h, ProfileState.AUTHENTICATED)
    if unusable == "error":
        h.call(OAuthConnectionStore().mark_error, connection(h, old), "rejected")
    else:
        _revoke(h, old)
    before = marker(h)

    new = _repair(h)

    after = marker(h)
    assert (after.migration_state, _effective(h)) == ("migrated", new)
    assert after.generation > before.generation
    assert connection(h, old).status == "revoked"
    assert connection(h, new).status == "active"
    assert access_token_of(blob_at_connection_address(h, new)) == "new-tok"


def test_chat_reads_the_replacement_after_the_repair(migrated: ConnectionBackedHarness) -> None:
    h = migrated
    _seed(h, ProfileState.ERROR)

    new = _repair(h)

    target = h.call(
        h.access.resolve, h.account_id, PROVIDER, Selector.from_header(None), plugin=ANTHROPIC
    )
    assert target.credential_name == credential_key_for(h.account_id, new)
    assert _chat_key(h) == (200, "new-tok")


def test_a_re_login_into_another_live_connection_makes_that_one_effective(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: before E1b a native flow on a migrated pair opened a plain row beside the effective one.
    # A repair that signs into that row's provider identity must promote it (with the fresh tokens)
    # — not return 200 and leave the pair on its broken effective row.
    h = migrated
    old = _seed(h, ProfileState.AUTHENTICATED)

    async def same_identity(*_args: Any, **_kwargs: Any) -> AccountIdentity:
        return AccountIdentity(sub="user-1")

    monkeypatch.setattr(type(ANTHROPIC), "extract_identity", same_identity)
    use_tokens(h, "sibling-tok")
    sibling = _start(h, label="sibling")
    assert callback(h, sibling["state"]).status_code == 200
    sibling_id = str(sibling["connection_id"])
    assert _effective(h) == old
    h.call(OAuthConnectionStore().mark_error, connection(h, old), "rejected")

    use_tokens(h, "new-tok")
    repair = _start(h)
    assert callback(h, repair["state"]).status_code == 200

    assert _effective(h) == sibling_id
    assert connection(h, old).status == "revoked"
    assert connection(h, str(repair["connection_id"])).status == "revoked"
    assert (connection(h, sibling_id).status, connection(h, sibling_id).identity_sub) == (
        "active",
        "user-1",
    )
    assert access_token_of(blob_at_connection_address(h, sibling_id)) == "new-tok"
    assert _chat_key(h) == (200, "new-tok")


def test_an_errored_api_key_effective_row_is_replaced_by_oauth(
    migrated: ConnectionBackedHarness,
) -> None:
    # WHY: a broken effective row serves nothing, whatever its type — the user who signs in with
    # OAuth wants a working pair, as the Profile facade gave them.
    h = migrated
    h.seed_profile(state=ProfileState.ERROR, auth_type="api_key", credential="sk-ant-old")
    old = h.migrated["default"]

    new = _repair(h)

    assert _effective(h) == new
    assert connection(h, old).status == "revoked"
    assert (connection(h, new).status, connection(h, new).auth_type) == ("active", "oauth")


# --- the effective row's own label targets it ----------------------------------------------------


@pytest.mark.parametrize("auth_type", ["api_key", "oauth"])
def test_a_flow_named_like_the_effective_row_replaces_it_even_when_it_works(
    migrated: ConnectionBackedHarness, auth_type: str
) -> None:
    # WHY: the label is the native flow's only way to address a connection — reusing the effective
    # row's label means "re-authorise THAT one", the Profile facade's re-auth by name. It is how a
    # working API key switches to OAuth without a window with no credential.
    h = migrated
    h.seed_profile(state=ProfileState.AUTHENTICATED, auth_type=auth_type, credential="old-cred")
    old = h.migrated["default"]
    label = connection(h, old).label

    new = _repair(h, label=label)

    assert _effective(h) == new
    assert connection(h, old).status == "revoked"
    row = connection(h, new)
    assert (row.status, row.label, row.auth_type) == ("active", label, "oauth")
    assert _chat_key(h) == (200, "new-tok")


def test_a_same_label_re_login_of_the_same_identity_replaces_the_effective_row(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: the effective row itself carries the identity — it is the target, not a sibling to
    # promote; its revocation frees the identity for the new row.
    h = migrated
    old = _seed(h, ProfileState.AUTHENTICATED)
    row = connection(h, old)
    row.identity_sub = "user-1"
    h.call(row.save, update_fields=["identity_sub"])

    async def same_identity(*_args: Any, **_kwargs: Any) -> AccountIdentity:
        return AccountIdentity(sub="user-1")

    monkeypatch.setattr(type(ANTHROPIC), "extract_identity", same_identity)

    new = _repair(h, label=row.label)

    assert _effective(h) == new
    assert (connection(h, new).status, connection(h, new).identity_sub) == ("active", "user-1")
    assert connection(h, old).status == "revoked"


# --- a usable effective row stays --------------------------------------------------------------


@pytest.mark.parametrize("usable", [ProfileState.AUTHENTICATED, ProfileState.PENDING])
def test_a_usable_effective_row_is_not_displaced(
    migrated: ConnectionBackedHarness, usable: ProfileState
) -> None:
    h = migrated
    old = _seed(h, usable)
    before = (marker(h), connection(h, old).status)

    new = _repair(h)

    assert (marker(h), connection(h, old).status) == before
    assert connection(h, new).status == "active"


def test_an_effective_row_that_breaks_after_the_start_is_not_replaced(
    migrated: ConnectionBackedHarness,
) -> None:
    # WHY: the decision is taken on the pair observed at start; a row usable then stays the
    # pair's effective row — the user can re-run the repair once it reads as errored.
    h = migrated
    old = _seed(h, ProfileState.AUTHENTICATED)
    use_tokens(h, "new-tok")
    started = _start(h)
    h.call(OAuthConnectionStore().mark_error, connection(h, old), "rejected")

    assert callback(h, started["state"]).status_code == 200

    assert _effective(h) == old
    assert connection(h, old).status == "error"


# --- the fence ---------------------------------------------------------------------------------


def test_the_first_of_two_repairs_wins_and_the_second_publishes_nothing(
    migrated: ConnectionBackedHarness,
) -> None:
    h = migrated
    old = _seed(h, ProfileState.ERROR)
    use_tokens(h, "new-tok")
    first = _start(h, label="first")
    second = _start(h, label="second")

    assert callback(h, first["state"]).status_code == 200
    after_first = marker(h)
    _assert_connection_conflict(callback(h, second["state"]))

    assert marker(h) == after_first
    assert _effective(h) == str(first["connection_id"])
    assert connection(h, old).status == "revoked"
    assert connection(h, str(second["connection_id"])).status != "active"
    assert blob_at_connection_address(h, str(second["connection_id"])) is None


def test_a_delete_between_start_and_callback_wins(migrated: ConnectionBackedHarness) -> None:
    h = migrated
    old = _seed(h, ProfileState.ERROR)
    use_tokens(h, "new-tok")
    started = _start(h)
    assert h.client.delete(f"/v1/oauth/connections/{old}").status_code == 204
    after_delete = marker(h)

    _assert_connection_conflict(callback(h, started["state"]))

    assert marker(h) == after_delete
    assert _effective(h) is None
    assert connection(h, str(started["connection_id"])).status != "active"
    assert blob_at_connection_address(h, str(started["connection_id"])) is None


def test_a_marker_move_between_start_and_callback_wins(migrated: ConnectionBackedHarness) -> None:
    # WHY: a key write (op 8) or any other authority change advances the generation; the repair
    # observed the older one and must not switch the effective row over it.
    h = migrated
    old = _seed(h, ProfileState.ERROR)
    use_tokens(h, "new-tok")
    started = _start(h)
    pair = marker(h)
    h.call(
        PairAuthorityStore().advance,
        h.account_id,
        PROVIDER,
        expected_generation=pair.generation,
        migration_state="migrated",
        effective_connection_id=pair.effective_connection_id,
    )
    moved = marker(h)

    _assert_connection_conflict(callback(h, started["state"]))

    assert marker(h) == moved
    assert _effective(h) == old
    assert connection(h, old).status == "error"
    assert connection(h, str(started["connection_id"])).status != "active"


def test_the_losing_repair_retires_its_row_and_frees_its_label(
    migrated: ConnectionBackedHarness,
) -> None:
    h = migrated
    _seed(h, ProfileState.ERROR)
    use_tokens(h, "new-tok")
    first = _start(h, label="first")
    second = _start(h, label="second")
    assert callback(h, first["state"]).status_code == 200

    _assert_connection_conflict(callback(h, second["state"]))

    assert connection(h, str(second["connection_id"])).status == "revoked"
    _start(h, label="second")


# --- nothing half-published ----------------------------------------------------------------------


def test_a_credential_store_outage_publishes_nothing(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = migrated
    old = _seed(h, ProfileState.ERROR)
    before = marker(h)

    async def store_down(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPException(status_code=503, detail={"code": "credential_store_unavailable"})

    monkeypatch.setattr(auth_routes, "_persist_connection_credentials", store_down)
    use_tokens(h, "new-tok")
    started = _start(h)

    assert callback(h, started["state"]).status_code == 503

    assert marker(h) == before
    assert connection(h, old).status == "error"
    assert connection(h, str(started["connection_id"])).status == "error"


def test_an_activation_conflict_publishes_nothing(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = migrated
    old = _seed(h, ProfileState.ERROR)
    before = marker(h)

    async def collide(*_args: Any, **_kwargs: Any) -> None:
        raise IntegrityError("unique constraint")

    monkeypatch.setattr(OAuthConnectionStore, "complete_pending", collide)
    use_tokens(h, "new-tok")
    started = _start(h)

    _assert_connection_conflict(callback(h, started["state"]))

    assert marker(h) == before
    assert connection(h, old).status == "error"
    assert connection(h, str(started["connection_id"])).status == "revoked"
