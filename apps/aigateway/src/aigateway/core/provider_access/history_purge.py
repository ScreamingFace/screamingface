"""Purge the retired Profile storage from `credential_blobs` (OME-1138 Stage E, E5b).

# FEATURE: Stage E history cleanup — the work half of `python -m aigateway.purge_profile_history`:
# every Profile index row goes, and every provider-credential blob no Connection row addresses, one
# account per transaction; with `--all`, then the blobs of deleted accounts, then the legacy global
# index row.
# INVARIANT (C2): a blob any Connection row of any status and any account addresses stays, at the
# whole `(service, account)` address its strategy resolves (`credential_blob_address`), never one
# assembled from the locator text; a row outside a loaded provider's credential namespace stays,
# and is counted.
# INVARIANT (C3): an account's transaction first takes `SELECT … FOR UPDATE` on its `accounts` row.
# Every reference creator inserts a row whose foreign key names the account, which takes
# `FOR KEY SHARE` on it, so on PostgreSQL a creator and the purge never interleave. On SQLite the
# lock is a no-op and the gateway must be stopped (C7).
# INVARIANT (C4): an account the purge cannot prove is skipped whole, with a reason, never partly
# purged; there is no override.
# INVARIANT (C5): no value is read but the index documents; the report and the journal carry account
# ids, kinds, counts and reasons, never a service string, credential name, value or ciphertext.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TextIO
from uuid import UUID

from tortoise.queryset import QuerySet
from tortoise.transactions import in_transaction

from aigateway.core.auth.models import Account
from aigateway.core.credential_blob.model import CredentialBlob
from aigateway.core.oauth.store import credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.profile_index import (
    INDEX_CREDENTIAL_SERVICE,
    LEGACY_INDEX_ACCOUNT,
    ProfileIndexStore,
    index_account_for,
)
from aigateway.core.profile_models import Profile
from aigateway.core.secrets.mixin import SecretDecryptionError

from .backfill_apply import all_account_ids
from .history_references import Address, read_references
from .pair_authority import PairAuthorityStore

PurgeMode = Literal["dry-run", "apply"]
PURGE_MODES: tuple[PurgeMode, ...] = ("dry-run", "apply")
LegacyIndex = Literal["purged", "absent", "kept_unreadable", "kept_listed_account_skipped"]

INDEX_ROWS = "index_rows"
NAME_SHAPED = "name_shaped_blobs"
UUID_SHAPED = "uuid_shaped_blobs"
DELETED_ACCOUNT = "deleted_account_blobs"
ACCOUNT_KINDS = (INDEX_ROWS, NAME_SHAPED, UUID_SHAPED)
_UNRECOGNISED = "unrecognised"
_NAMESPACE = "aigateway"


class _Skip(Exception):
    """The account cannot be proven; `reason` is a fixed word, never a stored value."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PurgeContext:
    """The reads the purge needs, built by the CLI from its own registry and stores."""

    # WHY duck-typed: `credential_blob_address` reads `state.credential_store` (and an optional
    # `<provider>_http_factory`) from it; the CLI hands it a bare namespace, a test the real app.
    app: Any
    # WHY duck-typed: only `.get(provider)` and `.all()` are used.
    providers: Any
    profile_index: ProfileIndexStore

    @classmethod
    def build(cls, app: Any, providers: Any) -> PurgeContext:
        store = app.state.credential_store
        return cls(app, providers, ProfileIndexStore(credential_store=store))

    def namespaces(self) -> tuple[str, ...]:
        """Every loaded provider's credential namespace; an alias shares its target's."""
        return tuple(
            sorted(
                {
                    credential_service_provider_for(plugin, plugin.custom_llm_provider)
                    for plugin in self.providers.all()
                }
            )
        )


@dataclass(frozen=True)
class AccountPurge:
    account_id: str
    rows: dict[str, int]
    skipped: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"account_id": self.account_id, "rows": dict(self.rows), "skipped": self.skipped}


@dataclass(frozen=True)
class SweepResult:
    """`--all` only: the rows of deleted accounts, and the rows the purge does not recognise."""

    index_rows: int = 0
    deleted_account_blobs: int = 0
    kept_unrecognised_rows: int = 0


