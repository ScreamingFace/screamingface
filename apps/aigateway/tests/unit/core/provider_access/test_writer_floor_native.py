"""G0 writer floor — native Connection writers claim a legacy-owned pair (OME-1497).

# FEATURE: OME-1138 D18, G0 (contract §5.3, owner decision 2026-10-06) — native API-key create,
# key replacement, delete, OAuth start and OAuth callback are ownership changes: on a `none` or
# `quarantined` pair each claims the generation it observed, keeps the state (no auto-promotion,
# D14) and loses with the native 409 `connection_conflict` when another ownership change won.
# INVARIANT: native create captures before its key validation (network I/O); key replacement
# captures after it, as the migrated paths do — a change during that validation is
# last-writer-wins, a change after the capture loses.
# INVARIANT: non-effective native rows of a `migrated` pair keep their existing fences.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

import pytest
from connection_backed_admin_probes import blob_at_connection_address, document, marker, set_api_key
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import access_token_of, callback, pending_entry, use_tokens
from provider_access_harness import PROVIDER, ProfileBackedHarness

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.provider_access import PairAuthorityStore
from aigateway.core.provider_access.writer_floor import claim_pair
from aigateway.routes import auth as auth_routes

KEY = "sk-ant-api03-native-floor-key-1111"
NEW_KEY = "sk-ant-api03-native-floor-key-2222"


class _ValidKeys:
    """Every key is valid; `during` runs inside the validation, i.e. between capture and claim."""

    def __init__(self) -> None:
        self.during: Callable[[], Awaitable[None]] | None = None

    async def validate(self, _plugin: Any, _provider: str, _key: str) -> ApiKeyValidationResult:
        if self.during is not None:
            await self.during()
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    harness = ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)
    authenticated_client.app.state.api_key_validation_service = _ValidKeys()
    return harness


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    harness = ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)
    authenticated_client.app.state.api_key_validation_service = _ValidKeys()
    return harness


def _validation(harness: Any) -> _ValidKeys:
    return harness.client.app.state.api_key_validation_service


async def _claim_the_current_pair(account_id: str) -> None:
    await claim_pair(await PairAuthorityStore().read(account_id, PROVIDER))


def _owner_change_after_the_next_pair_read(monkeypatch: pytest.MonkeyPatch) -> None:
    real_read = PairAuthorityStore.read
    fired: list[str] = []

    async def read_then_lose_the_pair(self: Any, account_id: str, provider: str) -> Any:
        observed = await real_read(self, account_id, provider)
        if not fired:
            fired.append(provider)
            await claim_pair(observed)
        return observed

    monkeypatch.setattr(PairAuthorityStore, "read", read_then_lose_the_pair)


def _create(harness: Any, label: str = "work", key: str = KEY) -> Any:
    return harness.client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": PROVIDER, "label": label, "api_key": key},
    )


def _replace(harness: Any, connection_id: str, key: str = NEW_KEY) -> Any:
    return harness.client.put(
        f"/v1/oauth/connections/{connection_id}/api-key", json={"api_key": key}
    )


def _row(harness: Any, connection_id: str) -> Any:
    return harness.call(OAuthConnectionStore().get, harness.account_id, connection_id)


def _api_key_at(harness: Any, connection_id: str) -> str | None:
    blob = blob_at_connection_address(harness, connection_id)
    return None if blob is None else json.loads(blob)["api_key"]


def _assert_connection_conflict(response: Any) -> None:
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "connection_conflict"


# --- API-key create -------------------------------------------------------------------------


def test_a_native_key_create_claims_an_unmarked_pair_and_keeps_it_legacy_owned(
    legacy: ProfileBackedHarness,
) -> None:
    created = _create(legacy)

    assert created.status_code == 201, created.text
    pair = marker(legacy)
    assert (pair.migration_state, pair.generation) == ("none", 1)
    assert (pair.effective_connection_id, pair.migration_note) == (None, None)
    assert _api_key_at(legacy, created.json()["id"]) == KEY


def test_a_native_key_create_loses_to_an_ownership_change_during_its_validation(
    legacy: ProfileBackedHarness,
) -> None:
    _validation(legacy).during = lambda: _claim_the_current_pair(legacy.account_id)

    _assert_connection_conflict(_create(legacy))

    assert legacy.call(OAuthConnectionStore().list, legacy.account_id, provider=PROVIDER) == []
    assert marker(legacy).generation == 1


def test_a_native_key_create_on_a_migrated_pair_keeps_the_marker(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_profile()
    before = marker(migrated)

    assert _create(migrated, label="side").status_code == 201

    assert marker(migrated) == before


# --- API-key replacement --------------------------------------------------------------------


def test_a_native_key_replacement_captures_the_pair_after_its_validation(
    legacy: ProfileBackedHarness,
) -> None:
    connection_id = _create(legacy).json()["id"]
    _validation(legacy).during = lambda: _claim_the_current_pair(legacy.account_id)

    replaced = _replace(legacy, connection_id)

    # WHY 200: the change landed during validation, before the capture — last-writer-wins.
    assert replaced.status_code == 200, replaced.text
    assert _api_key_at(legacy, connection_id) == NEW_KEY
    assert (marker(legacy).migration_state, marker(legacy).generation) == ("none", 3)


def test_a_native_key_replacement_that_lost_the_pair_after_its_capture_writes_nothing(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection_id = _create(legacy).json()["id"]
    _owner_change_after_the_next_pair_read(monkeypatch)

    _assert_connection_conflict(_replace(legacy, connection_id))

    assert _api_key_at(legacy, connection_id) == KEY
    # WHY 1: the capture runs inside the publication transaction, so on SQLite's one connection
    # the simulated writer joined it and rolled back with it; the PostgreSQL lane races a
    # committed one.
    assert marker(legacy).generation == 1


# --- delete ---------------------------------------------------------------------------------


def test_a_native_delete_claims_the_pair(legacy: ProfileBackedHarness) -> None:
    connection_id = _create(legacy).json()["id"]

    assert legacy.client.delete(f"/v1/oauth/connections/{connection_id}").status_code == 204

    assert (marker(legacy).migration_state, marker(legacy).generation) == ("none", 2)
    assert _row(legacy, connection_id).status == "revoked"
    assert blob_at_connection_address(legacy, connection_id) is None


def test_a_native_delete_that_lost_the_pair_keeps_the_connection_and_its_blob(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection_id = _create(legacy).json()["id"]
    _owner_change_after_the_next_pair_read(monkeypatch)

    _assert_connection_conflict(legacy.client.delete(f"/v1/oauth/connections/{connection_id}"))

    assert _row(legacy, connection_id).status == "active"
    assert _api_key_at(legacy, connection_id) == KEY


# --- OAuth start and callback ---------------------------------------------------------------


def _start(harness: Any, label: str = "work") -> Any:
    return harness.client.post("/v1/oauth/connections", json={"provider": PROVIDER, "label": label})


def test_a_native_oauth_start_and_its_callback_each_claim_and_keep_the_pair_legacy_owned(
    legacy: ProfileBackedHarness,
) -> None:
    use_tokens(legacy, "native-tok")
    started = _start(legacy)
    assert started.status_code == 201, started.text
    state = started.json()["state"]
    after_start = marker(legacy)
    assert (after_start.migration_state, after_start.generation) == ("none", 1)
    assert pending_entry(legacy, state).observed_pair == after_start

    assert callback(legacy, state).status_code == 200

    pair = marker(legacy)
    assert (pair.migration_state, pair.generation) == ("none", 2)
    connection_id = started.json()["connection_id"]
    assert _row(legacy, connection_id).status == "active"
    assert access_token_of(blob_at_connection_address(legacy, connection_id)) == "native-tok"


def test_a_second_native_oauth_start_supersedes_the_first_flow(
    legacy: ProfileBackedHarness,
) -> None:
    # WHY: each start is an ownership change (§5.3); the first callback claims the pair its start
    # published, which the second start has since moved — the latest start wins, the first 409s.
    use_tokens(legacy, "second-tok")
    first = _start(legacy, label="first")
    second = _start(legacy, label="second")

    _assert_connection_conflict(callback(legacy, first.json()["state"]))
    assert callback(legacy, second.json()["state"]).status_code == 200

    assert _row(legacy, first.json()["connection_id"]).status != "active"
    assert _row(legacy, second.json()["connection_id"]).status == "active"
    assert (marker(legacy).migration_state, marker(legacy).generation) == ("none", 3)


class _Listener:
    """A loopback listener that binds nothing."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def _loopback(harness: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = harness.client.app.state.providers.get(PROVIDER)
    cfg = plugin.oauth_config()
    monkeypatch.setattr(
        plugin, "oauth_config", lambda: replace(cfg, loopback_redirect_ports=[1455])
    )


