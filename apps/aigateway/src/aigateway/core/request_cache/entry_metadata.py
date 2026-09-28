"""The standard metadata block stored beside one cached provider response.

This is a **core** value object. It holds plain primitives only — ``str``, ``int``,
``None`` and ``dict`` — and imports nothing from ``plugins`` (hexagonal rule: core
never imports plugins). The canonical ``TokenUsage`` / ``DirectCost`` shapes arrive
already rendered as their ``as_json()`` dictionaries, produced by the taxonomy
layer at the write call site. This module owns the persisted shape, the size cap and
the JSON codec, not the meaning of the values inside ``usage`` and ``direct_cost``.

Design references:
* PRD ``docs/spec/2026-09-13-cache-entry-metadata-prd.md`` tasks A1, A5, A6.
* ERD ``docs/spec/2026-09-13-cache-entry-metadata-erd.md`` §3.2 (block shape), §5.4,
  §5.5, invariant M9 (drop whole, no trimming ladder), S11 (parse never raises).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal

# The block is bounded by construction: every field already passes the taxonomy
# ``DirectCost`` / ``TokenUsage`` validators, and the measured block is ~400 bytes.
# A breach means a bug, so the block is dropped WHOLE rather than trimmed (M9).
CACHE_ENTRY_METADATA_MAX_BYTES = 2048

# The version lives in the string, matching every other schema id in the repo.
CACHE_ENTRY_METADATA_SCHEMA = "aigw.cache-entry-metadata.v1"

MetadataStatus = Literal["complete", "partial", "archive_paired"]

_METADATA_STATUSES: frozenset[str] = frozenset({"complete", "partial", "archive_paired"})


def _reject_non_finite_constant(value: str) -> None:
    """``json.loads`` hook: reject the non-standard ``NaN`` / ``Infinity`` literals."""
    raise ValueError(f"non-finite JSON constant: {value}")


def _parse_finite_float(value: str) -> float:
    """``json.loads`` hook: reject a finite-looking literal that overflows to inf."""
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _decoded_payload(raw: str | bytes | dict[str, Any]) -> Any:
    """The stored block as a Python object, rejecting non-finite numbers on the way in.

    Raises ``ValueError`` / ``TypeError`` on a malformed payload; :meth:`CacheEntryMetadata.parse`
    turns either into ``None``.
    """
    if isinstance(raw, dict):
        return raw
    return json.loads(
        raw,
        parse_constant=_reject_non_finite_constant,
        parse_float=_parse_finite_float,
    )


def _validated_shape(data: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """The ``(usage, direct_cost, latency)`` triple a well-formed block must carry.

    ``None`` means the payload is not a block this gateway wrote — a wrong schema id, an
    unknown status, or a missing sub-object. Split out of :meth:`CacheEntryMetadata.parse` so
    the decode, the shape check and the construction each stay readable on their own.
    """
    if type(data) is not dict:
        return None
    if data.get("schema") != CACHE_ENTRY_METADATA_SCHEMA:
        return None
    if data.get("metadata_status") not in _METADATA_STATUSES:
        return None
    usage = data.get("usage")
    direct_cost = data.get("direct_cost")
    if type(usage) is not dict or type(direct_cost) is not dict:
        return None
    # An absent ``latency`` is a block with no measured latency, not a malformed one.
    latency = data.get("latency")
    if latency is None:
        latency = {}
    if type(latency) is not dict:
        return None
    return usage, direct_cost, latency


@dataclass(frozen=True)
class CacheEntryMetadata:
    """The metadata for one cached response, as stored in ``metadata_json``.

    ``usage`` and ``direct_cost`` are the canonical ``TokenUsage.as_json()`` and
    ``DirectCost.as_json()`` dictionaries, stored verbatim. ``provider_latency_ms``
    is the provider latency summed across attempts; it is nested under ``latency``
    in the serialized block.
    """

    metadata_status: MetadataStatus
    observed_at: str | None = None
    response_model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    direct_cost: dict[str, Any] = field(default_factory=dict)
    provider_latency_ms: int | None = None
    schema: str = CACHE_ENTRY_METADATA_SCHEMA

    def __post_init__(self) -> None:
        if type(self.metadata_status) is not str or self.metadata_status not in _METADATA_STATUSES:
            raise ValueError("metadata_status must use the canonical vocabulary")
        if type(self.schema) is not str or self.schema != CACHE_ENTRY_METADATA_SCHEMA:
            raise ValueError("schema must be the cache-entry-metadata schema id")
        if type(self.usage) is not dict:
            raise ValueError("usage must be a JSON object")
        if type(self.direct_cost) is not dict:
            raise ValueError("direct_cost must be a JSON object")
        if self.observed_at is not None and type(self.observed_at) is not str:
            raise ValueError("observed_at must be a string or None")
        if self.response_model is not None and type(self.response_model) is not str:
            raise ValueError("response_model must be a string or None")
        if self.provider_latency_ms is not None and (
            type(self.provider_latency_ms) is not int or self.provider_latency_ms < 0
        ):
            raise ValueError("provider_latency_ms must be a non-negative int or None")

    def as_json_dict(self) -> dict[str, Any]:
        """The ERD §3.2 block shape, ready to serialize."""
        return {
            "schema": self.schema,
            "metadata_status": self.metadata_status,
            "observed_at": self.observed_at,
            "response_model": self.response_model,
            "usage": self.usage,
            "direct_cost": self.direct_cost,
            "latency": {"provider_latency_ms": self.provider_latency_ms},
        }

    def serialize(self) -> str | None:
        """Compact JSON, or ``None`` when the block breaches the byte cap (M9).

        A genuine serialization failure (a non-serializable value, ``NaN`` or
        ``Infinity``) propagates as ``ValueError`` / ``TypeError``. The store wraps
        the call so that either failure writes the row with ``metadata_json = NULL``
        and never fails the request (S8, S9).
        """
        payload = json.dumps(
            self.as_json_dict(),
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if len(payload.encode("utf-8")) > CACHE_ENTRY_METADATA_MAX_BYTES:
            return None
        return payload

    @classmethod
    def parse(cls, raw: str | bytes | dict[str, Any] | None) -> CacheEntryMetadata | None:
        """Decode a stored block. Never raises: any defect yields ``None`` (S11)."""
        if raw is None:
            return None
        try:
            data = _decoded_payload(raw)
        except (ValueError, TypeError):
            return None
        shape = _validated_shape(data)
        if shape is None:
            return None
        usage, direct_cost, latency = shape
        try:
            return cls(
                metadata_status=data["metadata_status"],
                observed_at=data.get("observed_at"),
                response_model=data.get("response_model"),
                usage=usage,
                direct_cost=direct_cost,
                provider_latency_ms=latency.get("provider_latency_ms"),
            )
        except (ValueError, TypeError):
            return None
