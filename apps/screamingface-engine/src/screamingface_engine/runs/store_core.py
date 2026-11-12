"""What every part of the Run store shares: its settings, its context, its lock order and how a
row becomes a record (E5 P1 spec §4.2, §4.3; E5 P2 spec §4.4).

FEATURE: first-class Runs (OME-1785). `runs/store.py` and `runs/store_driver.py` build on this;
nothing else imports it.

INVARIANT (P1 spec R5): a record is derived from ONE statement, the Run's Candidates joined to
their Run, so a read never combines facts from two moments.

INVARIANT (E5 P2 spec §4.4): only `get` reads a Candidate's start and record. Every other read
selects the columns it needs, so a 1 s poll of a Run of 256 Candidates never carries their JSON.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine, Iterable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Concatenate, cast

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.context import TortoiseContext, get_current_context
from tortoise.queryset import QuerySet

from screamingface_engine.runs.db import using
from screamingface_engine.runs.models import Candidate, Run
from screamingface_engine.runs.records import (
    CandidateRecord,
    CandidateStart,
    CandidateState,
    ContextRef,
    RunRecord,
    StopReason,
    is_terminal_run,
)
from screamingface_engine.runs.state import derive_state

# The non-terminal Candidate states: the only ones a write may move a Candidate out of.
LIVE = ("pending", "scheduled", "running")

# The columns every read selects: the Candidate's, then its Run's under a `run_` prefix.
_CANDIDATE_COLUMNS = (
    "index",
    "name",
    "state",
    "topic",
    "bound_at",
    "finished_at",
    "cost_usd",
    "error_code",
)
_RUN_COLUMNS = {
    "run_id": "run__id",
    "run_created_at": "run__created_at",
    "run_benchmark": "run__benchmark",
    "run_case_count": "run__case_count",
    "run_canceled": "run__canceled",
    "run_stopped_by": "run__stopped_by",
    "run_detached": "run__detached",
    "run_deadline_at": "run__deadline_at",
    "run_context_sha256": "run__context_sha256",
    "run_context_bytes": "run__context_bytes",
}
# What `get` adds: the JSON a driver or a reattaching Client needs.
_FULL_COLUMNS = ("start", "record")


class StoreCore:
    """The settings and context one Run store holds.

    ``outcomes_survive_restart`` is the outcome stream's `survives_restart`, and ``started_at``
    when this process started: together they decide what reconcile may settle (P1 spec R6).
    ``orphan_grace`` is the attached Run's follow rule (E5 P2 spec R10; zero turns it off) and
    ``default_deadline`` a detached Run's deadline when it names none (D11).
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        lost_after: timedelta,
        outcomes_survive_restart: bool,
        started_at: datetime,
        orphan_grace: timedelta,
        default_deadline: timedelta,
        context: TortoiseContext | None = None,
    ) -> None:
        if orphan_grace < timedelta(0) or default_deadline <= timedelta(0):
            raise ValueError("the orphan grace must not be negative, and the deadline positive")
        self._clock = clock
        self._lost_after = lost_after
        self._outcomes_survive_restart = outcomes_survive_restart
        self._started_at = started_at
        self._orphan_grace = orphan_grace
        self._default_deadline = default_deadline
        # The Engine's own Tortoise context (`db.open_context`), or None to use the current one.
        self._context = context

    async def aclose(self) -> None:
        """Close the store's own database connections, when it owns a context."""
        if self._context is not None:
            await self._context.close_connections()


def in_context[S: StoreCore, **P, R](
    method: Callable[Concatenate[S, P], Coroutine[Any, Any, R]],
) -> Callable[Concatenate[S, P], Coroutine[Any, Any, R]]:
    """Run a store method's queries in the store's own Tortoise context."""

    @functools.wraps(method)
    async def wrapper(store: S, *args: P.args, **kwargs: P.kwargs) -> R:
        context = store._context
        if context is None or get_current_context() is context:
            return await method(store, *args, **kwargs)
        with using(context):
            return await method(store, *args, **kwargs)

    return wrapper