@dataclass(frozen=True)
class PurgeReport:
    mode: PurgeMode
    accounts: tuple[AccountPurge, ...]
    # WHY optional: the sweep and the legacy row are `--all` only; `None` says "not in scope".
    sweep: SweepResult | None = None
    legacy_index: LegacyIndex | None = None

    def counts(self) -> dict[str, int]:
        sweep = self.sweep or SweepResult()

        def total(kind: str) -> int:
            return sum(account.rows[kind] for account in self.accounts)

        return {
            INDEX_ROWS: total(INDEX_ROWS) + sweep.index_rows + int(self.legacy_index == "purged"),
            NAME_SHAPED: total(NAME_SHAPED),
            UUID_SHAPED: total(UUID_SHAPED),
            DELETED_ACCOUNT: sweep.deleted_account_blobs,
            "kept_unrecognised_rows": sweep.kept_unrecognised_rows,
            "skipped_accounts": sum(account.skipped is not None for account in self.accounts),
        }

    def refused(self) -> bool:
        """Something was kept for a reason the owner must look at before calling it clean."""
        legacy_kept = self.legacy_index is not None and self.legacy_index.startswith("kept_")
        return legacy_kept or any(account.skipped is not None for account in self.accounts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "scope": "account" if self.sweep is None else "all",
            "counts": self.counts(),
            "accounts": [account.to_dict() for account in self.accounts],
            "legacy_index": self.legacy_index,
        }


async def run_purge(
    ctx: PurgeContext,
    *,
    mode: PurgeMode,
    account_ids: Sequence[str] | None,
    journal: TextIO | None = None,
) -> PurgeReport:
    """The named accounts, or with ``account_ids=None`` (`--all`) every account, then the rows of
    deleted accounts, then the legacy global index row."""
    if mode not in PURGE_MODES:
        raise ValueError(f"unknown purge mode {mode!r}")
    apply = mode == "apply"
    ids = await all_account_ids() if account_ids is None else tuple(account_ids)
    results: list[AccountPurge] = []
    for account_id in ids:
        result = await purge_account(ctx, account_id, apply=apply)
        results.append(result)
        _journal(journal, result.to_dict())
    sweep: SweepResult | None = None
    legacy: LegacyIndex | None = None
    if account_ids is None:
        sweep = await sweep_deleted_accounts(ctx, apply=apply)
        skipped = {result.account_id for result in results if result.skipped is not None}
        legacy = await purge_legacy_index(ctx, skipped=skipped, apply=apply)
    report = PurgeReport(mode, tuple(results), sweep, legacy)
    _journal(journal, {"mode": mode, "summary": report.counts(), "legacy_index": legacy})
    return report


async def purge_account(ctx: PurgeContext, account_id: str, *, apply: bool) -> AccountPurge:
    """One account (C3): a dry run only reads; apply locks, reads and deletes in one transaction."""
    if not apply:
        return (await _plan_account(ctx, account_id, lock=False))[0]
    async with in_transaction():
        result, doomed = await _plan_account(ctx, account_id, lock=True)
        if doomed:
            await CredentialBlob.filter(id__in=doomed).delete()
    return result


async def sweep_deleted_accounts(ctx: PurgeContext, *, apply: bool) -> SweepResult:
    """`--all`: the rows of accounts that no longer exist, re-checked against every Connection row.

    # WHY no row lock: after E5a no path can create a reference to a deleted account's blob (the PUT
    # mints a fresh address, and every Connection insert needs the account row).
    """
    if not apply:
        return (await _plan_sweep(ctx))[0]
    async with in_transaction():
        result, doomed = await _plan_sweep(ctx)
        if doomed:
            await CredentialBlob.filter(id__in=doomed).delete()
    return result


