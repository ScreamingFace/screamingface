"""Persist source check outcomes without changing observations or ranking."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from tortoise.transactions import in_transaction

from scoreboard.db import DEFAULT_CONNECTION

from .models import SourceHealth


class SourceHealthSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    checked_at: datetime
    last_available_at: datetime | None


def source_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


async def read_health(urls: Iterable[str]) -> dict[str, SourceHealthSchema]:
    keys = {source_key(url) for url in urls}
    rows = await SourceHealth.filter(source_key__in=keys) if keys else []
    return {
        row.source_url: SourceHealthSchema(
            available=row.available,
            checked_at=row.checked_at,
            last_available_at=row.last_available_at,
        )
        for row in rows
    }


async def record_check(url: str, *, available: bool, checked_at: datetime) -> None:
    async with in_transaction(connection_name=DEFAULT_CONNECTION) as connection:
        row, _ = await SourceHealth.get_or_create(
            source_key=source_key(url),
            defaults={"source_url": url, "available": available, "checked_at": checked_at},
            using_db=connection,
        )
        locked = (
            await SourceHealth.filter(source_key=row.source_key)
            .using_db(connection)
            .select_for_update()
            .get()
        )
        # INVARIANT: late completion must not overwrite a newer check. An earlier
        # successful attempt can still establish the last known availability.
        if checked_at > locked.checked_at:
            locked.checked_at = checked_at
            locked.available = available
        if available and (
            locked.last_available_at is None or checked_at > locked.last_available_at
        ):
            locked.last_available_at = checked_at
        await locked.save(
            using_db=connection, update_fields=["available", "checked_at", "last_available_at"]
        )