def test_a_native_oauth_start_that_cannot_bind_its_loopback_leaves_the_flow_in_flight(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY (OME-307 Blocker 5): a start that never started must not supersede the flow in flight —
    # the redirect binds BEFORE the claim, so a 503 claims nothing and writes no row.
    _loopback(legacy, monkeypatch)
    binds: list[int] = []

    async def bind_only_once(*_args: Any, **_kwargs: Any) -> _Listener:
        binds.append(len(binds))
        if len(binds) > 1:
            raise OSError("port in use")
        return _Listener()

    monkeypatch.setattr(asyncio, "start_server", bind_only_once)
    use_tokens(legacy, "first-tok")
    first = _start(legacy, label="first")
    assert first.status_code == 201, first.text
    before = marker(legacy)

    refused = _start(legacy, label="second")

    assert refused.status_code == 503, refused.text
    assert refused.json()["detail"]["code"] == "oauth_loopback_unavailable"
    assert marker(legacy) == before
    rows = legacy.call(OAuthConnectionStore().list, legacy.account_id, provider=PROVIDER)
    assert [row.label for row in rows] == ["first"]
    assert callback(legacy, first.json()["state"]).status_code == 200
    assert _row(legacy, first.json()["connection_id"]).status == "active"


def test_a_native_oauth_start_that_lost_its_claim_closes_its_loopback_listener(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _loopback(legacy, monkeypatch)
    listener = _Listener()

    async def bind(*_args: Any, **_kwargs: Any) -> _Listener:
        return listener

    monkeypatch.setattr(asyncio, "start_server", bind)
    _owner_change_after_the_next_pair_read(monkeypatch)

    _assert_connection_conflict(_start(legacy))

    assert listener.closed
    assert legacy.client.app.state.loopback_oauth_callbacks == {}


def test_a_native_oauth_start_loses_to_an_ownership_change_after_its_capture(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owner_change_after_the_next_pair_read(monkeypatch)

    _assert_connection_conflict(_start(legacy))

    assert legacy.call(OAuthConnectionStore().list, legacy.account_id, provider=PROVIDER) == []


def test_a_native_callback_after_another_ownership_change_loses_and_activates_nothing(
    legacy: ProfileBackedHarness,
) -> None:
    use_tokens(legacy, "late-tok")
    started = _start(legacy)
    state = started.json()["state"]
    set_api_key(legacy, "default")

    response = callback(legacy, state)

    _assert_connection_conflict(response)
    connection_id = started.json()["connection_id"]
    assert _row(legacy, connection_id).status != "active"
    assert blob_at_connection_address(legacy, connection_id) is None
    assert marker(legacy).generation == 2


def test_a_native_callback_that_lost_the_pair_leaves_a_same_named_profile_unchanged(
    legacy: ProfileBackedHarness,
) -> None:
    # WHY: the callback's compat-document update runs in its claim's transaction — a lost claim
    # must not turn a same-named legacy api_key Profile into an authenticated OAuth one.
    legacy.seed_profile(name="work", auth_type="api_key", credential=KEY)
    before = document(legacy, "work")
    use_tokens(legacy, "late-tok")
    started = _start(legacy, label="work")
    set_api_key(legacy, "default")

    _assert_connection_conflict(callback(legacy, started.json()["state"]))

    assert document(legacy, "work") == before


def test_a_native_callback_that_lost_the_pair_before_activation_activates_nothing(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_extract = auth_routes._extract_connection_identity

    async def extract_after_an_owner_change(app: Any, pending: Any, *args: Any) -> Any:
        await _claim_the_current_pair(pending.account_id)
        return await real_extract(app, pending, *args)

    monkeypatch.setattr(auth_routes, "_extract_connection_identity", extract_after_an_owner_change)
    use_tokens(legacy, "late-tok")
    started = _start(legacy)

    _assert_connection_conflict(callback(legacy, started.json()["state"]))

    connection_id = started.json()["connection_id"]
    assert _row(legacy, connection_id).status != "active"
    assert blob_at_connection_address(legacy, connection_id) is None


async def _store_down(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("store down")


@pytest.mark.parametrize(
    ("broken", "code"),
    [
        ("credential_write", "credential_store_unavailable"),
        ("activation", "connection_activation_failed"),
    ],
)
def test_a_native_callback_that_fails_to_publish_keeps_the_pair_generation(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch, broken: str, code: str
) -> None:
    # WHY (§5.3): check and publication are atomic, and a failed callback is not an ownership
    # change — the claim commits only together with the activated row and its blob.
    use_tokens(legacy, "failed-tok")
    started = _start(legacy)
    before = marker(legacy)
    if broken == "credential_write":
        monkeypatch.setattr(legacy.client.app.state.credential_store, "write", _store_down)
    else:
        monkeypatch.setattr(OAuthConnectionStore, "complete_pending", _store_down)

    failed = callback(legacy, started.json()["state"])

    assert failed.status_code == 503, failed.text
    assert failed.json()["detail"]["code"] == code
    assert marker(legacy) == before
    connection_id = started.json()["connection_id"]
    assert _row(legacy, connection_id).status != "active"
    assert blob_at_connection_address(legacy, connection_id) is None