async def purge_legacy_index(ctx: PurgeContext, *, skipped: set[str], apply: bool) -> LegacyIndex:
    """The pre-split global index row goes last, and only once every account it lists is done."""
    if not await _legacy_row().exists():
        return "absent"
    try:
        listed = {document.account_id for document in (await ctx.profile_index.read()).profiles}
    except (SecretDecryptionError, ValueError):
        return "kept_unreadable"
    # INVARIANT (C3): a skipped account may still read its documents from this row (no row of its
    # own), so the row outlives every skip.
    if listed & skipped:
        return "kept_listed_account_skipped"
    if apply:
        await _legacy_row().delete()
    return "purged"


# --- one account ------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    id: UUID
    address: Address
    kind: str


async def _plan_account(
    ctx: PurgeContext, account_id: str, *, lock: bool
) -> tuple[AccountPurge, list[UUID]]:
    try:
        doomed = await _doomed(ctx, account_id, lock=lock)
    except _Skip as skip:
        return AccountPurge(account_id, _count([]), skip.reason), []
    return AccountPurge(account_id, _count(doomed)), [candidate.id for candidate in doomed]


async def _doomed(ctx: PurgeContext, account_id: str, *, lock: bool) -> list[_Candidate]:
    account = Account.filter(id=account_id)
    # INVARIANT (C3): the account row first, so every read below sees what a reference creator that
    # came first committed, and one that comes later waits for this transaction.
    if await (account.select_for_update() if lock else account).first() is None:
        raise _Skip("account_missing")
    states = await _migration_states(account_id)
    documents = await _documents(ctx, account_id)
    references = await read_references(ctx.app, ctx.providers)
    if references.unresolved_naming(account_id):
        raise _Skip("connection_unresolvable")
    addressed = references.addressed
    candidates = await _candidates(ctx, account_id, lock=lock)
    doomed = [candidate for candidate in candidates if candidate.address not in addressed]
    _refuse_unmigrated_documents(ctx, account_id, documents, states, doomed)
    return doomed


async def _migration_states(account_id: str) -> dict[str, str]:
    try:
        markers = await PairAuthorityStore().list(account_id)
    except ValueError as exc:
        raise _Skip("marker_unreadable") from exc
    if any(marker.migration_state == "quarantined" for marker in markers):
        raise _Skip("quarantined_marker")
    return {marker.provider: marker.migration_state for marker in markers}


async def _documents(ctx: PurgeContext, account_id: str) -> list[Profile]:
    try:
        # WHY `list`: it falls back to the legacy global row exactly as the backfill reads it.
        return await ctx.profile_index.list(account_id)
    except (SecretDecryptionError, ValueError) as exc:
        raise _Skip("index_unreadable") from exc


async def _candidates(ctx: PurgeContext, account_id: str, *, lock: bool) -> list[_Candidate]:
    """The account's index row and every blob under a loaded namespace — the rows it may lose."""
    found: dict[UUID, _Candidate] = {}
    for namespace in ctx.namespaces():
        prefix = f"{_NAMESPACE}:{namespace}:{account_id}:"
        for blob in await _rows(CredentialBlob.filter(service__startswith=prefix), lock=lock):
            # WHY re-checked: SQLite's LIKE ignores case.
            if blob.service.startswith(prefix):
                kind = UUID_SHAPED if _is_uuid(blob.service[len(prefix) :]) else NAME_SHAPED
                found[blob.id] = _Candidate(blob.id, (blob.service, blob.account), kind)
    index = CredentialBlob.filter(
        service=INDEX_CREDENTIAL_SERVICE, account=index_account_for(account_id)
    )
    for blob in await _rows(index, lock=lock):
        found[blob.id] = _Candidate(blob.id, (blob.service, blob.account), INDEX_ROWS)
    return list(found.values())


async def _rows(query: QuerySet[CredentialBlob], *, lock: bool) -> list[CredentialBlob]:
    # INVARIANT (C5): `value` is never loaded — the purge decides on addresses alone.
    query = query.only("id", "service", "account")
    return await (query.select_for_update() if lock else query)


