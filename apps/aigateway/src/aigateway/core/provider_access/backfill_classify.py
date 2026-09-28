"""Classify every `(account, provider)` pair before any authority changes (OME-1208, S4).

# FEATURE: Stage B "Classification before authority" — the read-only half of
# `python -m aigateway.migrate_profiles`: for each pair the legacy documents, the non-revoked
# Connections and the pair marker decide a disposition from the card's table; nothing is written.
# INVARIANT (D3, D11): "proven the same" compares the DECRYPTED credential documents in process —
# never a name or a label; an unprovable pair is quarantined or left on legacy authority, never
# guessed; revoked rows are invisible (never resurrected); a plan carries no secret.
# AIDEV-NOTE: a plan is a snapshot — `generation` is the marker generation the writer must expect;
# `backfill_apply.py` publishes it through `PairAuthorityStore.advance`, whose compare-and-set turns
# a stale plan (a concurrent writer moved the pair) into `PairAuthorityConflict`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from aigateway.core.credential_blob.store import CredentialBlobStore
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState
from aigateway.core.secrets.mixin import SecretDecryptionError

from .pair_authority import UNMARKED_GENERATION, PairAuthority, PairAuthorityStore

Disposition = Literal["migrated", "quarantined", "none"]
Action = Literal["create", "name", "quarantine", "skip"]
BlobState = Literal["ok", "missing", "undecodable", "malformed"]
_Address = dict[str, str]
_Verdict = tuple[Disposition, str, Action, UUID | None, Profile | None]


@dataclass(frozen=True)
class BackfillContext:
    """The three reads the tool needs — the app's stores, or a CLI-built equivalent."""

    credential_store: CredentialBlobStore
    profile_index: ProfileIndexStore
    # WHY duck-typed: only `.get(provider)` is used, and the CLI builds a bare registry.
    providers: Any

    @classmethod
    def from_app(cls, app: Any) -> BackfillContext:
        return cls(app.state.credential_store, app.state.profile_index, app.state.providers)

    @classmethod
    def from_stores(cls, credential_store: CredentialBlobStore, providers: Any) -> BackfillContext:
        # WHY here and not in the CLI: the A2 import boundary lets only this package (and the
        # legacy modules it adapts) name `ProfileIndexStore`; the CLI is a consumer of the port.
        return cls(
            credential_store, ProfileIndexStore(credential_store=credential_store), providers
        )


@dataclass(frozen=True)
class PairPlan:
    """One pair's disposition and the write that publishes it (`skip` = nothing to write)."""

    account_id: str
    provider: str
    disposition: Disposition
    category: str
    action: Action
    generation: int
    connection_id: UUID | None = None
    profile: Profile | None = None
    alias_documents: int = 0


async def classify_account(ctx: BackfillContext, account_id: str) -> tuple[PairPlan, ...]:
    """Every pair of the account, by provider — three reads, then blob reads per pair."""
    documents = await ctx.profile_index.list(account_id)
    connections = await OAuthConnectionStore().list(account_id)
    markers = {pair.provider: pair for pair in await PairAuthorityStore().list(account_id)}
    providers = sorted(
        {d.provider for d in documents} | {c.provider for c in connections} | set(markers)
    )
    plans: list[PairPlan] = []
    for provider in providers:
        marker = markers.get(provider) or PairAuthority(
            account_id, provider, "none", None, UNMARKED_GENERATION, None
        )
        plans.append(
            await _classify(
                ctx,
                marker,
                [d for d in documents if d.provider == provider],
                [c for c in connections if c.provider == provider],
            )
        )
    return tuple(plans)


async def _classify(
    ctx: BackfillContext,
    marker: PairAuthority,
    documents: list[Profile],
    connections: list[OAuthConnection],
) -> PairPlan:
    account_id, provider = marker.account_id, marker.provider
    plugin = ctx.providers.get(provider)
    credential_provider = credential_service_provider_for(plugin, provider)
    if marker.migration_state == "migrated":
        effective = next((c for c in connections if c.id == marker.effective_connection_id), None)
        return PairPlan(
            account_id,
            provider,
            "migrated",
            "already_migrated",
            "skip",
            marker.generation,
            connection_id=marker.effective_connection_id,
            alias_documents=_alias_documents(documents, effective, credential_provider, account_id),
        )
    if plugin is None:
        verdict: _Verdict = ("none", "provider_unknown", "skip", None, None)
    elif not documents:
        verdict = _connection_only(connections)
    elif len(documents) > 1:
        verdict = ("none", "several_documents", "skip", None, None)
    else:
        verdict = await _with_profile(
            ctx, account_id, credential_provider, documents[0], connections
        )
    disposition, category, action, connection_id, profile = verdict
    if marker.migration_state == "quarantined" and disposition == "quarantined":
        # WHY: a pair still in conflict stays as it is — republishing the same verdict is a write
        # for nothing; a pair that became clean is planned from the quarantine's generation.
        action = "skip"
    return PairPlan(
        account_id,
        provider,
        disposition,
        category,
        action,
        marker.generation,
        connection_id=connection_id,
        profile=profile,
    )


