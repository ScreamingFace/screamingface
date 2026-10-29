"""Provider availability follows the default resolve (D17 fold-in, OME-1138).

# FEATURE: OME-1138 D17 — the availability listing (op 6) answers by the rule chat resolves by. A
# pair its marker's effective reference does not serve (no marker, `none`, or `migrated` with no
# reference) lists through its Connections by label: one active row → that row's operational
# status, two or more → `error`, none active → `pending`, else `error`, else `not_connected`.
# INVARIANT: over the table's cases, `connected` exactly when the default chat resolve returns a
# stored target that `authorize` accepts. Spec §4 names the accepted exceptions (a recorded
# `insufficient_credits` lists `error` while chat still dispatches; an OAuth row whose record is
# missing lists `connected` until chat marks it). Every case reads availability FIRST: a refused
# `authorize` marks the row, which would change what the listing reads.
# STORY: as the Hosted Engine, I list a provider connected natively after the census as
# `connected`, because chat serves it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.provider_access import (
    CredentialStoreUnavailable,
    PairAuthorityStore,
    Selector,
    SelectorAmbiguous,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
)
from aigateway.core.provider_access import profile_authorize as authorize_module
from aigateway.plugins.anthropic_provider.auth import credential_service_for

DEFAULT = Selector.from_header(None)
KEY = "sk-ant-api03-availability-fold-in"
MARKERS = ["absent", "none", "migrated"]
REFUSED = (SelectorAmbiguous, TargetMissing, TargetPending, TargetReauthRequired)


@pytest.fixture
def h(
    authenticated_client: Any, credential_blobs: Any, monkeypatch: Any
) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


# --- seeding: the pair's rows, then its marker ---------------------------------------------------


def _address(h: ConnectionBackedHarness, connection_id: str) -> str:
    return credential_service_for(credential_key_for(h.account_id, UUID(connection_id)))


def _active(h: ConnectionBackedHarness, label: str = "work") -> str:
    return h.seed_connection(label=label)


def _api_key(h: ConnectionBackedHarness, *, stored: bool = True) -> str:
    connection_id = h.seed_connection(label="key", auth_type="api_key", credential=None)
    if stored:
        h.blobs.write(
            _address(h, connection_id),
            "default",
            json.dumps({"auth_type": "api_key", "api_key": KEY}),
        )
    return connection_id


def _row(h: ConnectionBackedHarness, provider: str, label: str = "stray") -> str:
    """One active row of `provider`, created as the native flow leaves it (OAuth-tagged)."""

    async def create() -> OAuthConnection:
        store = OAuthConnectionStore()
        pending = await store.create_pending(
            account_id=h.account_id, provider=provider, label=label, connection_id=uuid4()
        )
        return await store.complete(pending, label=label, identity=None)

    return str(h.call(create).id)


def _pending(h: ConnectionBackedHarness, provider: str = PROVIDER) -> str:
    async def create() -> OAuthConnection:
        return await OAuthConnectionStore().create_pending(
            account_id=h.account_id, provider=provider, label="waiting", connection_id=uuid4()
        )

    return str(h.call(create).id)


def _moved(h: ConnectionBackedHarness, status: str, label: str) -> str:
    connection_id = h.seed_connection(label=label)

    async def move() -> None:
        await OAuthConnection.filter(id=UUID(connection_id)).update(status=status)

    h.call(move)
    return connection_id


def _marked(h: ConnectionBackedHarness, marker: str) -> None:
    if marker == "absent":
        return

    async def advance() -> None:
        current = await PairAuthorityStore().read(h.account_id, PROVIDER)
        await PairAuthorityStore().advance(
            h.account_id,
            PROVIDER,
            expected_generation=current.generation,
            migration_state="migrated" if marker == "migrated" else "none",
            effective_connection_id=None,
        )

    h.call(advance)


# --- observing: the listing, then chat -----------------------------------------------------------


def _statuses(h: ConnectionBackedHarness) -> dict[str, str]:
    rows = h.call(h.access.availability, h.account_id)
    return {row.provider: row.status for row in rows}


def _resolve(h: ConnectionBackedHarness) -> Any:
    return h.call(h.access.resolve, h.account_id, PROVIDER, DEFAULT, plugin=ANTHROPIC)


def _served(h: ConnectionBackedHarness) -> bool:
    """Whether chat would reach the provider: a stored target that `authorize` accepts."""
    try:
        target = _resolve(h)
        if target.kind != "stored":
            return False
        h.call(h.access.authorize, target, plugin=ANTHROPIC, provider=PROVIDER)
    except REFUSED:
        return False
    return True


# --- the agreement table -------------------------------------------------------------------------

Seed = Callable[[ConnectionBackedHarness], object]
ROWS: dict[str, tuple[Seed, str]] = {
    "one-active-oauth": (_active, "connected"),
    "one-active-api-key": (_api_key, "connected"),
    "active-beside-pending-and-error": (
        lambda h: (_active(h), _pending(h), _moved(h, "error", "broken")),
        "connected",
    ),
    "two-active": (lambda h: (_active(h, "work"), _active(h, "home")), "error"),
    "pending-only": (_pending, "pending"),
    "pending-beside-error": (lambda h: (_pending(h), _moved(h, "error", "broken")), "pending"),
    "error-only": (lambda h: _moved(h, "error", "broken"), "error"),
    "revoked-only": (lambda h: _moved(h, "revoked", "gone"), "not_connected"),
    "no-rows": (lambda h: None, "not_connected"),
}


@pytest.mark.parametrize("marker", MARKERS)
@pytest.mark.parametrize("rows", list(ROWS))
def test_availability_lists_connected_exactly_when_the_default_resolve_serves(
    h: ConnectionBackedHarness, rows: str, marker: str
) -> None:
    seed, expected = ROWS[rows]
    seed(h)
    _marked(h, marker)

    listed = _statuses(h)[PROVIDER]

    assert listed == expected
    assert (listed == "connected") is _served(h)


@pytest.mark.parametrize("marker", MARKERS)
def test_an_api_key_row_without_its_credential_record_lists_needs_reauth(
    h: ConnectionBackedHarness, marker: str
) -> None:
    # WHY on every marker: chat resolves the row and `authorize` cannot read the key, so it
    # answers re-authentication; the listing says the same before anyone tries.
    _api_key(h, stored=False)
    _marked(h, marker)

    assert _statuses(h)[PROVIDER] == "needs_reauth"
    assert _served(h) is False


def test_a_recorded_rejection_lists_needs_reauth_on_a_reference_less_migrated_pair(
    h: ConnectionBackedHarness,
) -> None:
    # WHY only on `migrated`: outcomes are recorded for a migrated pair's effective row alone
    # (`begin_dispatch`), so a reference-less pair meets one only on a credential record a former
    # effective row left behind. There the label path refuses the key as the listing reports it.
    connection_id = _api_key(h)
    _marked(h, "migrated")
    store = h.client.app.state.credential_store

    async def reject() -> None:
        observation = await store.begin_dispatch(_address(h, connection_id), "default")
        assert observation is not None
        await store.record_dispatch_outcome(observation, "needs_reauth")

    h.call(reject)

    assert _statuses(h)[PROVIDER] == "needs_reauth"
    with pytest.raises(TargetReauthRequired):
        _resolve(h)


# --- what the listing must never do --------------------------------------------------------------


def test_the_listing_reads_no_secret_writes_nothing_and_lists_connections_once(
    h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT (spec op 6): no secret read, no refresh, no mutation — and one Connection listing
    # per call, not one per provider. The OAuth-tagged row of an api-key-only provider is the one
    # chat retags on resolve (`_repair_api_key_only`); the listing must leave it as it is.
    _api_key(h)
    _row(h, "openai")
    _pending(h, "codex")
    store = h.client.app.state.credential_store
    listings: list[dict[str, Any]] = []
    real_list = OAuthConnectionStore.list

    async def counting(self: OAuthConnectionStore, account_id: Any, **filters: Any) -> Any:
        listings.append(filters)
        return await real_list(self, account_id, **filters)

    def forbidden(name: str) -> Callable[..., Any]:
        async def refuse(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError(f"the availability listing called {name}")

        return refuse

    def no_strategy(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the availability listing took the authorize path")

    monkeypatch.setattr(OAuthConnectionStore, "list", counting)
    for name in (
        "set_auth_type",
        "mark_error",
        "mark_pending_error",
        "mark_revoked",
        "touch_last_used",
        "touch_last_refreshed",
    ):
        monkeypatch.setattr(OAuthConnectionStore, name, forbidden(name))
    monkeypatch.setattr(PairAuthorityStore, "advance", forbidden("advance"))
    for name in ("read", "write", "mutate", "delete", "begin_dispatch", "record_dispatch_outcome"):
        monkeypatch.setattr(store, name, forbidden(name))
    monkeypatch.setattr(authorize_module, "credential_strategy_from", no_strategy)

    statuses = _statuses(h)

    assert (statuses[PROVIDER], statuses["openai"], statuses["codex"]) == (
        "connected",
        "connected",
        "pending",
    )
    assert listings == [{}]


def test_an_unreadable_connection_store_fails_the_listing(
    h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: a store that cannot answer fails the call, never a silent `not_connected`.
    class Down(Exception):
        pass

    async def down(*_args: Any, **_kwargs: Any) -> None:
        raise Down

    monkeypatch.setattr(OAuthConnectionStore, "list", down)

    with pytest.raises(Down):
        _statuses(h)


def test_an_unreadable_credential_register_fails_the_listing(
    h: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api_key(h)

    async def down(_service: str, _account: str) -> None:
        raise RuntimeError("credential state unavailable")

    monkeypatch.setattr(h.client.app.state.credential_store, "operational_state", down)

    with pytest.raises(CredentialStoreUnavailable):
        _statuses(h)


def test_a_connection_of_an_unregistered_provider_has_no_row(
    h: ConnectionBackedHarness,
) -> None:
    # INVARIANT (OME-1721): a row is a registered provider this account may VIEW; a stray row of
    # any other provider is listed with the account's Connections but never read for a status.
    _row(h, "gemini")

    statuses = _statuses(h)

    assert "gemini" not in statuses
    assert set(statuses) == {
        plugin.custom_llm_provider for plugin in h.client.app.state.providers.all()
    }


def test_a_no_auth_provider_lists_not_connected_beside_a_stray_connection(
    h: ConnectionBackedHarness,
) -> None:
    # WHY (spec §7): a provider declaring only "none" resolves targetless before its marker is
    # read, so a legacy row of the same provider string never stands for it in the listing.
    _row(h, "ollama")

    assert _statuses(h)["ollama"] == "not_connected"
