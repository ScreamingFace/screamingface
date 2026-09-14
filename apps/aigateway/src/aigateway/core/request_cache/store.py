from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

from tortoise.exceptions import BaseORMException, IntegrityError
from tortoise.expressions import F
from tortoise.transactions import in_transaction

from .entry_metadata import CACHE_ENTRY_METADATA_MAX_BYTES, CacheEntryMetadata
from .models import RequestCacheEntry

logger = logging.getLogger(__name__)

# Infrastructure failures that must degrade the cache rather than fail the request. OSError covers
# the socket/file layer under the driver, which does not always arrive wrapped as an ORM error.
INFRASTRUCTURE_ERRORS = (BaseORMException, OSError)


class CacheUnavailable(RuntimeError):
    pass


class CacheAvailability(Protocol):
    def cache_available(self) -> bool: ...


class ConfiguredCacheAvailability:
    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled

    def cache_available(self) -> bool:
        return self._enabled


class _AlwaysAvailable:
    """Default for unit fixtures that construct the store without a gate."""

    def cache_available(self) -> bool:
        return True


_UNGATED = _AlwaysAvailable()

# How many distinct unreadable-metadata keys one store instance remembers having warned about.
# The store is a process-lifetime singleton, so this bounds the set rather than the log.
_MAX_WARNED_METADATA_KEYS = 1024


@dataclass(frozen=True)
class CachedEntry:
    """One served cache row: the provider-compatible body and its metadata block.

    INVARIANT (A6/ERD §5.5): ``metadata`` is the parsed block from ``metadata_json``,
    or ``None`` when the row has no block or its block is unreadable. The body always
    serves either way — a corrupt block is treated as absent (S11), never as a reason
    to lose the hit.
    """

    response: dict[str, Any]
    metadata: CacheEntryMetadata | None = None


@dataclass(frozen=True)
class RequestCacheWrite:
    """One plaintext JSON fill with no caller identity or prompt material."""

    key_hash: str
    prompt_hash: str
    provider: str
    model: str
    response: dict[str, Any]
    response_size_bytes: int
    # A4/ERD §5.4: the standard metadata block for THIS response. The default keeps
    # every existing caller working, including the Tavily lane, which never sets it.
    metadata: CacheEntryMetadata | None = None


class RequestCacheStore(Protocol):
    async def get(self, key_hash: str) -> CachedEntry | None: ...

    async def delete_expired(self) -> int: ...

    async def set_if_absent(
        self, entry: RequestCacheWrite
    ) -> Literal["stored", "race_lost", "not_stored"]: ...

    def cache_available(self) -> bool: ...


async def record_hit_metadata(entry_id: uuid.UUID, when: datetime) -> None:
    await RequestCacheEntry.filter(id=entry_id).update(
        hit_count=F("hit_count") + 1, last_hit_at=when
    )


