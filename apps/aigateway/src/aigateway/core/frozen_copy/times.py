"""Time helpers for the frozen copy (OME-1947)."""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["as_utc"]


def as_utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC time."""
    # WHY: TORTOISE_CONFIG sets no use_tz, so a stored time can come back naive. A naive time
    # from the database is UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
