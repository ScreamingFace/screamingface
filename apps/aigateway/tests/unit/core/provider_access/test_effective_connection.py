"""The effective Connection of a provider pair (OME-1138 close-out, L7a).

# FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §2 — at most one Connection of
# a pair is effective: the row the default chat resolve serves. A provider that declares only
# `none` has none, whatever its marker or rows; a `migrated` pair with a reference has the
# referenced row, whatever its status; any other pair has its single `active` row, and none for
# zero or two or more.
# INVARIANT: over L1's agreement cases, the effective row is exactly the Connection the default
# resolve serves, and there is none where resolve refuses.
# STORY: as the Local Engine, I manage the Connection chat uses, not the one I happen to label.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER
from test_availability_follows_resolve import MARKERS, REFUSED, ROWS, _active, _marked

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.provider_access import (
    MigrationState,
    PairAuthority,
    Selector,
    effective_connection_ids,
    flagged_connections,
)
from aigateway.core.provider_access.connection_authority import MigratedBacking
from tests.unit.seed_state import SeedState

STATUSES = ["active", "pending", "error", "expired", "revoked"]
A, B, C = uuid4(), uuid4(), uuid4()


def _row(connection_id: UUID, status: str, provider: str = PROVIDER) -> OAuthConnection:
    return OAuthConnection(
        id=connection_id, provider=provider, label=str(connection_id), status=status
    )


def _marker(
    state: MigrationState, reference: UUID | None = None, provider: str = PROVIDER
) -> PairAuthority:
    return PairAuthority("account", provider, state, reference, 1)


def _effective_of(
    markers: list[PairAuthority],
    rows: list[OAuthConnection],
    *,
    no_auth: frozenset[str] = frozenset(),
) -> UUID | None:
    return effective_connection_ids(markers, rows, no_auth=no_auth).get(PROVIDER)


# --- the rule ------------------------------------------------------------------------------------

UNMARKED: dict[str, list[PairAuthority]] = {
    "absent": [],
    "none": [_marker("none")],
    "migrated-without-reference": [_marker("migrated")],
}
LABEL_RULE: dict[str, tuple[list[OAuthConnection], UUID | None]] = {
    "one-active": ([_row(A, "active")], A),
    "one-active-beside-the-rest": (
        [_row(A, "active"), _row(B, "pending"), _row(C, "error")],
        A,
    ),
    "two-active": ([_row(A, "active"), _row(B, "active")], None),
    "pending-only": ([_row(A, "pending")], None),
    "error-only": ([_row(A, "error")], None),
    "expired-only": ([_row(A, "expired")], None),
    "revoked-only": ([_row(A, "revoked")], None),
    "no-rows": ([], None),
}


@pytest.mark.parametrize("marker", list(UNMARKED))
@pytest.mark.parametrize("case", list(LABEL_RULE))
def test_a_pair_no_reference_serves_has_its_single_active_row(marker: str, case: str) -> None:
    rows, expected = LABEL_RULE[case]

    assert _effective_of(UNMARKED[marker], rows) == expected


@pytest.mark.parametrize("status", STATUSES)
def test_a_migrated_reference_names_the_effective_row_whatever_its_status(status: str) -> None:
    # WHY beside an active row: the reference decides, not the label rule — chat serves the
    # referenced row (or refuses on it), never the other one.
    rows = [_row(A, status), _row(B, "active")]

    assert _effective_of([_marker("migrated", A)], rows) == A


def test_a_reference_to_a_row_not_listed_still_names_it() -> None:
    # WHY: the caller decides what an absent row means — availability reads it by id, the
    # listing flags nothing — so the rule does not guess.
    assert _effective_of([_marker("migrated", C)], [_row(A, "active")]) == C


@pytest.mark.parametrize(
    "markers",
    [[], [_marker("none")], [_marker("migrated", A)]],
    ids=["unmarked", "none", "migrated-reference"],
)
def test_a_provider_declaring_only_none_has_no_effective_row(
    markers: list[PairAuthority],
) -> None:
    # INVARIANT (spec §2, owner 2026-11-03): a stray active row, or a legacy reference to one,
    # never stands for a provider that owns no credential slot (D17).
    rows = [_row(A, "active")]

    assert _effective_of(markers, rows, no_auth=frozenset({PROVIDER})) is None


def test_each_provider_is_decided_on_its_own_rows_and_marker() -> None:
    rows = [
        _row(A, "active"),
        _row(B, "active", provider="openai"),
        _row(C, "active", provider="openai"),
        _row(uuid4(), "active", provider="ollama"),
    ]
    reference = uuid4()
    markers = [_marker("migrated", reference, provider="codex")]

    effective = effective_connection_ids(markers, rows, no_auth=frozenset({"ollama"}))

    assert effective == {PROVIDER: A, "codex": reference}


# --- agreement with resolve ----------------------------------------------------------------------


@pytest.fixture
def h(
    authenticated_client: Any, credential_blobs: Any, monkeypatch: Any
) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _served(h: ConnectionBackedHarness) -> str | None:
    """The Connection the default chat resolve serves, or None when it refuses."""
    try:
        target = h.call(
            h.access.resolve, h.account_id, PROVIDER, Selector.from_header(None), plugin=ANTHROPIC
        )
    except REFUSED:
        return None
    backing = target._backing
    connection = backing.connection if isinstance(backing, MigratedBacking) else backing
    return str(connection.id) if isinstance(connection, OAuthConnection) else None


def _flagged(h: ConnectionBackedHarness) -> str | None:
    listed = h.call(flagged_connections, h.client.app, h.account_id)
    ids = [str(row.id) for row, effective in listed if effective and row.provider == PROVIDER]
    assert len(ids) <= 1
    return ids[0] if ids else None


@pytest.mark.parametrize("marker", MARKERS)
@pytest.mark.parametrize("rows", list(ROWS))
def test_the_effective_row_is_the_row_the_default_resolve_serves(
    h: ConnectionBackedHarness, rows: str, marker: str
) -> None:
    seed, _status = ROWS[rows]
    seed(h)
    _marked(h, marker)

    assert _flagged(h) == _served(h)


@pytest.mark.parametrize("beside", [False, True], ids=["alone", "beside-an-active-row"])
def test_a_migrated_reference_is_the_row_the_default_resolve_serves(
    h: ConnectionBackedHarness, beside: bool
) -> None:
    h.seed_credential(state=SeedState.AUTHENTICATED)
    if beside:
        _active(h, "work")

    assert _flagged(h) == _served(h) == h.migrated["default"]


def test_a_reference_to_a_revoked_row_lists_not_connected_beside_an_active_row(
    h: ConnectionBackedHarness,
) -> None:
    # WHY: availability reads no row by id — a referenced row its listing hides is `revoked`, and
    # chat refuses on it while the reference stands, so the active row beside it serves nothing.
    h.seed_credential(state=SeedState.AUTHENTICATED)
    _active(h, "work")
    revoked = h.call(OAuthConnectionStore().get, h.account_id, h.migrated["default"])
    h.call(OAuthConnectionStore().mark_revoked, revoked, "gone")
    statuses = {row.provider: row.status for row in h.call(h.access.availability, h.account_id)}

    assert statuses[PROVIDER] == "not_connected"
    assert _served(h) is None
    assert _flagged(h) == h.migrated["default"]