def _connection_only(connections: list[OAuthConnection]) -> _Verdict:
    active = [c for c in connections if c.status == "active"]
    if len(connections) == 1 and active:
        return "migrated", "connection_only", "name", connections[0].id, None
    if len(active) > 1:
        # WHY (D12 Stage B rule, owner 2026-09-22): several active Connections keep today's label
        # resolution and its 409; Stage B does not pick one.
        return "none", "several_active_connections", "skip", None, None
    # WHY: no active row, or one active beside a pending/error stray whose flow may still complete
    # into a second active row — the policy the owner has not decided (D-S2b4-6).
    return "none", "connections_unsettled", "skip", None, None


async def _with_profile(
    ctx: BackfillContext,
    account_id: str,
    credential_provider: str,
    document: Profile,
    connections: list[OAuthConnection],
) -> _Verdict:
    if document.state != ProfileState.AUTHENTICATED:
        return "none", f"profile_{document.state.value}", "skip", None, None
    address = credential_locator_for(credential_provider, account_id, document.name)
    state, profile_document = await _read_document(ctx.credential_store, address)
    if state != "ok":
        # INVARIANT (card): a missing or undecodable blob is never promoted to an active Connection.
        return "none", f"profile_credential_{state}", "skip", None, None
    if not connections:
        return "migrated", "profile_only", "create", None, document
    if len(connections) > 1:
        return "quarantined", "several_connections", "quarantine", None, None
    (connection,) = connections
    if connection.status != "active":
        return "quarantined", f"connection_{connection.status}", "quarantine", None, None
    return await _against_connection(
        ctx, connection, address, profile_document, credential_provider, account_id
    )


async def _against_connection(
    ctx: BackfillContext,
    connection: OAuthConnection,
    profile_address: _Address,
    profile_document: dict[str, Any] | None,
    credential_provider: str,
    account_id: str,
) -> _Verdict:
    """The one ACTIVE Connection beside an authenticated Profile: same credential, or not proven."""
    locator = _locator_of(connection, credential_provider, account_id)
    if locator == profile_address:
        return "migrated", "profile_mapped", "name", connection.id, None
    state, connection_document = await _read_document(ctx.credential_store, locator)
    if state != "ok":
        return "quarantined", f"connection_credential_{state}", "quarantine", None, None
    if connection_document == profile_document:
        return "migrated", "profile_connection_same", "name", connection.id, None
    return "quarantined", "credentials_differ", "quarantine", None, None


def _locator_of(connection: OAuthConnection, credential_provider: str, account_id: str) -> _Address:
    locator = connection.credential_locator
    if (
        isinstance(locator, dict)
        and isinstance(locator.get("service"), str)
        and isinstance(locator.get("account"), str)
    ):
        return {"service": locator["service"], "account": locator["account"]}
    # WHY: S1's fallback — a malformed locator reads at the Connection's own UUID address.
    return credential_locator_for(credential_provider, account_id, connection.id)


async def _read_document(
    store: CredentialBlobStore, address: _Address
) -> tuple[BlobState, dict[str, Any] | None]:
    """Decrypt one blob in process for comparison only — the document never leaves this module."""
    try:
        raw = await store.read(address["service"], address["account"])
    except SecretDecryptionError:
        return "undecodable", None
    if raw is None:
        return "missing", None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return "malformed", None
    if not isinstance(parsed, dict):
        return "malformed", None
    return "ok", parsed


def _alias_documents(
    documents: list[Profile],
    effective: OAuthConnection | None,
    credential_provider: str,
    account_id: str,
) -> int:
    """Documents whose own blob address is NOT the effective Connection's — R1 would miss them."""
    if effective is None:
        return len(documents)
    locator = _locator_of(effective, credential_provider, account_id)
    return sum(
        credential_locator_for(credential_provider, account_id, d.name) != locator
        for d in documents
    )


__all__ = ["Action", "BackfillContext", "Disposition", "PairPlan", "classify_account"]
