"""The frozen copy retention sweep (OME-1947, spec prd/copy-sweep.md, contracts K6-K8).

FEATURE: always on, no switch (Q22) and no approval (Q23). Each gateway runs the sweep on a
periodic trigger; an operator can also run it by command. An idle open copy becomes `abandoned`,
and a sealed copy that no Score claims becomes `expired` when its period ends. The entries of both
are then deleted in chunks. The rules are in `sweep_rules.py`.

INVARIANT (I3): the mark sets the final status under the copy row lock, after it evaluates the rule
again under that lock, and before any entry is deleted. The rule check under the lock is
`mark_locked` in `sweep_rules.py` (I2 there): a capture, a seal or a claim that commits first wins.
INVARIANT (I4): `purged_at` is set only by a statement that checks that no entry remains.
WHY no global lock: two replicas or the command can run at the same time (row locks, SKIP LOCKED);
a lock left held after a failure would stop each later run with no signal.
The sweep never reads request_json or response_json; its log record has counts only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from tortoise.transactions import in_transaction

from aigateway.core.auth.models import Account
from aigateway.core.snapshot_scheduler import Sleep

from .models import STATUS_ABANDONED, STATUS_EXPIRED, FrozenCopy, FrozenCopyEntry
from .sweep_rules import (
    ExpiryRule,
    IdleRule,
    MarkOutcome,
    SweepCandidate,
    SweepRule,
    _is_postgres,
)
from .times import as_utc

if TYPE_CHECKING:
    from aigateway.config import Settings

__all__ = [
    "ExpiryRule",
    "FrozenCopySweep",
    "IdleRule",
    "MarkOutcome",
    "SweepCandidate",
    "SweepReport",
    "SweepRule",
    "build_frozen_copy_sweep",
    "database_now",
]

logger = logging.getLogger(__name__)

# WHY bound at import: some tests patch the global asyncio.sleep; a sweep built later keeps the
# real one.
_ASYNC_SLEEP: Sleep = asyncio.sleep
_POSTGRES_NOW_SQL = "SELECT now() AS now"
_SQLITE_NOW_SQL = "SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now') AS now"
_PURGE_CHUNK_SQL = (
    "DELETE FROM frozen_copy_entries WHERE id IN (SELECT id FROM frozen_copy_entries "
    "WHERE frozen_copy_id = $1 LIMIT $2 FOR UPDATE SKIP LOCKED)"
)
_FINISH_PURGE_SQL = (
    "UPDATE frozen_copies SET purged_at = $1 WHERE id = $2 AND purged_at IS NULL "
    "AND NOT EXISTS (SELECT 1 FROM frozen_copy_entries WHERE frozen_copy_id = $2)"
)


async def database_now() -> datetime:
    """The database clock, as an aware UTC time."""
    client = FrozenCopy._meta.db
    if _is_postgres():
        rows = await client.execute_query_dict(_POSTGRES_NOW_SQL)
        return as_utc(rows[0]["now"])
    rows = await client.execute_query_dict(_SQLITE_NOW_SQL)
    return as_utc(datetime.fromisoformat(rows[0]["now"]))


async def _account_names(ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = await Account.filter(id__in=list(ids)).values("id", "username")
    return {row["id"]: row["username"] for row in rows}


@dataclass
class SweepReport:
    trigger: str
    marked: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, dict[str, int]] = field(default_factory=dict)
    entries_purged: int = 0
    copies_completed: int = 0
    copies_with_entries: int = 0
    purge_stopped: str | None = None


class FrozenCopySweep:
    def __init__(
        self,
        rules: Sequence[SweepRule],
        *,
        max_entries: int,
        chunk_size: int = 500,
        chunk_pause_s: float = 0.2,
        slow_chunk_s: float = 5.0,
        slow_window: int = 10,
        sleep: Sleep | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rules = tuple(rules)
        self._max_entries = max_entries
        self._chunk_size = chunk_size
        self._chunk_pause_s = chunk_pause_s
        self._slow_chunk_s = slow_chunk_s
        self._slow_window = slow_window
        self._sleep = sleep if sleep is not None else _ASYNC_SLEEP
        self._clock = clock

    async def dry_run(self, at: datetime | None = None) -> dict[str, Any]:
        """What a run at `at` would do. It writes nothing."""
        when = as_utc(at) if at is not None else await database_now()
        found: list[SweepCandidate] = []
        for rule in self._rules:
            found.extend(c for c in await rule.candidates(when) if c.skip is None)
        totals: dict[str, dict[str, int]] = {
            STATUS_ABANDONED: {"copies": 0, "entries": 0},
            STATUS_EXPIRED: {"copies": 0, "entries": 0},
        }
        per_account: dict[tuple[UUID, str], dict[str, int]] = {}
        for c in found:
            totals[c.rule]["copies"] += 1
            totals[c.rule]["entries"] += c.entries
            counts = per_account.setdefault((c.account_id, c.rule), {"copies": 0, "entries": 0})
            counts["copies"] += 1
            counts["entries"] += c.entries
        names = await _account_names({c.account_id for c in found})
        by_account = [
            {
                "account": names.get(aid, str(aid)),
                "rule": rule,
                "copies": counts["copies"],
                "entries": counts["entries"],
            }
            for (aid, rule), counts in sorted(
                per_account.items(),
                key=lambda item: (names.get(item[0][0], str(item[0][0])), item[0][1]),
            )
        ]
        candidates = [
            {"rule": c.rule, "id": str(c.copy_id), "entries": c.entries}
            for c in sorted(found, key=lambda c: (c.rule, str(c.copy_id)))
        ]
        return {
            "evaluated_at": when.isoformat(),
            "rules": totals,
            "by_account": by_account,
            "candidates": candidates,
        }

    async def run_pass(self, *, trigger: str, max_entries: int | None = None) -> SweepReport:
        report = SweepReport(trigger=trigger)
        budget = self._max_entries if max_entries is None else max_entries
        try:
            at = await database_now()
            await self._mark_all(at, report)
            await self._purge(at, budget, report)
            report.copies_with_entries = await FrozenCopy.filter(
                swept_at__isnull=False, purged_at__isnull=True
            ).count()
        except Exception as exc:
            logger.error(
                "frozen copy sweep run failed trigger=%s error=%s", trigger, type(exc).__name__
            )
            raise
        _log_report(report)
        return report

    async def _mark_all(self, at: datetime, report: SweepReport) -> None:
        for rule in self._rules:
            marked = 0
            skipped: dict[str, int] = {}
            for candidate in await rule.candidates(at):
                outcome = (
                    candidate.skip
                    if candidate.skip is not None
                    else await rule.mark(candidate.copy_id, at)
                )
                if outcome == "marked":
                    marked += 1
                else:
                    skipped[outcome] = skipped.get(outcome, 0) + 1
            report.marked[rule.name] = marked
            report.skipped[rule.name] = skipped

    async def _purge(self, at: datetime, budget: int, report: SweepReport) -> None:
        remaining = budget
        recent: deque[float] = deque(maxlen=self._slow_window)
        pending: list[Any] = (
            await FrozenCopy.filter(swept_at__isnull=False, purged_at__isnull=True)
            .order_by("swept_at", "id")
            .values_list("id", flat=True)
        )
        for copy_id in pending:
            while True:
                if remaining <= 0:
                    # WHY: the last chunk can use the budget exactly and delete the last entries of
                    # this copy; the guarded statement completes such a copy and deletes nothing.
                    if await self.finish_purge(copy_id, at):
                        report.copies_completed += 1
                        break
                    report.purge_stopped = "budget"
                    return
                started = self._clock()
                deleted = await self.purge_chunk(copy_id, limit=min(self._chunk_size, remaining))
                recent.append(self._clock() - started)
                report.entries_purged += deleted
                remaining -= deleted
                if deleted == 0:
                    if await self.finish_purge(copy_id, at):
                        report.copies_completed += 1
                    break
                if (
                    len(recent) == self._slow_window
                    and sum(recent) / len(recent) > self._slow_chunk_s
                ):
                    report.purge_stopped = "slow"
                    return
                await self._sleep(self._chunk_pause_s)

    async def purge_chunk(self, copy_id: UUID, *, limit: int | None = None) -> int:
        """Delete up to `limit` entries of one copy; the number deleted."""
        size = self._chunk_size if limit is None else limit
        async with in_transaction() as conn:
            if _is_postgres():
                deleted, _ = await conn.execute_query(_PURGE_CHUNK_SQL, [copy_id, size])
                return int(deleted)
            ids = (
                await FrozenCopyEntry.filter(frozen_copy_id=copy_id)
                .limit(size)
                .values_list("id", flat=True)
            )
            if not ids:
                return 0
            return await FrozenCopyEntry.filter(id__in=list(ids)).delete()

    async def finish_purge(self, copy_id: UUID, at: datetime) -> bool:
        """Set `purged_at` if no entry remains; True when this call set it."""
        if _is_postgres():
            updated, _ = await FrozenCopy._meta.db.execute_query(_FINISH_PURGE_SQL, [at, copy_id])
            return updated == 1
        async with in_transaction():
            if await FrozenCopyEntry.filter(frozen_copy_id=copy_id).exists():
                return False
            updated = await FrozenCopy.filter(id=copy_id, purged_at__isnull=True).update(
                purged_at=at
            )
            return updated == 1


def _log_report(report: SweepReport) -> None:
    # INVARIANT (spec section 4.4, Q16): counts only, never an account name or a copy id.
    logger.info(
        "frozen copy sweep run trigger=%s marked=%s skipped=%s entries_purged=%d "
        "copies_completed=%d copies_with_entries=%d purge_stopped=%s",
        report.trigger,
        json.dumps(report.marked, sort_keys=True),
        json.dumps(report.skipped, sort_keys=True),
        report.entries_purged,
        report.copies_completed,
        report.copies_with_entries,
        report.purge_stopped or "none",
    )


def build_frozen_copy_sweep(settings: Settings) -> FrozenCopySweep:
    """The sweep of this gateway, from its settings. The idle rule runs first (contracts.md K7)."""
    return FrozenCopySweep(
        [
            IdleRule(open_idle_seconds=settings.frozen_copy_open_idle_seconds),
            ExpiryRule(unclaimed_ttl_seconds=settings.frozen_copy_unclaimed_ttl_seconds),
        ],
        max_entries=settings.frozen_copy_sweep_max_entries,
    )