def _refuse_unmigrated_documents(
    ctx: PurgeContext,
    account_id: str,
    documents: Iterable[Profile],
    states: Mapping[str, str],
    doomed: Iterable[_Candidate],
) -> None:
    """C4 (Q4): a document on a pair not yet `migrated` names the blob a backfill would adopt."""
    # WHY by service, not by address: the backfill reads the document at the locator's logical
    # account and the Connection it creates reads the strategy's physical one. Every strategy keeps
    # the service, so the service covers both: a spare refusal at worst, never a lost key.
    doomed_services = {candidate.address[0] for candidate in doomed}
    for document in documents:
        if states.get(document.provider) == "migrated":
            continue
        plugin = ctx.providers.get(document.provider)
        namespace = credential_service_provider_for(plugin, document.provider)
        # WHY the backfill's own locator: `backfill_apply` creates the Connection on exactly it.
        locator = credential_locator_for(namespace, account_id, document.name)
        if locator["service"] in doomed_services:
            raise _Skip("unmigrated_document")


def _count(doomed: Iterable[_Candidate]) -> dict[str, int]:
    kinds = Counter(candidate.kind for candidate in doomed)
    return {kind: kinds[kind] for kind in ACCOUNT_KINDS}


# --- deleted accounts, unrecognised rows, the legacy row ------------------------------------------


@dataclass(frozen=True)
class _SweepScope:
    namespaces: frozenset[str]
    accounts: frozenset[str]
    index_accounts: frozenset[str]

    def kind(self, blob: CredentialBlob) -> str | None:
        """What the sweep makes of a row; `None` when another step owns it."""
        if blob.service == INDEX_CREDENTIAL_SERVICE:
            # WHY: the legacy row goes last; a live account's row goes in its own transaction.
            if blob.account == LEGACY_INDEX_ACCOUNT or blob.account in self.index_accounts:
                return None
            return INDEX_ROWS
        parts = blob.service.split(":", 3)
        if len(parts) != 4 or parts[0] != _NAMESPACE or parts[1] not in self.namespaces:
            return _UNRECOGNISED
        if not _is_uuid(parts[2]):
            return _UNRECOGNISED
        return None if parts[2] in self.accounts else DELETED_ACCOUNT


async def _plan_sweep(ctx: PurgeContext) -> tuple[SweepResult, list[UUID]]:
    accounts = frozenset(await all_account_ids())
    scope = _SweepScope(
        frozenset(ctx.namespaces()),
        accounts,
        frozenset(index_account_for(account_id) for account_id in accounts),
    )
    # WHY rows before Connections: a reference is inserted before the blob it names is written, so
    # every blob this scan sees has its Connection committed before the read below.
    blobs = await CredentialBlob.all().only("id", "service", "account")
    references = await read_references(ctx.app, ctx.providers)
    # WHY: an unresolvable row's account is skipped in its own pass, so what it keeps here is
    # reported as a refusal.
    kept = references.unresolved_services()
    kinds = {blob.id: scope.kind(blob) for blob in blobs}
    index_rows = [blob.id for blob in blobs if kinds[blob.id] == INDEX_ROWS]
    deleted = [
        blob.id
        for blob in blobs
        if kinds[blob.id] == DELETED_ACCOUNT
        and (blob.service, blob.account) not in references.addressed
        and blob.service not in kept
    ]
    unrecognised = sum(kind == _UNRECOGNISED for kind in kinds.values())
    return SweepResult(len(index_rows), len(deleted), unrecognised), index_rows + deleted


def _legacy_row() -> QuerySet[CredentialBlob]:
    return CredentialBlob.filter(service=INDEX_CREDENTIAL_SERVICE, account=LEGACY_INDEX_ACCOUNT)


def _is_uuid(text: str) -> bool:
    try:
        UUID(text)
    except ValueError:
        return False
    return True


def _journal(journal: TextIO | None, line: Mapping[str, Any]) -> None:
    if journal is not None:
        journal.write(json.dumps(line) + "\n")
        # WHY: an account's line follows its commit; a run that stops part-way keeps the record.
        journal.flush()


__all__ = [
    "ACCOUNT_KINDS",
    "PURGE_MODES",
    "AccountPurge",
    "PurgeContext",
    "PurgeMode",
    "PurgeReport",
    "SweepResult",
    "purge_account",
    "purge_legacy_index",
    "run_purge",
    "sweep_deleted_accounts",
]
