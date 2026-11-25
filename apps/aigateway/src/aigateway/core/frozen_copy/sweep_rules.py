"""The rules of the frozen copy retention sweep (OME-1947, spec prd/copy-sweep.md, contracts K7).

A rule names the copies that it can mark (`candidates`) and marks one copy under the row lock of
that copy (`mark`). `FrozenCopySweep` in `sweep.py` runs the rules and purges the marked copies.

INVARIANT (I2): each rule evaluates its condition again under the row lock of the copy, in the
transaction of the write (`mark_locked`); a capture, a seal or a claim that commits first wins.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any, Literal, Protocol
from uuid import UUID

from asyncpg import exceptions as asyncpg_exceptions
from tortoise.expressions import Q
from tortoise.queryset import QuerySet
from tortoise.transactions import in_transaction

from .models import (
    STATUS_ABANDONED,
    STATUS_EXPIRED,
    STATUS_OPEN,
    STATUS_SEALED,
    FrozenCopy,
    FrozenCopyEntry,
)
from .times import as_utc

__all__ = [
    "Decide",
    "ExpiryRule",
    "IdleRule",
    "MarkOutcome",
    "SweepCandidate",
    "SweepRule",
    "mark_locked",
]

MarkOutcome = Literal["marked", "rule no longer true", "lock timeout", "newest entry not found"]
# AIDEV-NOTE: the check and the write of one rule under the row lock; it gets the locked row,
# or None when the copy is gone.
Decide = Callable[[FrozenCopy | None], Awaitable[MarkOutcome]]


def _is_postgres() -> bool:
    return FrozenCopy._meta.db.capabilities.dialect == "postgres"


async def _idle_since(copy_id: UUID, entry_seq: int, created_at: datetime) -> datetime | None:
    if entry_seq == 0:
        return as_utc(created_at)
    times: list[Any] = await FrozenCopyEntry.filter(
        frozen_copy_id=copy_id, seq=entry_seq
    ).values_list("created_at", flat=True)
    return as_utc(times[0]) if times else None


@dataclass(frozen=True)
class SweepCandidate:
    rule: str
    copy_id: UUID
    account_id: UUID
    entries: int
    # WHY (erd.md section 2.4): a copy that the rule cannot evaluate is reported with this cause;
    # the run does not call mark() for it and the dry run does not list it.
    skip: MarkOutcome | None = None


class SweepRule(Protocol):
    """The shape of a sweep rule; a candidate can carry a skip cause."""

    name: str

    async def candidates(self, at: datetime) -> list[SweepCandidate]: ...

    async def mark(self, copy_id: UUID, at: datetime) -> MarkOutcome: ...


async def mark_locked(copy_id: UUID, lock_timeout_ms: int, decide: Decide) -> MarkOutcome:
    """Lock the copy row, then let `decide` check the rule again and write the row."""
    try:
        async with in_transaction() as conn:
            if _is_postgres():
                await conn.execute_script(f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'")
            copy = await FrozenCopy.filter(id=copy_id).select_for_update().first()
            return await decide(copy)
    # WHY this type and nothing wider: Tortoise 1.1.8 passes SQLSTATE 55P03 through as the
    # asyncpg error, not as OperationalError. The class is SQLSTATE 55P03 itself, so no
    # further check is needed.
    except asyncpg_exceptions.LockNotAvailableError:
        return "lock timeout"


class IdleRule:
    """An open copy with no new entry for `open_idle_seconds` becomes `abandoned`."""

    def __init__(self, *, open_idle_seconds: int, lock_timeout_ms: int = 2000) -> None:
        self.name: str = STATUS_ABANDONED
        self._idle = timedelta(seconds=open_idle_seconds)
        self._lock_timeout_ms = lock_timeout_ms

    def _is_idle(self, idle_since: datetime, at: datetime) -> bool:
        return as_utc(at) - idle_since >= self._idle

    async def candidates(self, at: datetime) -> list[SweepCandidate]:
        rows = await FrozenCopy.filter(status=STATUS_OPEN).values(
            "id", "account_id", "entry_seq", "created_at"
        )
        found: list[SweepCandidate] = []
        for row in rows:
            since = await _idle_since(row["id"], row["entry_seq"], row["created_at"])
            if since is None:
                found.append(
                    SweepCandidate(
                        rule=self.name,
                        copy_id=row["id"],
                        account_id=row["account_id"],
                        entries=row["entry_seq"],
                        skip="newest entry not found",
                    )
                )
            elif self._is_idle(since, at):
                found.append(
                    SweepCandidate(
                        rule=self.name,
                        copy_id=row["id"],
                        account_id=row["account_id"],
                        entries=row["entry_seq"],
                    )
                )
        return found

    async def mark(self, copy_id: UUID, at: datetime) -> MarkOutcome:
        return await mark_locked(copy_id, self._lock_timeout_ms, partial(self._decide, at=at))

    async def _decide(self, copy: FrozenCopy | None, at: datetime) -> MarkOutcome:
        if copy is None or copy.status != STATUS_OPEN:
            return "rule no longer true"
        since = await _idle_since(copy.id, copy.entry_seq, copy.created_at)
        if since is None:
            return "newest entry not found"
        if not self._is_idle(since, at):
            return "rule no longer true"
        copy.status = STATUS_ABANDONED
        copy.swept_at = at
        copy.entries = copy.entry_seq
        fields_to_save = ["status", "swept_at", "entries"]
        if copy.entry_seq == 0:
            # WHY: spec S16, no entry to delete, so the mark completes the purge in the same
            # transaction.
            copy.purged_at = at
            fields_to_save.append("purged_at")
        await copy.save(update_fields=fields_to_save)
        return "marked"


class ExpiryRule:
    """A sealed copy that no Score claims becomes `expired` when its retention period ends.

    The clock starts at `retention_from` when migration 0019 set it, else at `sealed_at`.
    """

    def __init__(self, *, unclaimed_ttl_seconds: int, lock_timeout_ms: int = 2000) -> None:
        self.name: str = STATUS_EXPIRED
        self._ttl = timedelta(seconds=unclaimed_ttl_seconds)
        self._lock_timeout_ms = lock_timeout_ms

    def _candidates_query(self, cutoff: datetime) -> QuerySet[FrozenCopy]:
        """The sealed copies with no claim whose clock started at or before `cutoff`."""
        return FrozenCopy.filter(
            Q(retention_from__lte=cutoff) | Q(retention_from__isnull=True, sealed_at__lte=cutoff),
            status=STATUS_SEALED,
            claimed_at__isnull=True,
        )

    async def candidates(self, at: datetime) -> list[SweepCandidate]:
        # WHY one filtered query (erd.md section 2.6): about 130 000 sealed rows after 90 days.
        # The filter only selects; the check under the row lock decides.
        rows = await self._candidates_query(as_utc(at) - self._ttl).values(
            "id", "account_id", "entries"
        )
        return [
            SweepCandidate(
                rule=self.name,
                copy_id=row["id"],
                account_id=row["account_id"],
                entries=row["entries"],
            )
            for row in rows
        ]

    async def mark(self, copy_id: UUID, at: datetime) -> MarkOutcome:
        return await mark_locked(copy_id, self._lock_timeout_ms, partial(self._decide, at=at))

    async def _decide(self, copy: FrozenCopy | None, at: datetime) -> MarkOutcome:
        # INVARIANT (I1): a claim that commits first wins; `claimed_at` is read under the lock.
        if copy is None or copy.status != STATUS_SEALED or copy.claimed_at is not None:
            return "rule no longer true"
        start = copy.retention_from or copy.sealed_at
        if start is None or as_utc(at) < as_utc(start) + self._ttl:
            return "rule no longer true"
        copy.status = STATUS_EXPIRED
        copy.swept_at = at
        fields_to_save = ["status", "swept_at"]
        if copy.entry_seq == 0:
            # WHY: no entry to delete, so the mark completes the purge in the same transaction.
            copy.purged_at = at
            fields_to_save.append("purged_at")
        await copy.save(update_fields=fields_to_save)
        return "marked"
