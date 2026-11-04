"""The effective Connection of each provider pair (OME-1138 close-out, L7a).

# FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §2 — at most one Connection
# of a pair is effective: the row the default chat resolve serves. The availability listing and
# `GET /v1/oauth/connections` both take it from `effective_connection_ids`, so `connected` and
# the flag the Local Engine writes by name the same row.
# INVARIANT: the rule is pure — no store, no secret, no clock. `flagged_connections` adds the two
# listings it reads (the markers, then the Connections, fenced by the pair generations; read
# again at most once) and writes nothing.
# STORY: as the Local Engine, I manage the Connection chat uses, not the one I happen to label.
"""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from typing import Any
from uuid import UUID

from ..endpoint_access import EndpointOperation, permits
from ..oauth.models import OAuthConnection
from .auth_mode import available_auth_modes
from .connection_authorize import oauth_connection_store
from .pair_authority import PairAuthority, PairAuthorityStore
from .types import CredentialStoreUnavailable

# WHY two, as the admin inventory reads: one re-read absorbs a write landing between the reads;
# a second moved marker in a row is refused for the caller to retry, never read through.
_SNAPSHOT_READ_ATTEMPTS = 2


def served_by_reference(pair: PairAuthority) -> bool:
    """Whether the default resolve serves this pair from its marker's effective reference."""
    return pair.migration_state == "migrated" and pair.effective_connection_id is not None


def no_auth_providers(app: Any) -> frozenset[str]:
    """The registered providers that declare only "none": they own no credential slot."""
    registry = getattr(app.state, "providers", None)
    if registry is None:
        return frozenset()
    return frozenset(
        plugin.custom_llm_provider
        for plugin in registry.all()
        if available_auth_modes(plugin) == ("none",)
    )


def visible_providers(app: Any, account_id: str) -> frozenset[str]:
    """The registered providers this account may VIEW (OME-1721): the pairs availability lists.

    # WHY VIEW stands for chat here: the endpoint policy grants every operation alike
    # (`RemoteEndpointAccess.permits`), so a provider hidden from VIEW is refused by chat too.
    """
    registry = getattr(app.state, "providers", None)
    if registry is None:
        return frozenset()
    return frozenset(
        plugin.custom_llm_provider
        for plugin in registry.all()
        if permits(
            app, plugin.custom_llm_provider, account_id=account_id, operation=EndpointOperation.VIEW
        )
    )


def effective_connection_ids(
    markers: Iterable[PairAuthority],
    connections: Iterable[OAuthConnection],
    *,
    no_auth: AbstractSet[str],
) -> dict[str, UUID]:
    """Each provider's effective Connection id; a provider without one is absent.

    # INVARIANT (D17, owner 2026-11-03): a provider in `no_auth` resolves targetless before its
    # marker is read, so neither a reference nor a stray active row of its name stands for it.
    # WHY the reference wins whatever its row's status: chat serves that row or refuses on it,
    # never on another active row of the pair.
    # WHY a reference to a row not given is still returned: the caller decides what an absent row
    # means — availability lists `not_connected`, the listing flags nothing.
    """
    referenced = {
        marker.provider: marker.effective_connection_id
        for marker in markers
        if served_by_reference(marker) and marker.effective_connection_id is not None
    }
    active: dict[str, list[UUID]] = {}
    for connection in connections:
        if connection.status == "active":
            active.setdefault(connection.provider, []).append(connection.id)
    effective: dict[str, UUID] = {}
    for provider in referenced.keys() | active.keys():
        if provider in no_auth:
            continue
        reference = referenced.get(provider)
        if reference is not None:
            effective[provider] = reference
        elif len(active[provider]) == 1:
            # WHY one and only one: two or more active rows are the ambiguity chat refuses (409).
            effective[provider] = active[provider][0]
    return effective


async def flagged_connections(
    app: Any,
    account_id: str,
    *,
    provider: str | None = None,
    status: str | None = None,
) -> list[tuple[OAuthConnection, bool]]:
    """The caller's Connections for `GET /v1/oauth/connections`, each with whether it is effective.

    # WHY one listing of every status, filtered here: the flag is the pair's — its marker and its
    # active rows decide it, which no `provider` or `status` filter changes — but the unfiltered
    # listing must also show a `revoked` effective row, which the store's default listing hides.
    # INVARIANT (spec §8.3): without a `status` filter, `revoked` rows stay hidden as the store
    # hides them, except the effective one, which the Local Engine must see to repair it.
    # INVARIANT: an unknown stored marker state fails the call (`PairAuthorityDataError`), as it
    # fails chat; nothing is flagged by a guessed owner.
    # INVARIANT (owner, 2026-11-03; OME-1721): only a provider availability lists — registered and
    # visible to the caller — has an effective row; a row of any other provider is unflagged.
    """
    markers, connections = await _one_snapshot(app, account_id)
    visible = visible_providers(app, account_id)
    effective = {
        provider: connection_id
        for provider, connection_id in effective_connection_ids(
            markers, connections, no_auth=no_auth_providers(app)
        ).items()
        if provider in visible
    }
    flagged = [
        (connection, effective.get(connection.provider) == connection.id)
        for connection in connections
    ]
    return [
        (connection, is_effective)
        for connection, is_effective in flagged
        if (provider is None or connection.provider == provider)
        and (
            connection.status == status
            if status is not None
            else connection.status != "revoked" or is_effective
        )
    ]


async def _one_snapshot(
    app: Any, account_id: str
) -> tuple[tuple[PairAuthority, ...], list[OAuthConnection]]:
    """The markers and the Connections as one snapshot, fenced by the pair generations.

    # WHY the fence: the two listings are separate reads. A delete committed between them clears
    # the reference and revokes its row, so the old reference would flag the revoked row and the
    # Engine would create a second active row beside the one chat serves. Every marker write moves
    # its pair's generation, so an unchanged fence after the Connection read proves the markers
    # still stand — the admin inventory's fence (`pair_admin.pair_inventory`).
    """
    store = PairAuthorityStore()
    for _attempt in range(_SNAPSHOT_READ_ATTEMPTS):
        markers = await store.list(account_id)
        connections = await oauth_connection_store(app).list(account_id, include_revoked=True)
        fence = tuple((marker.provider, marker.generation) for marker in markers)
        if await store.generations(account_id) == fence:
            return markers, connections
    raise CredentialStoreUnavailable("connections", operation="list")
