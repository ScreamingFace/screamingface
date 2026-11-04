"""`GET /v1/oauth/connections` marks the Connection chat uses (OME-1138 close-out, L7a).

# FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §2 — every listed row carries
# a required, read-only `effective`, true on at most one row per provider: the row the default
# chat resolve serves. The flag is computed over the caller's full set of rows and markers, then
# the `provider` and `status` filters apply, so a filtered listing still flags the right row.
# INVARIANT: the listing reads no secret and writes nothing; it lists the markers once and the
# Connections once. Without a `status` filter it hides `revoked` rows, except the effective one.
# STORY: as the Local Engine, I read which Connection chat uses and write to that one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from connection_backed_admin_probes import connection
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import PROVIDER
from test_availability_follows_resolve import _moved, _pending, _row
from test_compatibility_paths_retired import _plant_retired

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.provider_access import PairAuthorityStore, retire_effective
from aigateway.core.provider_access.pair_authority import PairAuthorityDataError
from tests.unit.seed_state import SeedState

KEY = "sk-ant-api03-effective-listing-key-1357"


@pytest.fixture
def h(
    authenticated_client: Any, credential_blobs: Any, monkeypatch: Any
) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _listing(h: ConnectionBackedHarness, **params: str) -> list[dict[str, Any]]:
    response = h.client.get("/v1/oauth/connections", params=params)
    assert response.status_code == 200, response.text
    return response.json()["connections"]


def _flags(rows: list[dict[str, Any]]) -> dict[str, bool]:
    return {row["id"]: row["effective"] for row in rows}


def _revoke(h: ConnectionBackedHarness, connection_id: str) -> None:
    h.call(OAuthConnectionStore().mark_revoked, connection(h, connection_id), "gone")


def _mark_migrated(h: ConnectionBackedHarness, provider: str, connection_id: str) -> None:
    async def advance() -> None:
        current = await PairAuthorityStore().read(h.account_id, provider)
        await PairAuthorityStore().advance(
            h.account_id,
            provider,
            expected_generation=current.generation,
            migration_state="migrated",
            effective_connection_id=row.id,
        )

    row = connection(h, connection_id)
    h.call(advance)


# --- the flag ------------------------------------------------------------------------------------


def test_every_row_carries_a_boolean_and_only_the_served_row_is_flagged(
    h: ConnectionBackedHarness,
) -> None:
    served = h.seed_connection(label="work")
    waiting = _pending(h)
    first, second = _row(h, "openai", "one"), _row(h, "openai", "two")
    started = _pending(h, "codex")

    rows = _listing(h)

    assert all(isinstance(row["effective"], bool) for row in rows)
    assert _flags(rows) == {
        served: True,
        waiting: False,
        first: False,
        second: False,
        started: False,
    }


def test_a_migrated_reference_is_flagged_beside_another_active_row(
    h: ConnectionBackedHarness,
) -> None:
    h.seed_credential(state=SeedState.AUTHENTICATED)
    other = h.seed_connection(label="work")

    assert _flags(_listing(h)) == {h.migrated["default"]: True, other: False}


@pytest.mark.parametrize("state", [SeedState.PENDING, SeedState.ERROR])
def test_a_migrated_reference_is_flagged_whatever_its_status(
    h: ConnectionBackedHarness, state: SeedState
) -> None:
    # WHY: the Engine repairs or refuses on the row chat is bound to; an active row beside it
    # serves nothing while the reference stands.
    h.seed_credential(state=state)
    other = h.seed_connection(label="work")

    assert _flags(_listing(h)) == {h.migrated["default"]: True, other: False}


def test_a_provider_filter_keeps_the_flag(h: ConnectionBackedHarness) -> None:
    h.seed_credential(state=SeedState.AUTHENTICATED)
    other = h.seed_connection(label="work")
    openai = _row(h, "openai", "one")

    assert _flags(_listing(h, provider=PROVIDER)) == {h.migrated["default"]: True, other: False}
    assert _flags(_listing(h, provider="openai")) == {openai: True}


def test_a_status_filter_keeps_the_flag(h: ConnectionBackedHarness) -> None:
    # WHY: the flag is the pair's, not the filtered page's — `status=active` shows the one active
    # row unflagged, because the reference names the errored row.
    h.seed_credential(state=SeedState.ERROR)
    other = h.seed_connection(label="work")

    assert _flags(_listing(h, status="active")) == {other: False}
    assert _flags(_listing(h, status="error")) == {h.migrated["default"]: True}


def test_an_unfiltered_listing_shows_a_revoked_effective_row_and_hides_the_rest(
    h: ConnectionBackedHarness,
) -> None:
    # WHY (spec §8.3): a migrated reference to a revoked row must be visible as the effective row,
    # or the Engine would see one active row and no flag — a contract break the gateway caused.
    h.seed_credential(state=SeedState.AUTHENTICATED)
    effective = h.migrated["default"]
    _revoke(h, effective)
    gone = h.seed_connection(label="gone")
    _revoke(h, gone)
    other = h.seed_connection(label="work")

    assert _flags(_listing(h)) == {effective: True, other: False}
    assert _flags(_listing(h, status="revoked")) == {effective: True, gone: False}


@pytest.mark.parametrize("referenced", [False, True], ids=["stray", "migrated-reference"])
def test_a_provider_declaring_only_none_flags_no_row(
    h: ConnectionBackedHarness, referenced: bool
) -> None:
    # INVARIANT (spec §2, owner 2026-11-03): a provider that owns no credential slot has no
    # effective row whatever is stored under its name, as its availability says (D17).
    stray = _row(h, "ollama")
    if referenced:
        _mark_migrated(h, "ollama", stray)

    assert _flags(_listing(h, provider="ollama")) == {stray: False}


class _Hidden:
    """The endpoint-access port, hiding one provider from every account."""

    def __init__(self, hidden: str) -> None:
        self._hidden = hidden

    def permits(self, _operation: Any, *, account_id: str, provider: str) -> bool:
        del account_id
        return provider != self._hidden


def test_a_row_of_a_provider_the_registry_does_not_know_is_not_flagged(
    h: ConnectionBackedHarness,
) -> None:
    # INVARIANT (owner, 2026-11-03; OME-1721): chat cannot route a provider gone from the
    # registry, so its pair has no effective row, as availability lists no row for it.
    stray = _row(h, "retired-provider")

    assert _flags(_listing(h, provider="retired-provider")) == {stray: False}


def test_a_row_of_a_provider_hidden_from_the_caller_is_not_flagged(
    h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY VIEW, as availability: the endpoint policy grants every operation alike
    # (`RemoteEndpointAccess.permits`), so a provider hidden from VIEW is refused by chat too.
    hidden = _row(h, "openai", "one")
    shown = _row(h, "codex", "one")
    monkeypatch.setattr(h.client.app.state, "endpoint_access", _Hidden("openai"))

    assert _flags(_listing(h)) == {hidden: False, shown: True}


# --- the two reads are one snapshot --------------------------------------------------------------


def _write_between_the_reads(
    monkeypatch: pytest.MonkeyPatch, write: Callable[[], Awaitable[None]]
) -> list[str]:
    """Commit `write` after every marker listing, before the Connection listing."""
    listings: list[str] = []
    real_markers = PairAuthorityStore.list

    async def then_write(self: PairAuthorityStore, account_id: str) -> Any:
        listed = await real_markers(self, account_id)
        listings.append(account_id)
        await write()
        return listed

    monkeypatch.setattr(PairAuthorityStore, "list", then_write)
    return listings


def test_a_delete_between_the_two_reads_is_read_again(
    h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: a delete that clears the reference and revokes its row between the two reads would
    # pair the old reference with the revoked row and flag it; the Engine would then create a
    # second active row beside the one chat now serves, and chat would refuse the pair (409).
    h.seed_credential(state=SeedState.AUTHENTICATED)
    deleted = [connection(h, h.migrated["default"])]
    other = h.seed_connection(label="work")

    async def delete_once() -> None:
        if deleted:
            row = deleted.pop()
            await retire_effective(row)
            await OAuthConnectionStore().mark_revoked(row, "gone")

    listings = _write_between_the_reads(monkeypatch, delete_once)

    assert _flags(_listing(h)) == {other: True}
    assert listings == [h.account_id, h.account_id]


def test_a_listing_that_never_settles_is_refused(
    h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: the re-read is bounded — a second moved marker is a 503 to retry, never a guess.
    h.seed_credential(state=SeedState.AUTHENTICATED)

    async def move_the_marker() -> None:
        current = await PairAuthorityStore().read(h.account_id, PROVIDER)
        await PairAuthorityStore().advance(
            h.account_id,
            PROVIDER,
            expected_generation=current.generation,
            migration_state=current.migration_state,
            effective_connection_id=current.effective_connection_id,
        )

    listings = _write_between_the_reads(monkeypatch, move_the_marker)
    response = h.client.get("/v1/oauth/connections")

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "credential_store_unavailable"
    assert response.headers["Retry-After"] == "1"
    assert listings == [h.account_id, h.account_id]


# --- only the listing carries it -----------------------------------------------------------------


class _ValidKeys:
    async def validate(self, _plugin: Any, _provider: str, _key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )


def test_the_single_row_get_and_the_writes_carry_no_flag(h: ConnectionBackedHarness) -> None:
    h.client.app.state.api_key_validation_service = _ValidKeys()
    created = h.client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": PROVIDER, "label": "key", "api_key": KEY},
    )
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]
    read = h.client.get(f"/v1/oauth/connections/{connection_id}")
    renamed = h.client.patch(f"/v1/oauth/connections/{connection_id}", json={"label": "renamed"})

    for response in (created, read, renamed):
        assert response.status_code in (200, 201), response.text
        assert "effective" not in response.json()


def test_the_list_row_schema_requires_a_read_only_flag(h: ConnectionBackedHarness) -> None:
    schemas = h.client.get("/openapi.json").json()["components"]["schemas"]
    listing = schemas["OAuthConnectionListResponse"]["properties"]["connections"]["items"]
    row = schemas[listing["$ref"].rsplit("/", 1)[-1]]

    assert "effective" in row["required"]
    assert row["properties"]["effective"]["type"] == "boolean"
    assert row["properties"]["effective"]["readOnly"] is True
    assert "effective" not in schemas["OAuthConnectionResponse"]["properties"]


# --- what the listing must never do --------------------------------------------------------------


def test_the_listing_reads_no_secret_writes_nothing_and_lists_once(
    h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.seed_credential(state=SeedState.AUTHENTICATED)
    _revoke(h, h.migrated["default"])
    h.seed_connection(label="work")
    _moved(h, "error", "broken")
    store = h.client.app.state.credential_store
    connection_listings: list[dict[str, Any]] = []
    marker_listings: list[str] = []
    real_list = OAuthConnectionStore.list
    real_markers = PairAuthorityStore.list

    async def counting(self: OAuthConnectionStore, account_id: Any, **filters: Any) -> Any:
        connection_listings.append(filters)
        return await real_list(self, account_id, **filters)

    async def counting_markers(self: PairAuthorityStore, account_id: str) -> Any:
        marker_listings.append(account_id)
        return await real_markers(self, account_id)

    def forbidden(name: str) -> Callable[..., Any]:
        async def refuse(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError(f"the connection listing called {name}")

        return refuse

    monkeypatch.setattr(OAuthConnectionStore, "list", counting)
    monkeypatch.setattr(PairAuthorityStore, "list", counting_markers)
    for name in (
        "get",
        "set_auth_type",
        "mark_error",
        "mark_pending_error",
        "mark_revoked",
        "touch_last_used",
        "touch_last_refreshed",
    ):
        monkeypatch.setattr(OAuthConnectionStore, name, forbidden(name))
    for name in ("read", "advance"):
        monkeypatch.setattr(PairAuthorityStore, name, forbidden(name))
    for name in ("read", "write", "delete", "begin_dispatch", "record_dispatch_outcome"):
        monkeypatch.setattr(store, name, forbidden(name))

    rows = _listing(h)

    assert sum(row["effective"] for row in rows) == 1
    assert len(connection_listings) == 1
    assert marker_listings == [h.account_id]


def test_a_marker_in_an_unknown_state_fails_the_listing(h: ConnectionBackedHarness) -> None:
    # INVARIANT (L4a): an unknown stored state is refused, never read as `none` — the listing
    # fails as chat does rather than flag a row by a guessed owner.
    h.seed_connection(label="work")
    _plant_retired(h)

    with pytest.raises(PairAuthorityDataError):
        h.client.get("/v1/oauth/connections")