class TortoiseRequestCacheStore:
    """Tortoise-backed implementation of the shared exact-request cache."""

    def __init__(
        self,
        availability: CacheAvailability | None = None,
    ) -> None:
        self._availability: CacheAvailability = (
            availability if availability is not None else _UNGATED
        )
        # S11 / PRD §4.4: one warning per unreadable block, not one per hit on it.
        self._warned_metadata_keys: set[str] = set()

    def _warn_unreadable_metadata(self, key_hash: str, size_bytes: int) -> None:
        """Warn once per key that a stored block could not be read (S11, PRD §4.4).

        A popular corrupt row is hit over and over, and a warning per hit is spam rather than
        signal. The seen-set is capped: past the cap it simply stops admitting new keys, so
        memory stays bounded and the worst case is a repeated warning — never unbounded growth.
        """
        prefix = key_hash[:12]
        if prefix in self._warned_metadata_keys:
            return
        if len(self._warned_metadata_keys) < _MAX_WARNED_METADATA_KEYS:
            self._warned_metadata_keys.add(prefix)
        logger.warning(
            "request cache entry %s… metadata block was unreadable (%d bytes); "
            "serving the body without it",
            prefix,
            size_bytes,
        )

    def cache_available(self) -> bool:
        return self._availability.cache_available()

    async def delete_expired(self) -> int:
        # INVARIANT: NULL means indefinite, so the indexed comparison reaches only rows whose
        # future configurable TTL has actually elapsed.
        return await RequestCacheEntry.filter(expires_at__lte=datetime.now(UTC)).delete()

    async def get(self, key_hash: str) -> CachedEntry | None:
        """Look up one row. ``None`` means no currently serveable row; every failure raises.

        INVARIANT: an absent or expired row is a miss; read and decode failures raise.
        """
        if not self._availability.cache_available():
            # WHY raise rather than return None: `None` is this module's documented miss signal, and
            # a miss makes the route dispatch AND store. A degraded worker must not write.
            raise CacheUnavailable("this worker is not serving the global cache")

        try:
            row = await RequestCacheEntry.get_or_none(key_hash=key_hash)
        except INFRASTRUCTURE_ERRORS as exc:
            logger.warning("global cache read failed (%s); bypassing", type(exc).__name__)
            raise CacheUnavailable("global cache read failed") from exc

        if row is None:
            return None
        # Nullable expiry is part of this one lane: NULL is indefinite, a past timestamp is a miss.
        if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
            return None

        # ERD §5.5 / S11: a block that fails to parse is treated as absent. The body
        # still serves; the failure is logged once, with the key prefix only.
        metadata: CacheEntryMetadata | None = None
        if row.metadata_json is not None:
            metadata = CacheEntryMetadata.parse(row.metadata_json)
            if metadata is None:
                self._warn_unreadable_metadata(key_hash, len(row.metadata_json))

        def reject_non_finite(value: str) -> None:
            raise ValueError(f"non-finite JSON constant: {value}")

        def parse_finite_decimal(value: str) -> Decimal:
            try:
                parsed = Decimal(value)
                binary_value = float(parsed)
            except (InvalidOperation, OverflowError, ValueError) as exc:
                raise ValueError(f"invalid JSON number: {value}") from exc
            if not parsed.is_finite() or not math.isfinite(binary_value):
                raise ValueError(f"non-finite JSON number: {value}")
            return parsed

        try:
            response = json.loads(
                row.response_json,
                parse_constant=reject_non_finite,
                # Keep persisted fractional JSON exact while validating the cached row.
                # Accounting does not certify cached money because this row cannot prove
                # raw-provider provenance; the response boundary restores Decimal carriers
                # to floats so cached JSON numbers keep their prior wire shape.
                parse_float=parse_finite_decimal,
            )
            if not isinstance(response, dict):
                raise ValueError("cached payload is not a JSON object")
        except (ValueError, TypeError) as exc:
            logger.warning(
                "request cache entry %s… could not be decoded (%s); refusing to serve it and "
                "leaving the row untouched",
                key_hash[:12],
                type(exc).__name__,
            )
            raise CacheUnavailable("global cache entry could not be decoded") from exc

        try:
            await record_hit_metadata(row.id, datetime.now(UTC))
        except Exception as exc:
            # WHY broad only here: the response is already decoded and validated. Metadata is
            # best-effort, so no ordinary update failure may discard a hit already in hand.
            logger.warning(
                "global cache hit metadata was not recorded (%s); serving the hit anyway",
                type(exc).__name__,
            )
        return CachedEntry(response=response, metadata=metadata)

    async def set_if_absent(
        self, entry: RequestCacheWrite
    ) -> Literal["stored", "race_lost", "not_stored"]:
        """Create-only fill: ``stored`` won, ``race_lost`` someone else won, ``not_stored`` failed.

        INVARIANT (plan §5.3): first successful insert wins. A conflict is NEVER resolved by
        overwriting — the stored winner is what every later caller has
        already been served, and replacing it would make an identical request answer differently.
        """
        if not self._availability.cache_available():
            return "not_stored"

        try:
            payload = json.dumps(
                entry.response,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (ValueError, TypeError) as exc:
            logger.warning(
                "global cache fill could not be serialized (%s); not stored", type(exc).__name__
            )
            return "not_stored"

        metadata_json = self._serialize_metadata(entry)

        try:
            # WHY the explicit transaction: on Postgres a unique-violation aborts the whole
            # transaction it happens in. Nested inside a caller's transaction this becomes a
            # SAVEPOINT, so losing the race rolls back only this INSERT and leaves the caller's
            # transaction usable. The exception must escape the block for that rollback to run.
            #
            # AIDEV-NOTE: the most dangerous edit to this function looks like a tidy-up. Moving the
            # `except` clauses INSIDE this block leaves the aborted transaction in place, and the
            # next statement fails with "current transaction is aborted, commands ignored until end
            # of transaction block" — which then poisons the CALLER's transaction too. Extracting
            # the INSERT into a helper called from in here is fine; wrapping that helper in its own
            # try/except is not.
            async with in_transaction():
                await RequestCacheEntry.create(
                    key_hash=entry.key_hash,
                    prompt_hash=entry.prompt_hash,
                    provider=entry.provider,
                    model=entry.model,
                    response_json=payload,
                    response_size_bytes=entry.response_size_bytes,
                    expires_at=None,
                    metadata_json=metadata_json,
                )
        except IntegrityError:
            # INVARIANT: `race_lost` means the winner's row is in the table. `IntegrityError` also
            # covers other constraints, so the conflict must be CONFIRMED before it is reported as
            # a lost race. A stale schema can otherwise report a race forever against an empty
            # table.
            #
            # WHY the read is out here and not inside the `async with`: the failed INSERT already
            # aborted that transaction on Postgres, so any statement inside it would raise
            # TransactionManagementError. By now the block has exited and the savepoint is rolled
            # back, so this runs on a usable session.
            return await self._classify_fill_conflict(entry)
        except INFRASTRUCTURE_ERRORS as exc:
            # AIDEV-NOTE: this clause must stay BELOW `except IntegrityError`. The MRO is
            # IntegrityError -> OperationalError -> BaseORMException, so reordering them makes this
            # one swallow every lost race and silently report `not_stored` instead.
            logger.warning(
                "global cache fill was not persisted (%s); serving the response anyway",
                type(exc).__name__,
            )
            return "not_stored"
        return "stored"

    @staticmethod
    def _serialize_metadata(entry: RequestCacheWrite) -> str | None:
        """Serialize the metadata block, or ``None`` when it cannot be stored.

        INVARIANT (A5/S8/S9/E7): metadata is best-effort. A build or serialization
        failure, and a block over the size cap, all write the row with
        ``metadata_json = NULL`` — never fail the request and never trim the block.
        The warning carries the key-hash prefix only; never prompt or response content.
        """
        if entry.metadata is None:
            return None
        try:
            payload = entry.metadata.serialize()
        except (ValueError, TypeError) as exc:
            logger.warning(
                "global cache fill %s… metadata could not be serialized (%s); storing without it",
                entry.key_hash[:12],
                type(exc).__name__,
            )
            return None
        if payload is None:
            logger.warning(
                "global cache fill %s… metadata exceeded %d bytes; storing without it",
                entry.key_hash[:12],
                CACHE_ENTRY_METADATA_MAX_BYTES,
            )
        return payload

    async def _classify_fill_conflict(
        self, entry: RequestCacheWrite
    ) -> Literal["race_lost", "not_stored"]:
        """Did a rival fill win this key, or did the row violate some other constraint?"""
        try:
            winner_exists = await RequestCacheEntry.filter(key_hash=entry.key_hash).exists()
        except INFRASTRUCTURE_ERRORS as exc:
            logger.warning(
                "global cache fill conflict for %s… could not be classified (%s); not stored",
                entry.key_hash[:12],
                type(exc).__name__,
            )
            return "not_stored"

        if not winner_exists:
            # Loud on purpose: nothing is in the table, so no amount of traffic will fill it.
            logger.warning(
                "global cache fill %s… was rejected by a constraint other than the entry key and "
                "no row is stored; is the database schema up to date?",
                entry.key_hash[:12],
            )
            return "not_stored"

        logger.debug(
            "global cache fill %s… lost the race; keeping the stored winner",
            entry.key_hash[:12],
        )
        return "race_lost"
