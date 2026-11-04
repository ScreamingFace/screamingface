"""Row rules of the Local AI Gateway adapter (OME-1138 close-out, L7b).

# FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §3-§4 — the Local Engine
# manages the Connection chat uses: the row the gateway flags `effective` (`E`). These rules pick
# `E`, check the listing, and name the rows each write targets; `aigateway.py` keeps the I/O.
# INVARIANT: the rules are pure — no request, no status. Every public status comes from
# `GET /v1/provider-access`; nothing here derives one from a row's lifecycle.
# STORY: as a Local Engine user, the connection I see and manage is the one chat uses.
"""

from __future__ import annotations

import functools
import logging
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

logger = logging.getLogger(__name__)

# Inter-service contract: the label of a row the Engine creates (Anthropic requires a label on
# both creates) and the mark the stale-row repair reads. Selection never reads it while the
# gateway flags `effective`; only the version-skew fallback below does.
MANAGED_LABEL = "screamingface"

UpstreamConnectionStatus = Literal["pending", "active", "expired", "revoked", "error"]

# WHY these two: the gateway's `PUT …/api-key` re-keys an API-key row that is working or in
# `error` (its designed repair); any other unusable `E` is replaced by a labelled create.
_REKEYABLE = frozenset({"active", "error"})


@dataclass(frozen=True, slots=True)
class ConnectionRow:
    id: UUID
    provider: str
    label: str
    status: UpstreamConnectionStatus
    auth_type: AuthMethod
    account_label: str | None
    # None when the row carries no `effective` field: a gateway older than L7a, or a write's
    # response, which never carries it.
    effective: bool | None = None


@dataclass(frozen=True, slots=True)
class Selection:
    """One listed provider's rows as spec §3 reads them."""

    effective: ConnectionRow | None  # `E`
    active: int  # `A`, the provider's `active` rows
    stale: tuple[ConnectionRow, ...]  # its non-active `screamingface` rows other than `E`
    label_held: bool  # an `active` row other than `E` holds `screamingface`


@dataclass(frozen=True, slots=True)
class Plan:
    """One operation's writes: remove these rows first, then re-key one in place or create."""

    remove: tuple[ConnectionRow, ...] = ()
    rekey: ConnectionRow | None = None


def select(rows: Sequence[ConnectionRow], providers: Iterable[str]) -> dict[str, Selection]:
    """Each listed provider's selection; a listing that breaks the contract is a bad response.

    # INVARIANT (spec §3): the field-presence check covers the whole response, but the
    # per-provider checks run only for `providers` — the ones `/v1/providers` lists. A row of any
    # other provider (a no-auth provider's stray `active` row) is never selected or checked.
    """
    flagged = {row.effective is not None for row in rows}
    if len(flagged) > 1:
        # WHY: the gateway sets the field on every row it lists; a mix is no known gateway.
        raise ConnectionBadResponse()
    label_rule = flagged == {False}
    if label_rule:
        _note_gateway_predates_effective()
    return {provider: _selection(rows, provider, label_rule=label_rule) for provider in providers}


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
    return Plan(remove=selection.stale)


def oauth_start_plan(selection: Selection) -> Plan:
    """`start_oauth`: the callback replaces an unusable `E`; repair first, then start."""
    effective = selection.effective
    if effective is not None:
        _refuse_pending(effective)
        if effective.status == "active":
            raise ConnectionAlreadyConnected()
        return _replace_plan(selection)
    _refuse_ambiguity(selection)
    return Plan(remove=selection.stale)


def disconnect_plan(selection: Selection) -> Plan:
    """`disconnect` removes `E` whatever its label or status; without one, only stale rows."""
    if selection.effective is not None:
        return Plan(remove=(selection.effective,))
    _refuse_ambiguity(selection)
    return Plan(remove=selection.stale)


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
    return Plan(remove=selection.stale)


def _selection(rows: Sequence[ConnectionRow], provider: str, *, label_rule: bool) -> Selection:
    own = [row for row in rows if row.provider == provider]
    active = sum(row.status == "active" for row in own)
    managed = [row for row in own if row.label == MANAGED_LABEL]
    if label_rule:
        # WHY (Q3 option A, owner 2026-11-02): against a gateway older than L7a the Engine keeps
        # today's label rule for one Engine release. Remove this branch,
        # `_note_gateway_predates_effective` and the label rule of `select` in the release after
        # L7b ships.
        if len(managed) > 1:
            raise ConnectionConflict()
        effective = managed[0] if managed else None
    else:
        chosen = [row for row in own if row.effective]
        if len(chosen) > 1:
            raise ConnectionBadResponse()
        effective = chosen[0] if chosen else None
        if effective is None and active == 1:
            # WHY: the gateway's rule makes a single active row effective (spec §2).
            raise ConnectionBadResponse()
    others = [row for row in managed if row is not effective]
    return Selection(
        effective=effective,
        active=active,
        stale=tuple(row for row in others if row.status != "active"),
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


@functools.cache
def _note_gateway_predates_effective() -> None:
    # WHY once per process: a running Engine's gateway does not change version, and one notice
    # per listing would drown the log.
    logger.warning(
        "AI Gateway lists Connections without the `effective` flag; the Local Engine selects "
        "the row labelled %r until the gateway is upgraded",
        MANAGED_LABEL,
    )


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
