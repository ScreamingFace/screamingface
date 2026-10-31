"""The Stage E compatibility paths stay retired (OME-1138 close-out, L4a).

# FEATURE: OME-1138 close-out, L4a — Stage E left compatibility code nothing writes or needs: the
# `quarantined` marker state (no writer since E5c deleted the backfill), and the HONOUR selector
# policy with named `X-Profile` selection and its `SelectorUnknown` refusal (production has run
# REJECT_EXPLICIT since Stage D). These tests pin their absence.
# INVARIANT: a present `X-Profile` is refused by the parse itself, with no policy to consult.
# INVARIANT: the marker knows exactly `none` and `migrated`; any other stored state is refused
# loudly on every read path — never read as `none`, never answered as a pair conflict.
# INVARIANT: `migration_note` is neither read nor written; the column stays one more release so a
# rolled-back image still finds it (spec §9 Q1), and L4c drops it.
"""

from __future__ import annotations

import dataclasses
import inspect
import typing
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from connection_backed_harness import ConnectionBackedHarness
from fastapi import FastAPI
from provider_access_harness import ANTHROPIC, PROVIDER
from starlette.requests import Request
from tortoise.contrib.test import tortoise_test_context

import aigateway.core.provider_access as provider_access
from aigateway.core.auth.models import Account
from aigateway.core.provider_access import (
    DEFAULT_SELECTOR_NAME,
    CredentialAuthorityUnavailable,
    PairConflict,
    PairDisposition,
    Selector,
    SelectorUnsupported,
    pair_inventory,
)
from aigateway.core.provider_access import selector as selector_module
from aigateway.core.provider_access import types as types_module
from aigateway.core.provider_access.models import ProviderCredentialSlot
from aigateway.core.provider_access.pair_admin import listing
from aigateway.core.provider_access.pair_authority import (
    MIGRATION_STATES,
    MigrationState,
    PairAuthority,
    PairAuthorityDataError,
    PairAuthorityStore,
)
from aigateway.core.provider_access.writer_floor import claim_pair
from aigateway.routes.provider_access_http import selector_from_request

_MODELS = [
    "aigateway.core.auth.models",
    "aigateway.core.oauth.models",
    "aigateway.core.provider_access.models",
]
_RETIRED_STATE = "quarantined"


# --- X-Profile: refused by the parse, on every route --------------------------------------------


@pytest.mark.parametrize("raw", ["work", "default", "Default", "  work  ", "\tpersonal\n"])
def test_any_present_x_profile_value_is_refused_by_the_parse(raw: str) -> None:
    with pytest.raises(SelectorUnsupported):
        Selector.from_header(raw)


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_an_absent_or_blank_header_is_the_implicit_default(raw: str | None) -> None:
    assert Selector.from_header(raw) == Selector(DEFAULT_SELECTOR_NAME, explicit=False)


def test_the_parse_takes_no_policy() -> None:
    assert list(inspect.signature(Selector.from_header).parameters) == ["raw"]


def _request(app: FastAPI, *headers: tuple[bytes, bytes]) -> Request:
    return Request({"type": "http", "method": "GET", "headers": list(headers), "app": app})


def test_the_http_edge_refuses_a_present_header_without_any_app_policy() -> None:
    # WHY a bare app: nothing on `app.state` configures the refusal any more.
    app = FastAPI()

    assert selector_from_request(_request(app)) == Selector(DEFAULT_SELECTOR_NAME, explicit=False)
    with pytest.raises(SelectorUnsupported):
        selector_from_request(_request(app, (b"x-profile", b""), (b"x-profile", b"work")))


def test_the_composition_root_configures_no_selector_policy(authenticated_client: Any) -> None:
    assert not hasattr(authenticated_client.app.state, "selector_policy")


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (provider_access, "SelectorPolicy"),
        (provider_access, "SelectorUnknown"),
        (selector_module, "SelectorPolicy"),
        (types_module, "SelectorUnknown"),
    ],
)
def test_the_named_selection_vocabulary_is_gone(module: Any, name: str) -> None:
    assert not hasattr(module, name)
    assert name not in getattr(module, "__all__", ())


# --- the marker: exactly `none` and `migrated` ----------------------------------------------------


def test_the_marker_knows_exactly_none_and_migrated() -> None:
    assert frozenset({"none", "migrated"}) == MIGRATION_STATES
    assert set(typing.get_args(MigrationState)) == {"none", "migrated"}


