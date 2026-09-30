"""The registry races that only a real database can show: SR-12, SR-14, SR-15.

WHY PostgreSQL: SQLite serializes writers, so two concurrent submits never overlap. Here each task
runs in its own transaction on its own connection, exactly like two requests, and an
`asyncio.Barrier` forces both to READ before either WRITES (a barrier before the read would let one
task commit first and hide the race). The loser of each race must land on the winner's committed
row through the savepoint rollback and the one retry of `RegistryService`.

WHY a self-contained connection: the same reason `scores/test_idempotency_postgres.py` gives
(OME-430). Runs only when SCOREBOARD_TEST_DATABASE_URL is set; skips otherwise.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from tortoise import Tortoise
from tortoise.transactions import in_transaction

from scoreboard.core.registry import RegistryService, Resolution, SystemNameTaken
from scoreboard.db import build_tortoise_config
from scoreboard.scores.models import System, SystemRevision
from scoreboard.scores.system_registry_store import TortoiseSystemRepository
from tests.unit.registry.conftest import FakeFingerprinter, fingerprint_of

DATABASE_URL = os.getenv("SCOREBOARD_TEST_DATABASE_URL", "")
KEVIN = "kevin@x.org"
ANA = "ana@x.org"
BRUNO = "bruno@y.org"


@asynccontextmanager
async def _database(names: list[str], texts: list[str]) -> AsyncIterator[None]:
    await Tortoise.init(config=build_tortoise_config(DATABASE_URL))
    try:
        await Tortoise.generate_schemas(safe=True)
        yield
    finally:
        # Clean only this test's rows: the database may be shared, and the names are per run.
        await SystemRevision.filter(fingerprint__in=[fingerprint_of(t) for t in texts]).delete()
        await System.filter(name__in=names).delete()
        await Tortoise.close_connections()


def _wrap_first_call_per_task(target: Any, method: str, barrier: asyncio.Barrier) -> None:
    """Make the FIRST call of `method` in each task wait at `barrier`, after the real call ran."""
    real = getattr(target, method)
    seen: set[asyncio.Task[Any] | None] = set()

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        result = await real(*args, **kwargs)
        task = asyncio.current_task()
        if task not in seen:
            seen.add(task)
            await asyncio.wait_for(barrier.wait(), timeout=10)
        return result

    setattr(target, method, wrapped)


async def _in_own_transaction(
    service: RegistryService,
    text: str,
    name: str,
    submitter: str,
    *,
    revision_of: str | None = None,
) -> Resolution:
    async with in_transaction() as connection:
        return await service.resolve_for_submit(
            text, name, revision_of, submitter, "public", connection=connection
        )


async def _race(*calls: Callable[[], Awaitable[Resolution]]) -> list[Resolution | BaseException]:
    return await asyncio.gather(*(call() for call in calls), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_sr12_concurrent_first_submits_one_revision() -> None:
    run = uuid4().hex[:8]
    name_a, name_b, text = f"sr12-a-{run}", f"sr12-b-{run}", f"U_SR12_{run}"
    async with _database([name_a, name_b], [text]):
        repository = TortoiseSystemRepository()
        service = RegistryService(repository, FakeFingerprinter())
        _wrap_first_call_per_task(repository, "find_revision_by_fingerprint", asyncio.Barrier(2))

        results = await _race(
            lambda: _in_own_transaction(service, text, name_a, ANA),
            lambda: _in_own_transaction(service, text, name_b, BRUNO),
        )

        assert all(isinstance(result, Resolution) for result in results), results
        outcomes = sorted(result.outcome for result in results if isinstance(result, Resolution))
        assert outcomes == ["new", "renamed_notice"]
        assert await SystemRevision.filter(fingerprint=fingerprint_of(text)).count() == 1
        # INVARIANT: the loser's savepoint removed its own System row.
        assert await System.filter(name__in=[name_a, name_b]).count() == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_sr14_concurrent_name_claims_one_winner() -> None:
    run = uuid4().hex[:8]
    name, text_a, text_b = f"sr14-{run}", f"U_SR14_A_{run}", f"U_SR14_B_{run}"
    async with _database([name], [text_a, text_b]):
        repository = TortoiseSystemRepository()
        service = RegistryService(repository, FakeFingerprinter())
        _wrap_first_call_per_task(repository, "find_revision_by_fingerprint", asyncio.Barrier(2))

        results = await _race(
            lambda: _in_own_transaction(service, text_a, name, ANA),
            lambda: _in_own_transaction(service, text_b, name, BRUNO),
        )

        winners = [result for result in results if isinstance(result, Resolution)]
        losers = [result for result in results if isinstance(result, SystemNameTaken)]
        assert len(winners) == 1 and len(losers) == 1, results
        assert winners[0].outcome == "new"
        assert await System.filter(name=name).count() == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_sr15_concurrent_revisions_contiguous() -> None:
    run = uuid4().hex[:8]
    name = f"sr15-{run}"
    texts = [f"U_SR15_{index}_{run}" for index in (1, 2, 3)]
    async with _database([name], texts):
        repository = TortoiseSystemRepository()
        service = RegistryService(repository, FakeFingerprinter())
        await _in_own_transaction(service, texts[0], name, KEVIN)
        _wrap_first_call_per_task(repository, "_next_revision_number", asyncio.Barrier(2))

        results = await _race(
            lambda: _in_own_transaction(service, texts[1], name, KEVIN, revision_of=name),
            lambda: _in_own_transaction(service, texts[2], name, KEVIN, revision_of=name),
        )

        assert all(isinstance(result, Resolution) for result in results), results
        system = await System.get(name=name)
        numbers = await _revision_numbers(system.id)
        assert numbers == [1, 2, 3]


async def _revision_numbers(system_id: UUID) -> list[int]:
    rows = await SystemRevision.filter(system_id=system_id).order_by("revision")
    return [row.revision for row in rows]
