"""Shared arrangement for the frozen copy sweep tests (OME-1947). Holds no test of its own."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.models import FrozenCopy, FrozenCopyEntry
from tests.unit.test_frozen_copy_support import run_async


def make_entries(n: int) -> list[Any]:
    return [("chat", {"q": i}, {"a": i}, 200) for i in range(n)]


def age_copy(
    client: TestClient, copy_id: str, *, copy_age: timedelta, entry_age: timedelta | None = None
) -> None:
    async def _update() -> None:
        now = datetime.now(UTC)
        await FrozenCopy.filter(id=UUID(copy_id)).update(created_at=now - copy_age)
        if entry_age is not None:
            await FrozenCopyEntry.filter(frozen_copy_id=UUID(copy_id)).update(
                created_at=now - entry_age
            )

    run_async(client, _update)


def read_copy(client: TestClient, copy_id: str) -> FrozenCopy:
    async def _get() -> FrozenCopy:
        return await FrozenCopy.get(id=UUID(copy_id))

    return run_async(client, _get)
