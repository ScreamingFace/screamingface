"""Publish the backfill's dispositions — apply, rollback, dry-run report (OME-1208, S4).

# FEATURE: Stage B backfill — the write half of `python -m aigateway.migrate_profiles`: a
# Profile-only pair gets a Connection ON the Profile's blob address (no re-entry, no decrypt for
# transfer), a single active Connection-only pair is named effective, an unprovable pair is
# quarantined, and the pair marker publishes each disposition inside ONE transaction per account.
# INVARIANT (D14, card): the marker advance is the LAST write of each pair and is fenced on the
# generation the plan observed, so a concurrent writer — or a second apply run creating the same
# FIRST marker — becomes `PairAuthorityConflict`/`IntegrityError` and the whole account rolls back;
# the re-run classifies the pair `already_migrated` and mints nothing.
# INVARIANT (D5, R1): rollback moves only the marker (`none`, no effective, note `rollback`); every
# blob, Connection row and document stays.
# INVARIANT (card): the report and the journal carry opaque identifiers only — account and
# Connection UUIDs, provider ids, dispositions, categories, generations, counts.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, TextIO
from uuid import UUID, uuid4

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from aigateway.core.auth.models import Account
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for

from .backfill_classify import BackfillContext, PairPlan, classify_account
from .pair_authority import PairAuthorityConflict, PairAuthorityStore

Mode = Literal["dry-run", "apply", "rollback"]
MODES: tuple[Mode, ...] = ("dry-run", "apply", "rollback")


@dataclass(frozen=True)
class PairRecord:
    provider: str
    disposition: str
    category: str
    action: str
    generation: int
    connection_id: str | None
    applied: bool
    alias_documents: int


@dataclass(frozen=True)
class AccountResult:
    account_id: str
    records: tuple[PairRecord, ...]
    conflict: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "conflict": self.conflict,
            "pairs": [asdict(record) for record in self.records],
        }


@dataclass(frozen=True)
class BackfillReport:
    mode: Mode
    accounts: tuple[AccountResult, ...]

    def counts(self) -> dict[str, int]:
        records = [record for account in self.accounts for record in account.records]
        return {
            "migrated": sum(r.disposition == "migrated" for r in records),
            "quarantined": sum(r.disposition == "quarantined" for r in records),
            "none": sum(r.disposition == "none" for r in records),
            "applied": sum(r.applied for r in records),
            "conflicts": sum(account.conflict for account in self.accounts),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "counts": self.counts(),
            "accounts": [account.to_dict() for account in self.accounts],
        }


async def all_account_ids() -> tuple[str, ...]:
    """Every account, oldest first (`--all`); every Connection has an Account, so none is missed."""
    ids = await Account.all().order_by("created_at", "id").values_list("id", flat=True)
    return tuple(str(account_id) for account_id in ids)


async def run_backfill(
    ctx: BackfillContext,
    *,
    mode: Mode,
    account_ids: Sequence[str],
    journal: TextIO | None = None,
) -> BackfillReport:
    if mode not in MODES:
        raise ValueError(f"unknown backfill mode {mode!r}")
    results: list[AccountResult] = []
    for account_id in account_ids:
        if mode == "apply":
            result = await apply_account(ctx, account_id)
        elif mode == "rollback":
            result = await rollback_account(ctx, account_id)
        else:
            result = await plan_account(ctx, account_id)
        results.append(result)
        _journal(journal, result)
    report = BackfillReport(mode, tuple(results))
    if journal is not None:
        journal.write(json.dumps({"mode": mode, "summary": report.counts()}) + "\n")
    return report


async def plan_account(ctx: BackfillContext, account_id: str) -> AccountResult:
    """`--dry-run`: exactly the reads `apply` performs, and not one write."""
    plans = await classify_account(ctx, account_id)
    return AccountResult(account_id, tuple(_record(plan, applied=False) for plan in plans))


async def apply_account(ctx: BackfillContext, account_id: str) -> AccountResult:
    plans = await classify_account(ctx, account_id)
    try:
        async with in_transaction():
            records = [await _apply_pair(ctx, plan) for plan in plans]
    except (PairAuthorityConflict, IntegrityError):
        # WHY: a racing writer owns the pair now (or created the first marker first); the context
        # manager rolled the account back — report it, never guess, let the scheduler retry.
        return AccountResult(
            account_id, tuple(_record(plan, applied=False) for plan in plans), conflict=True
        )
    return AccountResult(account_id, tuple(records))


ROLLBACK_REFUSED = "rollback_refused_alias_documents"


async def rollback_account(ctx: BackfillContext, account_id: str) -> AccountResult:
    """R1: every `migrated` pair of the account returns to legacy authority; nothing else moves."""
    plans = await classify_account(ctx, account_id)
    records: list[PairRecord] = []
    try:
        async with in_transaction():
            for plan in plans:
                if plan.category != "already_migrated":
                    records.append(_record(plan, applied=False))
                    continue
                if plan.alias_documents:
                    # WHY refuse, not reset: a document not addressed at the effective row's blob
                    # (a `work` alias write, a UUID-addressed row that gained a document) holds no
                    # key at its own address. Reset to `none`, the legacy path would serve that
                    # document from an empty address while reporting it connected. The only
                    # repair — copying the secret between addresses — decrypts it for transfer, so
                    # the pair stays migrated and the report names it for the operator.
                    # INVARIANT (R1): a rollback never leaves a document whose address holds no key.
                    records.append(
                        PairRecord(
                            plan.provider,
                            "migrated",
                            ROLLBACK_REFUSED,
                            "skip",
                            plan.generation,
                            _text(plan.connection_id),
                            False,
                            plan.alias_documents,
                        )
                    )
                    continue
                pair = await PairAuthorityStore().advance(
                    account_id,
                    plan.provider,
                    expected_generation=plan.generation,
                    migration_state="none",
                    migration_note="rollback",
                )
                records.append(
                    PairRecord(
                        plan.provider,
                        "none",
                        "rollback",
                        "rollback",
                        pair.generation,
                        _text(plan.connection_id),
                        True,
                        plan.alias_documents,
                    )
                )
    except PairAuthorityConflict:
        return AccountResult(
            account_id, tuple(_record(plan, applied=False) for plan in plans), conflict=True
        )
    return AccountResult(account_id, tuple(records))


async def _apply_pair(ctx: BackfillContext, plan: PairPlan) -> PairRecord:
    if plan.action == "skip":
        return _record(plan, applied=False)
    effective = plan.connection_id
    if plan.action == "create":
        effective = (await _create_connection(ctx, plan)).id
    migrated = plan.action != "quarantine"
    pair = await PairAuthorityStore().advance(
        plan.account_id,
        plan.provider,
        expected_generation=plan.generation,
        migration_state="migrated" if migrated else "quarantined",
        effective_connection_id=effective if migrated else None,
        migration_note=plan.category,
    )
    return _record(
        plan,
        applied=True,
        generation=pair.generation,
        connection_id=effective if migrated else None,
    )


async def _create_connection(ctx: BackfillContext, plan: PairPlan) -> OAuthConnection:
    profile = plan.profile
    if profile is None:
        raise ValueError("a create plan carries its document")
    credential_provider = credential_service_provider_for(
        ctx.providers.get(plan.provider), plan.provider
    )
    store = OAuthConnectionStore()
    # WHY: the Connection is created ON the Profile's blob address — the credential is neither
    # decrypted for transfer nor re-entered (card "Reads without re-entry"); the label is the legacy
    # name so a named selector still resolves until Stage D retires the selector.
    connection = await store.create_pending(
        account_id=plan.account_id,
        provider=plan.provider,
        label=profile.name,
        connection_id=uuid4(),
        credential_provider=credential_provider,
        credential_locator=credential_locator_for(
            credential_provider, plan.account_id, profile.name
        ),
    )
    if profile.auth_type != "oauth":
        typed = await store.set_auth_type(connection, profile.auth_type)
        if typed is None:
            raise PairAuthorityConflict(plan.provider, plan.generation)
        connection = typed
    return await store.complete(connection, label=profile.name, identity=None)


def _record(
    plan: PairPlan,
    *,
    applied: bool,
    generation: int | None = None,
    connection_id: UUID | None = None,
) -> PairRecord:
    return PairRecord(
        plan.provider,
        plan.disposition,
        plan.category,
        plan.action,
        plan.generation if generation is None else generation,
        _text(plan.connection_id if connection_id is None else connection_id),
        applied,
        plan.alias_documents,
    )


def _text(connection_id: UUID | None) -> str | None:
    return None if connection_id is None else str(connection_id)


def _journal(journal: TextIO | None, result: AccountResult) -> None:
    if journal is None:
        return
    for record in result.records:
        line = {"account_id": result.account_id, "conflict": result.conflict, **asdict(record)}
        journal.write(json.dumps(line) + "\n")


__all__ = [
    "MODES",
    "ROLLBACK_REFUSED",
    "AccountResult",
    "BackfillReport",
    "Mode",
    "PairRecord",
    "all_account_ids",
    "apply_account",
    "plan_account",
    "rollback_account",
    "run_backfill",
]
