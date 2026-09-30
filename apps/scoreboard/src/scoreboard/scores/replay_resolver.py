"""`ReplayPinResolver`: the Tortoise adapter that turns a pin into ONE result (C6, RP-D4).

FEATURE: OME-1307 (E14) replay grants. The pin resolves once, here; the grant names the result.

INVARIANT (OME-894): the access rule is `core/replay_access.py`, never copied. A private or gated
result of another user is `PinNotFound`, the same answer as an unknown id, and it is decided BEFORE
the withdrawn and the benchmark-mismatch answers, so no refusal confirms that such a result exists.

AIDEV-NOTE: this adapter only reads. It writes no row and makes no grant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from tortoise.queryset import QuerySet

from scoreboard.core.registry import (
    DatePin,
    PinNotFound,
    RegistryService,
    RevisionRef,
)
from scoreboard.core.replay.grants import PinBenchmarkMismatch, PinWithdrawn, ResolvedReplay
from scoreboard.core.replay.pins import ReplayPin, ResultPin, ScorePin
from scoreboard.core.replay_access import Access, is_owner, replay_access

from .cluster_store import ClusterStore
from .models import Benchmark, ReportedResult

# WHY 100: the scan never loads all rows of a big cluster; it stops at the first readable row.
_PAGE = 100
_SCAN_COLUMNS = ("id", "head_id", "reporter", "cache_version_id", "submitted_at")


@dataclass(frozen=True, slots=True)
class _Ask:
    """What one request asks for, kept together so each rule takes one argument."""

    raw_pin: str
    benchmark: Benchmark
    caller: str | None
    identity_verified: bool


class ReplayPinResolver:
    def __init__(self, cluster_store: ClusterStore, registry: RegistryService) -> None:
        self._cluster_store = cluster_store
        self._registry = registry

    async def resolve(
        self,
        pin: ReplayPin,
        raw_pin: str,
        *,
        benchmark_id: str,
        caller: str | None,
        identity_verified: bool,
    ) -> ResolvedReplay:
        benchmark = await Benchmark.get_or_none(id=benchmark_id)
        if benchmark is None:
            # OD-5: an unknown board answers like an unknown pin.
            raise PinNotFound(raw_pin)
        ask = _Ask(raw_pin, benchmark, caller, identity_verified)
        if isinstance(pin, ResultPin | ScorePin):
            return await self._resolve_direct(pin, ask)
        return await self._resolve_by_system(pin, ask)

    # -- a direct pin: result:<uuid> or score:<uuid> --------------------------------------------

    async def _resolve_direct(self, pin: ResultPin | ScorePin, ask: _Ask) -> ResolvedReplay:
        result_id = (
            pin.result_id if isinstance(pin, ResultPin) else await self._original_of(pin, ask)
        )
        target = await self._cluster_store.load_replay_target(result_id)
        if target is None:
            raise PinNotFound(ask.raw_pin)
        access = _access(target.benchmark, target.result, target.publication_state, ask)
        # The order is fixed: 404 class first, then 410, then 422 (see the module INVARIANT).
        if access == "not_found" or target.result.cache_version_id is None:
            raise PinNotFound(ask.raw_pin)
        if access == "withdrawn":
            raise PinWithdrawn(ask.raw_pin)
        if getattr(target.head, "benchmark_id") != ask.benchmark.id:
            raise PinBenchmarkMismatch(ask.raw_pin)
        return _resolved(target.result, ask)

    async def _original_of(self, pin: ScorePin, ask: _Ask) -> UUID:
        original = await ReportedResult.filter(head_id=pin.score_id, is_original=True).first()
        if original is None:
            raise PinNotFound(ask.raw_pin)
        return original.id

    # -- a system pin: name, name@r<N>, name@<date or time> ---------------------------------------

    async def _resolve_by_system(self, pin: ReplayPin, ask: _Ask) -> ResolvedReplay:
        resolved = await self._registry.resolve_pin(ask.raw_pin)
        board = ask.benchmark.id
        if isinstance(pin, DatePin) and isinstance(resolved, list):
            # RP-H2: the newest accessible result of ANY revision of the name, original or not.
            rows = ReportedResult.filter(
                cache_version_id__isnull=False,
                submitted_at__lte=pin.at,
                head__system_revision_id__in=[revision.id for revision in resolved],
                head__benchmark_id=board,
            )
        else:
            revision = cast(RevisionRef, resolved)
            # OD-3: the newest versioned ORIGINAL of that revision on this board.
            rows = ReportedResult.filter(
                is_original=True,
                cache_version_id__isnull=False,
                head__system_revision_id=revision.id,
                head__benchmark_id=board,
            )
        return await self._first_readable(rows, ask)

    async def _first_readable(self, rows: QuerySet[ReportedResult], ask: _Ask) -> ResolvedReplay:
        """The first row, newest first `(submitted_at, id)` descending, that the caller may read.

        A withdrawn row is NOT skipped (OD-3): it answers 410.
        """
        ordered = rows.order_by("-submitted_at", "-id")
        offset = 0
        while True:
            page = await ordered.offset(offset).limit(_PAGE).only(*_SCAN_COLUMNS)
            states = await self._cluster_store.publication_states([row.id for row in page])
            for row in page:
                access = _access(ask.benchmark, row, states.get(str(row.id)), ask)
                if access == "withdrawn":
                    raise PinWithdrawn(ask.raw_pin)
                if access == "allow":
                    return _resolved(row, ask)
            if len(page) < _PAGE:
                raise PinNotFound(ask.raw_pin)
            offset += _PAGE


def _access(
    benchmark: Benchmark, row: ReportedResult, publication_state: str | None, ask: _Ask
) -> Access:
    return replay_access(
        board_visibility=benchmark.visibility,
        redistributable=benchmark.redistributable,
        reporter=row.reporter,
        publication_state=publication_state,
        caller=ask.caller,
        identity_verified=ask.identity_verified,
    )


def _resolved(row: ReportedResult, ask: _Ask) -> ResolvedReplay:
    # `cache_version_id` is not None here: the filters and the direct check both require it.
    return ResolvedReplay(
        result_id=row.id,
        score_id=cast(UUID, getattr(row, "head_id")),
        cache_version_id=cast(UUID, row.cache_version_id),
        via_owner=is_owner(ask.caller, row.reporter, identity_verified=ask.identity_verified),
    )
