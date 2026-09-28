"""The pair authority marker's store (OME-1208, Stage B S1).

# FEATURE: OME-1138 Stage B — `PairAuthorityStore` reads and advances the one row per
# `(account, provider)` that says which backing owns the pair; `PairAuthority` is the read view the
# authority routing (S2') and the migration tool (S4) consume.
# INVARIANT: an absent row reads as `none` with generation 0. `advance` is a compare-and-set on the
# generation — the row is created only when the caller expects generation 0 and updated only
# `WHERE generation = expected` — so a stale writer is fenced at commit time and changes nothing.
# INVARIANT (D14): only a `migrated` pair names an effective Connection; for `none` and
# `quarantined` the legacy Profile owns the pair, and a reference would be a second owner.
# AIDEV-NOTE: policy-free by design — WHICH transition a pair may take (classify, quarantine,
# roll back) is the caller's decision. Call `advance` inside the caller's `in_transaction()` so
# the marker commits with the data it describes (card: "written in the same transaction").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from tortoise.exceptions import IntegrityError

from .models import ProviderCredentialSlot

MigrationState = Literal["none", "migrated", "quarantined"]
MIGRATION_STATES: frozenset[str] = frozenset({"none", "migrated", "quarantined"})
# WHY 0: what an absent row reads as; the first write creates the row at 1.
UNMARKED_GENERATION = 0

_COLUMNS = (
    "provider",
    "migration_state",
    "effective_connection_id",
    "generation",
    "migration_note",
)


@dataclass(frozen=True)
class PairAuthority:
    """What the marker says about one pair — all of it, and nothing secret."""

    account_id: str
    provider: str
    migration_state: MigrationState
    effective_connection_id: UUID | None
    generation: int
    migration_note: str | None


class PairAuthorityConflict(Exception):
    """The compare-and-set on the marker lost: another writer advanced this pair first."""

    def __init__(self, provider: str, expected_generation: int) -> None:
        super().__init__(
            f"pair authority for {provider} moved past generation {expected_generation}"
        )
        self.provider = provider
        self.expected_generation = expected_generation


def _checked_state(value: object) -> MigrationState:
    if value not in MIGRATION_STATES:
        # INVARIANT: an unknown stored state is refused, never read as `none` — guessing the owner
        # is exactly the dual-writer state Stage B exists to exclude.
        raise ValueError(f"unknown pair authority state {value!r}")
    return cast(MigrationState, value)


def _view(account_id: str, row: dict[str, Any]) -> PairAuthority:
    return PairAuthority(
        account_id=account_id,
        provider=row["provider"],
        migration_state=_checked_state(row["migration_state"]),
        effective_connection_id=row["effective_connection_id"],
        generation=row["generation"],
        migration_note=row["migration_note"],
    )


def _unmarked(account_id: str, provider: str) -> PairAuthority:
    return PairAuthority(account_id, provider, "none", None, UNMARKED_GENERATION, None)


class PairAuthorityStore:
    """Read and advance the pair authority markers."""

    async def read(self, account_id: str, provider: str) -> PairAuthority:
        rows = await ProviderCredentialSlot.filter(account_id=account_id, provider=provider).values(
            *_COLUMNS
        )
        return _view(account_id, rows[0]) if rows else _unmarked(account_id, provider)

    async def list(self, account_id: str) -> tuple[PairAuthority, ...]:
        """Every marked pair of the account, by provider; unmarked pairs are simply absent."""
        rows = (
            await ProviderCredentialSlot.filter(account_id=account_id)
            .order_by("provider")
            .values(*_COLUMNS)
        )
        return tuple(_view(account_id, row) for row in rows)

    async def advance(
        self,
        account_id: str,
        provider: str,
        *,
        expected_generation: int,
        migration_state: MigrationState,
        effective_connection_id: UUID | None = None,
        migration_note: str | None = None,
    ) -> PairAuthority:
        """Publish a new authority for the pair, fenced on the generation the caller observed."""
        state = _checked_state(migration_state)
        if effective_connection_id is not None and state != "migrated":
            raise ValueError("only a migrated pair names an effective Connection")
        changes: dict[str, Any] = {
            "migration_state": state,
            "effective_connection_id": effective_connection_id,
            "migration_note": migration_note,
        }
        generation = expected_generation + 1
        if expected_generation == UNMARKED_GENERATION:
            try:
                await ProviderCredentialSlot.create(
                    account_id=account_id, provider=provider, generation=generation, **changes
                )
            except IntegrityError as exc:
                # WHY one outcome: a marker already exists (a racing writer won), or the account is
                # gone (nothing to own) — either way THIS writer does not own the pair. Under
                # PostgreSQL the enclosing transaction is aborted by now, so no follow-up query
                # could tell the two apart anyway.
                raise PairAuthorityConflict(provider, expected_generation) from exc
        else:
            updated = await ProviderCredentialSlot.filter(
                account_id=account_id, provider=provider, generation=expected_generation
            ).update(
                generation=generation,
                # WHY explicit: `QuerySet.update` does not touch `auto_now` fields.
                updated_at=datetime.now(UTC),
                **changes,
            )
            if updated != 1:
                raise PairAuthorityConflict(provider, expected_generation)
        return PairAuthority(
            account_id, provider, state, effective_connection_id, generation, migration_note
        )


__all__ = [
    "MIGRATION_STATES",
    "UNMARKED_GENERATION",
    "MigrationState",
    "PairAuthority",
    "PairAuthorityConflict",
    "PairAuthorityStore",
]