async def lock_run(run_id: str, conn: BaseDBAsyncClient) -> None:
    """Lock the Run's row for this transaction.

    INVARIANT: every write transaction locks its Run row first, then its Candidates. One lock
    order means writes to one Run never deadlock on Postgres, and a stop's "is any Candidate
    live?" check holds until its reason commits (P1 spec D12). SQLite takes one write lock per
    transaction, so the order holds there by construction.
    """
    await Run.filter(id=run_id).using_db(conn).select_for_update().first()


async def touch(run_id: str, now: datetime, conn: BaseDBAsyncClient | None = None) -> None:
    # INVARIANT (P1 spec §4.3): `last_activity_at` only moves forward, so a write stamped by a
    # slower clock never pulls it back.
    await (
        Run.filter(id=run_id, last_activity_at__lt=now).using_db(conn).update(last_activity_at=now)
    )


async def read_runs(candidates: QuerySet[Candidate], *, full: bool) -> list[RunRecord]:
    """The records of the Runs these Candidates belong to, in first-seen order, from one
    statement. ``full`` adds each Candidate's start and record (`get` only)."""
    columns = _CANDIDATE_COLUMNS + (_FULL_COLUMNS if full else ())
    rows = await candidates.values(*columns, **_RUN_COLUMNS)
    by_run: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_run.setdefault(row["run_id"], []).append(row)
    return [_run_record(group) for group in by_run.values()]


def start_to_json(start: CandidateStart) -> dict[str, Any]:
    """A start as the Candidate row keeps it; the name is the row's own column."""
    return {
        "url4": start.url4,
        "answer_seed": start.answer_seed,
        "capture": start.capture,
        "use_cache": start.use_cache,
        "replay_frozen_copy": start.replay_frozen_copy,
    }


def start_from_json(name: str, data: Mapping[str, Any]) -> CandidateStart:
    return CandidateStart(
        name=name,
        url4=data["url4"],
        answer_seed=data.get("answer_seed"),
        capture=bool(data.get("capture", False)),
        use_cache=bool(data.get("use_cache", True)),
        replay_frozen_copy=data.get("replay_frozen_copy"),
    )


def _run_record(rows: Iterable[dict[str, Any]]) -> RunRecord:
    ordered = sorted(rows, key=lambda row: row["index"])
    first = ordered[0]
    stopped_by = cast(StopReason | None, first["run_stopped_by"])
    state = derive_state(
        [cast(CandidateState, row["state"]) for row in ordered],
        canceled=stopped_by == "canceled",
    )
    ends = [row["finished_at"] for row in ordered if row["finished_at"] is not None]
    # A Run's end is its last Candidate's, once it is over and every Candidate has one.
    over = is_terminal_run(state) and len(ends) == len(ordered)
    context = None
    if first["run_context_sha256"] is not None:
        context = ContextRef(first["run_context_sha256"], first["run_context_bytes"])
    return RunRecord(
        id=first["run_id"],
        state=state,
        created_at=first["run_created_at"],
        finished_at=max(ends) if over else None,
        benchmark=first["run_benchmark"],
        case_count=first["run_case_count"],
        candidates=tuple(_candidate_record(row) for row in ordered),
        canceled=bool(first["run_canceled"]),
        detached=bool(first["run_detached"]),
        deadline_at=first["run_deadline_at"],
        stopped_by=stopped_by,
        context=context,
    )


def _candidate_record(row: Mapping[str, Any]) -> CandidateRecord:
    start = row.get("start")
    cost = row["cost_usd"]
    return CandidateRecord(
        index=row["index"],
        name=row["name"],
        state=cast(CandidateState, row["state"]),
        attempt_id=row["topic"],
        started_at=row["bound_at"],
        finished_at=row["finished_at"],
        cost_usd=None if cost is None else Decimal(cost),
        error_code=row["error_code"],
        start=None if start is None else start_from_json(row["name"], start),
        record=row.get("record"),
    )


__all__ = [
    "LIVE",
    "StoreCore",
    "in_context",
    "lock_run",
    "read_runs",
    "start_from_json",
    "start_to_json",
    "touch",
]
