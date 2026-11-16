"""Row rules of the Local AI Gateway adapter (OME-1138 close-out, L7b).

# FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §3-§4 — the Local Engine
# manages the Connection chat uses: the row the gateway flags `effective` (`E`). These rules pick
# `E`, check the listing, and name the rows each write targets; `aigateway.py` keeps the I/O.
# INVARIANT: the rules are pure — no request, no status. Every public status comes from
# `GET /v1/provider-access`; nothing here derives one from a row's lifecycle.
# STORY: as a Local Engine user, the connection I see and manage is the one chat uses.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from screamingface_engine.connections.port import (
    AuthMethod,
    ConnectionAlreadyConnected,
    ConnectionBadResponse,
    ConnectionConflict,
)

# Inter-service contract: the label of a row the Engine creates (Anthropic requires a label on
# both creates) and the mark the stale-row repair reads. Choosing the effective row never reads
# it; repair planning (`Selection.stale`, `Selection.label_held`) still does.
MANAGED_LABEL = "screamingface"

UpstreamConnectionStatus = Literal["pending", "active", "expired", "revoked", "error"]

# WHY these two: the gateway's `PUT …/api-key` re-keys an API-key row that is working or in
# `error` (its designed repair); any other unusable `E` is replaced by a labelled create.
_REKEYABLE = frozenset({"active", "error"})
# WHY these two (spec §2a): the statuses the gateway's conditional delete takes, and the only ones a
# `screamingface` row serving nothing can have — an OAuth `error` row and every `revoked` row are
# parked under a placeholder label, and nothing writes `expired`.
_STALE = frozenset({"pending", "error"})


@dataclass(frozen=True, slots=True)
class ConnectionRow:
    id: UUID
    provider: str
    label: str
    status: UpstreamConnectionStatus
    auth_type: AuthMethod
    account_label: str | None
    # None only for a write's response, which never carries the field; `select` refuses a listed
    # row without it.
    effective: bool | None = None


@dataclass(frozen=True, slots=True)
class Selection:
    """One listed provider's rows as spec §3 reads them."""

    effective: ConnectionRow | None  # `E`
    active: int  # `A`, the provider's `active` rows
    stale: tuple[ConnectionRow, ...]  # its `pending`/`error` `screamingface` rows other than `E`
    label_held: bool  # an `active` row other than `E` holds `screamingface`


@dataclass(frozen=True, slots=True)
class Plan:
    """One operation's writes: retire `E` or repair stale rows first, then re-key or create."""

    retire: ConnectionRow | None = None  # `E`, deleted plainly: only `disconnect` retires it
    repair: tuple[ConnectionRow, ...] = ()  # each deleted only while it has its listed status
    rekey: ConnectionRow | None = None


def select(rows: Sequence[ConnectionRow], providers: Iterable[str]) -> dict[str, Selection]:
    """Each listed provider's selection; a listing that breaks the contract is a bad response.

    # INVARIANT (spec §3): the field-presence check covers the whole response, but the
    # per-provider checks run only for `providers` — the ones `/v1/providers` lists. A row of any
    # other provider (a no-auth provider's stray `active` row) is never selected or checked.
    """
    if any(row.effective is None for row in rows):
        # WHY: the gateway sets the field on every row it lists. A gateway older than L7a lists
        # none; L7b's label-rule fallback for it served one Engine release (spec §4, OME-1832).
        raise ConnectionBadResponse()
    return {provider: _selection(rows, provider) for provider in providers}


def api_key_plan(selection: Selection) -> Plan:
    """`connect` (API key), by spec §3's create and repair table."""
    if selection.effective is not None:
        return _api_key_plan_over(selection, selection.effective)
    _refuse_ambiguity(selection)
    own = next(
        (row for row in selection.stale if row.auth_type == "api_key" and row.status == "error"),
        None,
    )
    if own is not None:
        # INVARIANT (spec §3, accepted limitation): a row the user named `screamingface` cannot be
        # told from the Engine's; in `error` it is re-keyed in place and turns `active`.
        return Plan(rekey=own)
    return Plan(repair=selection.stale)


def oauth_start_plan(selection: Selection) -> Plan:
    """`start_oauth`: the callback replaces an unusable `E`; repair first, then start."""
    effective = selection.effective
    if effective is not None:
        _refuse_pending(effective)
        if effective.status == "active":
            raise ConnectionAlreadyConnected()
        return _replace_plan(selection)
    _refuse_ambiguity(selection)
    return Plan(repair=selection.stale)


def disconnect_plan(selection: Selection) -> Plan:
    """`disconnect` removes `E` whatever its label or status; without one, only stale rows."""
    if selection.effective is not None:
        return Plan(retire=selection.effective)
    _refuse_ambiguity(selection)
    return Plan(repair=selection.stale)


def _api_key_plan_over(selection: Selection, effective: ConnectionRow) -> Plan:
    _refuse_pending(effective)
    if effective.auth_type == "api_key" and effective.status in _REKEYABLE:
        return Plan(rekey=effective)
    if effective.status == "active":
        # WHY: changing an active OAuth Connection's method takes an explicit disconnect.
        raise ConnectionAlreadyConnected()
    return _replace_plan(selection)


def _replace_plan(selection: Selection) -> Plan:
    """The labelled create that replaces an unusable `E`, once no other row holds the label.

    # WHY: the gateway's create replaces an unusable effective row, even one holding the label
    # (`effective_to_replace`, `core/provider_access/connection_native.py`), but refuses a label
    # another row holds (409 `label_conflict`). A pre-L7b Engine left its `screamingface` row
    # beside a migrated `E`, so without this every attempt would fail (owner, 2026-11-04).
    """
    if selection.label_held:
        # WHY refuse, not remove: an active row may serve the user elsewhere. Disconnecting `E`
        # makes it the effective row; refuse before any write and before the key leaves.
        raise ConnectionConflict()
    return Plan(repair=selection.stale)


def _selection(rows: Sequence[ConnectionRow], provider: str) -> Selection:
    own = [row for row in rows if row.provider == provider]
    active = sum(row.status == "active" for row in own)
    chosen = [row for row in own if row.effective]
    if len(chosen) > 1:
        raise ConnectionBadResponse()
    effective = chosen[0] if chosen else None
    if effective is None and active == 1:
        # WHY: the gateway's rule makes a single active row effective (spec §2).
        raise ConnectionBadResponse()
    managed = [row for row in own if row.label == MANAGED_LABEL]
    others = [row for row in managed if row is not effective]
    return Selection(
        effective=effective,
        active=active,
        stale=tuple(row for row in others if row.status in _STALE),
        label_held=any(row.status == "active" for row in others),
    )


def _refuse_pending(effective: ConnectionRow) -> None:
    if effective.status == "pending":
        # WHY (R6): a pending effective row is usable — the user finishes or removes that sign-in
        # in the gateway; the Engine neither replaces nor deletes it here.
        raise ConnectionConflict()


def _refuse_ambiguity(selection: Selection) -> None:
    if selection.active >= 2:
        # WHY: no effective row and two or more active ones is the ambiguity chat refuses (409);
        # the Engine adds no further row and removes none of the user's.
        raise ConnectionConflict()


__all__ = [
    "MANAGED_LABEL",
    "ConnectionRow",
    "Plan",
    "Selection",
    "UpstreamConnectionStatus",
    "api_key_plan",
    "disconnect_plan",
    "oauth_start_plan",
    "select",
]
