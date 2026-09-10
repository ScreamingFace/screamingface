"""OME-1044 — persistence for the Tavily retrieval cache lane.

FEATURE: one shared row per exact Tavily retrieval request, so a repeated search or
fetch is neither re-paid nor re-randomized.

WHY it reuses `request_cache_entries` rather than adding a table (owner decision): zero
migration, and the per-provider reset already documented in DEPLOYMENT.md
(`DELETE FROM request_cache_entries WHERE provider = 'tavily'`) becomes this lane's
correction path for free.

INVARIANT: every row this lane writes carries `provider='tavily'`, and every read filters
on it. That column is the ONLY thing separating this lane from the chat lane in a shared
table, so the targeted reset and any operator inspection depend on it.

INVARIANT: no expiry. `expires_at` is NULL, exactly as the chat lane writes it — the
owner chose determinism (a re-run keys AND answers identically) over freshness, with
manual pruning as the correction path.

INVARIANT: this lane is UNCONDITIONAL (owner decision). There is deliberately no operator
switch and no availability gate — retrieval results are always cached. The only
degradation is a runtime store failure, which surfaces as `CacheUnavailable` on read and
`not_stored` on write; neither is configuration.

AIDEV-NOTE: the exception discipline here is copied from `TortoiseRequestCacheStore` on
purpose, including the clause ORDER in `set_if_absent`. Read that class before changing
anything here; the traps it documents apply verbatim.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from .models import RequestCacheEntry
from .store import INFRASTRUCTURE_ERRORS, CacheUnavailable, record_hit_metadata
from .tavily_retrieval import TAVILY_PROVIDER

logger = logging.getLogger(__name__)

# WHY a JSON OBJECT and not the bare result string: the column is shared with the chat
# lane, and the generic readers over it (admin cache, snapshot, bulk loader) assume a
# JSON object. A bare string would parse and then break their `isinstance(..., dict)`.
_RESULT_MEMBER = "result"


@dataclass(frozen=True)
class TavilyRetrievalCacheWrite:
    """One retrieval fill. No caller identity, no credential, no request description."""

    key_hash: str
    tool: str
    result: str


@dataclass(frozen=True)
class TavilyRetrievalHit:
    """A served row: the stored result and how long ago it was filled."""

    result: str
    age_seconds: int


class TavilyRetrievalCacheStore:
    """Insert-only store for the Tavily retrieval lane.

    Stateless and unconditional — there is no operator gate to hold, which is why this
    class takes no constructor arguments. It stays a class rather than loose functions so
    the route can be handed a fake through ``app.state``.
    """

    async def get(self, key_hash: str) -> TavilyRetrievalHit | None:
        """One row. ``None`` means no serveable row; every failure raises.

        WHY raise rather than return None on failure: ``None`` is this module's
        documented MISS signal, and a miss makes the caller pay Tavily and then fill. A
        store that just failed to read must not be talked into writing.
        """
        try:
            row = await RequestCacheEntry.get_or_none(key_hash=key_hash, provider=TAVILY_PROVIDER)
        except INFRASTRUCTURE_ERRORS as exc:
            logger.warning("tavily retrieval cache read failed (%s); bypassing", type(exc).__name__)
            raise CacheUnavailable("tavily retrieval cache read failed") from exc

        if row is None:
            return None

        try:
            payload = json.loads(row.response_json)
            if not isinstance(payload, dict):
                raise ValueError("cached tavily payload is not a JSON object")
            result = payload[_RESULT_MEMBER]
            if not isinstance(result, str):
                raise ValueError("cached tavily result is not a string")
        except (ValueError, TypeError, KeyError) as exc:
            # INVARIANT: never serve a half-understood payload, and leave the row alone so
            # it can be inspected. The caller sees the cache as unavailable and dispatches.
            logger.warning(
                "tavily retrieval cache entry %s… could not be decoded (%s); refusing to "
                "serve it and leaving the row untouched",
                key_hash[:12],
                type(exc).__name__,
            )
            raise CacheUnavailable("tavily retrieval cache entry could not be decoded") from exc

        try:
            await record_hit_metadata(row.id, datetime.now(UTC))
        except Exception as exc:
            # WHY broad only here: the result is already decoded and validated. Metadata is
            # best-effort, so no ordinary update failure may discard a hit already in hand.
            logger.warning(
                "tavily retrieval cache hit metadata was not recorded (%s); serving anyway",
                type(exc).__name__,
            )

        return TavilyRetrievalHit(result=result, age_seconds=_age_seconds(row.created_at))

    async def set_if_absent(
        self, entry: TavilyRetrievalCacheWrite
    ) -> Literal["stored", "race_lost", "not_stored"]:
        """Create-only fill: ``stored`` won, ``race_lost`` someone else won, else failed.

        INVARIANT: first successful insert wins. A conflict is NEVER resolved by
        overwriting — the stored winner is what every later caller has already been
        served, and replacing it would make an identical request answer differently.
        """
        payload = json.dumps(
            {_RESULT_MEMBER: entry.result}, separators=(",", ":"), ensure_ascii=False
        )

        try:
            # WHY the explicit transaction: on Postgres a unique-violation aborts the whole
            # transaction it happens in. Nested inside a caller's transaction this becomes a
            # SAVEPOINT, so losing the race rolls back only this INSERT. The exception must
            # escape the block for that rollback to run — see `TortoiseRequestCacheStore`.
            async with in_transaction():
                await RequestCacheEntry.create(
                    key_hash=entry.key_hash,
                    # The chat lane writes the full-call digest here too; there is no second
                    # digest to keep in sync, and the column has no read path.
                    prompt_hash=entry.key_hash,
                    provider=TAVILY_PROVIDER,
                    model=entry.tool,
                    response_json=payload,
                    response_size_bytes=len(payload.encode("utf-8")),
                    expires_at=None,
                )
        except IntegrityError:
            return await self._classify_fill_conflict(entry)
        except INFRASTRUCTURE_ERRORS as exc:
            # AIDEV-NOTE: this clause must stay BELOW `except IntegrityError`. The MRO is
            # IntegrityError -> OperationalError -> BaseORMException, so reordering them
            # makes this one swallow every lost race and report `not_stored` instead.
            logger.warning(
                "tavily retrieval cache fill was not persisted (%s); serving the result anyway",
                type(exc).__name__,
            )
            return "not_stored"
        return "stored"

    async def _classify_fill_conflict(
        self, entry: TavilyRetrievalCacheWrite
    ) -> Literal["race_lost", "not_stored"]:
        """Did a rival fill win this key, or did the row violate another constraint?"""
        try:
            winner_exists = await RequestCacheEntry.filter(key_hash=entry.key_hash).exists()
        except INFRASTRUCTURE_ERRORS as exc:
            logger.warning(
                "tavily retrieval cache fill conflict for %s… could not be classified (%s)",
                entry.key_hash[:12],
                type(exc).__name__,
            )
            return "not_stored"

        if not winner_exists:
            # Loud on purpose: nothing is in the table, so no amount of traffic will fill it.
            logger.warning(
                "tavily retrieval cache fill %s… was rejected by a constraint other than the "
                "entry key and no row is stored; is the database schema up to date?",
                entry.key_hash[:12],
            )
            return "not_stored"

        logger.debug(
            "tavily retrieval cache fill %s… lost the race; keeping the stored winner",
            entry.key_hash[:12],
        )
        return "race_lost"


def _age_seconds(created_at: datetime) -> int:
    """Whole seconds since the row was filled, never negative.

    AIDEV-NOTE: SQLite can hand back a naive datetime, so the tzinfo is normalized rather
    than assumed — subtracting a naive from an aware datetime raises.
    """
    created = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - created).total_seconds()))