def test_the_marker_view_and_its_writer_carry_no_note() -> None:
    assert "migration_note" not in {field.name for field in dataclasses.fields(PairAuthority)}
    assert "migration_note" not in inspect.signature(PairAuthorityStore.advance).parameters


@pytest_asyncio.fixture
async def account() -> AsyncIterator[Account]:
    async with tortoise_test_context(_MODELS):
        yield await Account.create(username="alice", password_hash="hash")


async def _plant(account: Account, *, state: str, note: str | None = None) -> None:
    # WHY a raw create: no writer can produce the retired state; an install may still hold one.
    await ProviderCredentialSlot.create(
        account_id=account.id,
        provider=PROVIDER,
        generation=1,
        migration_state=state,
        migration_note=note,
    )


@pytest.mark.asyncio
async def test_a_stored_quarantined_marker_is_refused_as_unknown(account: Account) -> None:
    await _plant(account, state=_RETIRED_STATE)
    store = PairAuthorityStore()

    with pytest.raises(PairAuthorityDataError) as on_read:
        await store.read(str(account.id), PROVIDER)
    with pytest.raises(PairAuthorityDataError) as on_list:
        await store.list(str(account.id))

    assert on_read.value.provider == on_list.value.provider == PROVIDER


@pytest.mark.asyncio
async def test_no_writer_publishes_the_retired_state(account: Account) -> None:
    with pytest.raises(ValueError, match="unknown pair authority state"):
        await PairAuthorityStore().advance(
            str(account.id),
            PROVIDER,
            expected_generation=0,
            migration_state=typing.cast(MigrationState, _RETIRED_STATE),
        )

    assert await ProviderCredentialSlot.all().count() == 0


@pytest.mark.asyncio
async def test_a_leftover_note_is_neither_read_nor_written(account: Account) -> None:
    # WHY untouched rather than cleared: L4c's upgrade refuses a noted row, so the note must
    # still be there for it to see (spec §4.3).
    await _plant(account, state="none", note="left by the retired backfill")
    store = PairAuthorityStore()

    observed = await store.read(str(account.id), PROVIDER)
    claimed = await claim_pair(observed)
    advanced = await store.advance(
        str(account.id), PROVIDER, expected_generation=claimed.generation, migration_state="none"
    )

    assert advanced == PairAuthority(str(account.id), PROVIDER, "none", None, 3)
    notes = await ProviderCredentialSlot.filter(account_id=account.id).values_list(
        "migration_note", flat=True
    )
    assert notes == ["left by the retired backfill"]


# --- every read path refuses a stored retired state ----------------------------------------------


@pytest.fixture
def h(
    authenticated_client: Any, credential_blobs: Any, monkeypatch: Any
) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _plant_retired(h: ConnectionBackedHarness) -> None:
    async def plant() -> None:
        await ProviderCredentialSlot.create(
            account_id=UUID(h.account_id),
            provider=PROVIDER,
            generation=1,
            migration_state=_RETIRED_STATE,
        )

    h.call(plant)


def test_resolve_refuses_a_stored_quarantined_marker_as_unknown(
    h: ConnectionBackedHarness,
) -> None:
    h.seed_connection(label="work")
    _plant_retired(h)

    with pytest.raises(PairAuthorityDataError):
        h.call(
            h.access.resolve,
            h.account_id,
            PROVIDER,
            Selector.from_header(None),
            plugin=ANTHROPIC,
        )


def test_availability_refuses_an_account_holding_a_quarantined_marker(
    h: ConnectionBackedHarness,
) -> None:
    _plant_retired(h)

    with pytest.raises(PairAuthorityDataError):
        h.call(h.access.availability, h.account_id)


def test_the_successor_inventory_refuses_a_quarantined_marker_as_unavailable(
    h: ConnectionBackedHarness,
) -> None:
    _plant_retired(h)

    with pytest.raises(CredentialAuthorityUnavailable) as refused:
        h.call(pair_inventory, h.client.app, h.account_id)

    assert refused.value.provider == PROVIDER


@pytest.mark.parametrize("row", range(1, 12))
def test_the_disposition_table_lists_a_conflict_only_for_rows_3_and_11(row: int) -> None:
    marker = PairAuthority("acct", PROVIDER, "none", None, 1)

    result = listing(PairDisposition(row, marker))

    assert isinstance(result, PairConflict) is (row in (3, 11))
