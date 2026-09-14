"""Cache-entry metadata builders that bridge the accounting session and the cache row.

FEATURE (PRD tasks B1, B2): the write path needs a standard metadata block beside every
cached response, and the hit path needs to turn that block back into a ``CacheReference``.

HEXAGONAL: this module lives in ``plugins/taxonomy`` because it reads an
``AccountingSession`` and produces taxonomy value objects. It imports ``core`` (the
``CacheEntryMetadata`` DTO) and never the other way round.

INVARIANTS:
* PRD S8/S11/M1: ``cache_entry_metadata_from_session`` never raises. Any failure yields
  ``None`` so the row is still written, and any absent block still serves the body.
* PRD S7/M8: ``direct_cost`` is passed through verbatim ONLY for a ``complete`` or
  ``archive_paired`` capture. A ``partial`` capture must never certify a price.
* ERD §3.5/M5/M7: money and counts are re-validated through the canonical ``DirectCost`` /
  ``TokenUsage`` constructors on the way in, so a corrupt stored block fails narrowly.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, get_args

from ...core.request_cache.entry_metadata import CacheEntryMetadata
from .render import MAX_RENDERED_ATTEMPTS
from .types import (
    CacheReference,
    CacheWriteTTL,
    DirectCost,
    DirectCostStatus,
    InputTokenUsage,
    OutputTokenUsage,
    TokenUsage,
    UsageEvidenceStatus,
)

if TYPE_CHECKING:  # avoids a circular import with ``session``, which imports this module
    from .session import AccountingSession

logger = logging.getLogger(__name__)

__all__ = [
    "CacheEntryMetadataReferenceError",
    "cache_entry_metadata_from_session",
    "cache_reference_from_entry_metadata",
]


class CacheEntryMetadataReferenceError(RuntimeError):
    """A stored block cannot build a ``CacheReference``.

    INVARIANT (PRD S11, ERD R2): narrow and internal. The hit path catches exactly this
    and falls back to the provider's existing mapper; it is never surfaced to a caller.
    """


# The statuses whose stored cost the reference may certify. A ``partial`` capture is
# deliberately excluded (ERD §3.5) — an incomplete observation is not evidence of a price.
# AIDEV-NOTE: `archive_paired` has NO producer in this repo and is not dead code. Blocks
# carrying it are written by the out-of-band archive loader, which constructs
# `CacheEntryMetadata` directly; `cache_entry_metadata_from_session` below only ever emits
# `complete` or `partial`. The READ path is what lives here, and it is exercised by
# `test_an_archive_paired_block_is_certified_like_a_reported_one`.
_CERTIFYING_STATUSES = frozenset({"complete", "archive_paired"})

# The canonical status vocabularies, read off the Literals themselves so a new member added
# in ``types.py`` is admitted here with no edit.
_USAGE_STATUSES: Final[tuple[UsageEvidenceStatus, ...]] = get_args(UsageEvidenceStatus)
_COST_STATUSES: Final[tuple[DirectCostStatus, ...]] = get_args(DirectCostStatus)


def _usage_status(value: Any) -> UsageEvidenceStatus:
    """Narrow a stored usage status to the canonical vocabulary.

    A stored block is bytes on disk and can be hand-edited, so an unrecognised status is a
    defect in the block rather than a new status: it raises, and the caller maps that to the
    provider's fallback mapper (PRD S11). Comparing member-by-member rather than testing set
    membership also keeps an unhashable value from raising a different error here.
    """
    for status in _USAGE_STATUSES:
        if value == status:
            return status
    raise ValueError("usage.status is not a canonical status")


def _cost_status(value: Any) -> DirectCostStatus:
    """Narrow a stored cost status to the canonical vocabulary. See :func:`_usage_status`."""
    for status in _COST_STATUSES:
        if value == status:
            return status
    raise ValueError("direct_cost.status is not a canonical status")


def _count(value: Any, *, field_name: str) -> int | None:
    """A bounded optional count, or a ``ValueError`` the builder maps to a fallback."""
    if value is None:
        return None
    if type(value) is not int or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer or null")
    return value


def _required_count(value: Any, *, field_name: str) -> int:
    parsed = _count(value, field_name=field_name)
    if parsed is None:
        raise ValueError(f"{field_name} is required")
    return parsed


def _input_usage_from_json(data: Any) -> InputTokenUsage:
    if type(data) is not dict:
        raise ValueError("usage.input must be a JSON object")
    ttl_rows = data.get("cache_write_by_ttl")
    if ttl_rows is None:
        ttl_rows = []
    if type(ttl_rows) is not list or any(type(row) is not dict for row in ttl_rows):
        raise ValueError("usage.input.cache_write_by_ttl must be a JSON array of objects")
    return InputTokenUsage(
        total=_count(data.get("total"), field_name="usage.input.total"),
        uncached=_count(data.get("uncached"), field_name="usage.input.uncached"),
        cache_read=_count(data.get("cache_read"), field_name="usage.input.cache_read"),
        cache_write=_count(data.get("cache_write"), field_name="usage.input.cache_write"),
        cache_write_by_ttl=tuple(
            CacheWriteTTL(
                ttl_seconds=_required_count(
                    row.get("ttl_seconds"), field_name="usage.input.cache_write_by_ttl.ttl_seconds"
                ),
                tokens=_required_count(
                    row.get("tokens"), field_name="usage.input.cache_write_by_ttl.tokens"
                ),
            )
            for row in ttl_rows
        ),
    )


def _output_usage_from_json(data: Any) -> OutputTokenUsage:
    if type(data) is not dict:
        raise ValueError("usage.output must be a JSON object")
    return OutputTokenUsage(
        total=_count(data.get("total"), field_name="usage.output.total"),
        reasoning=_count(data.get("reasoning"), field_name="usage.output.reasoning"),
    )


def _token_usage_from_json(data: Any) -> TokenUsage:
    """Rebuild the stored canonical usage, rewriting the source for a replayed response.

    The stored block keeps ``provider_raw_response`` as provenance of how the bytes first
    arrived; the reference reports how THIS response reached the caller, which is
    ``cached_converted_response`` (ERD §3.5).
    """
    if type(data) is not dict:
        raise ValueError("usage must be a JSON object")
    return TokenUsage(
        status=_usage_status(data.get("status")),
        source="cached_converted_response",
        input=_input_usage_from_json(data.get("input")),
        output=_output_usage_from_json(data.get("output")),
    )


def _direct_cost_from_json(data: Any) -> DirectCost:
    if type(data) is not dict:
        raise ValueError("direct_cost must be a JSON object")
    return DirectCost(
        status=_cost_status(data.get("status")),
        amount=data.get("amount"),
        unit=data.get("unit"),
        source=data.get("source"),
    )


def cache_entry_metadata_from_session(
    session: AccountingSession | None,
) -> CacheEntryMetadata | None:
    """The standard metadata block for the response this session finalized.

    Derivation (ERD §3.2): every field is copied from the collector's own records. The
    record chosen is the LAST SUCCEEDED send — the one whose body became the caller's
    answer — and ``provider_latency_ms`` is summed across every observed attempt.
    Nothing is computed, nothing is invented.

    INVARIANT: totally non-raising. ``None`` means "no block"; the row is still written.
    """
    try:
        collector = getattr(session, "collector", None)
        if collector is None:
            return None
        records = collector.records()
        if not records:
            return None
        chosen = next(
            (record for record in reversed(records) if record.outcome == "succeeded"),
            None,
        )
        if chosen is None:
            # Only a successful final response is served, so there is nothing to describe.
            return None
        latencies = [record.latency_ms for record in records if record.latency_ms is not None]
        capture_complete = (
            collector.status() == "complete" and len(records) <= MAX_RENDERED_ATTEMPTS
        )
        return CacheEntryMetadata(
            metadata_status="complete" if capture_complete else "partial",
            observed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            response_model=chosen.response_model,
            usage=chosen.usage.as_json(),
            direct_cost=chosen.direct_cost.as_json(),
            provider_latency_ms=sum(latencies) if latencies else None,
        )
    except Exception:
        # S8: a build failure writes the row with metadata_json = NULL. It never fails
        # the request and never loses the answer.
        # AIDEV-NOTE: `exc_info` is deliberate and does NOT weaken S8 — the handler still
        # swallows. Without it a genuine defect here (an AttributeError after a refactor of
        # `collector`, say) logs identically to an expected malformed capture, and the cause is
        # unrecoverable from the logs. The provider name alone cannot tell those two apart.
        logger.warning(
            "cache-entry metadata could not be built provider=%s",
            getattr(session, "provider", "unknown"),
            exc_info=True,
        )
        return None


def cache_reference_from_entry_metadata(meta: CacheEntryMetadata) -> CacheReference:
    """Map a stored block to the hit-path reference (ERD §3.5).

    RAISES ``CacheEntryMetadataReferenceError`` on any construction failure. The caller
    maps exactly this error to the provider's fallback mapper (PRD S11).
    """
    if not isinstance(meta, CacheEntryMetadata):
        raise CacheEntryMetadataReferenceError("stored cache-entry metadata has the wrong type")
    try:
        usage = _token_usage_from_json(meta.usage)
        direct_cost = _direct_cost_from_json(meta.direct_cost)
    except (ValueError, TypeError, KeyError) as exc:
        raise CacheEntryMetadataReferenceError(
            "stored cache-entry metadata could not be rebuilt"
        ) from exc
    if meta.metadata_status not in _CERTIFYING_STATUSES:
        # §3.5: a partial capture must never certify a price. No value is inferred from
        # the cached body either (R2).
        direct_cost = DirectCost.unavailable()
    try:
        return CacheReference(
            usage=usage,
            direct_cost=direct_cost,
            provider_latency_ms=meta.provider_latency_ms,
        )
    except (ValueError, TypeError) as exc:
        raise CacheEntryMetadataReferenceError(
            "stored cache-entry metadata produced an invalid reference"
        ) from exc
