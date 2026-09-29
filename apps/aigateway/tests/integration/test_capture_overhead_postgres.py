"""NFR: capture adds at most 5 ms at p99 to a traced call (OME-1307, GW-capture).

The budget comes from `prd/cache-version-store.md` section 4 and `test-plan.md` section 5. A budget
test has no honest RED: it measures. The measured numbers go into the work ledger.

FEATURE: OME-1307 (E14) - capture runs on the chat request path, so its cost is the caller's
latency.
INVARIANT: the measured cost is the WORST case, a distinct key on every call, so every call writes
a prompt row and a capture row on PostgreSQL. Half of the calls also carry a 4 KB inline body.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import asyncio
import os
import statistics
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import Request
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from aigateway.core.cache_versions.capture_store import TortoiseCaptureSink
from aigateway.core.cache_versions.ports import CaptureKey
from aigateway.core.cache_versions.stats import CaptureStats
from aigateway.db import close_db, init_db
from aigateway.routes.chat_capture_stage import CaptureContext, record_capture

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_CALLS = 1_000
_BUDGET_SECONDS = 0.005
_BODY = {"id": "resp", "choices": [{"message": {"content": "x" * 4_000}, "finish_reason": "stop"}]}


@pytest.fixture(scope="module")
def migrated_postgres() -> Generator[str, None, None]:
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = (
            f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
            f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}"
            f"/{postgres.dbname}"
        )
        subprocess.run(
            [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", "migrate"],
            cwd=_APP_DIR,
            env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
            check=True,
            capture_output=True,
            text=True,
        )
        yield database_url


def _p99(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=100, method="inclusive")[98]


async def _time_each(call: Callable[[int], Awaitable[None]]) -> list[float]:
    samples: list[float] = []
    for index in range(_CALLS):
        started = time.perf_counter()
        await call(index)
        samples.append(time.perf_counter() - started)
    return samples


def test_capture_overhead_p99_is_at_most_5_ms(migrated_postgres: str) -> None:
    request = cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    capture_sink=TortoiseCaptureSink(), capture_stats=CaptureStats()
                )
            )
        ),
    )

    def _context(index: int) -> CaptureContext:
        key = CaptureKey(key_hash=f"{index:064x}", material=f'{{"prompt":"call {index}"}}')
        return CaptureContext(account_id="acct", trace_id="a7" * 16, key=key)

    async def _with_capture(index: int) -> None:
        inline = index % 2 == 0
        await record_capture(
            request,
            _context(index),
            "bypass" if inline else "stored",
            response=_BODY if inline else None,
        )

    async def _without_capture(index: int) -> None:
        await record_capture(request, None, "stored")

    async def _run() -> tuple[float, float]:
        await close_db()
        await init_db(migrated_postgres)
        try:
            # Warm the connection pool and the statement cache so neither is billed to capture.
            for index in range(20):
                await _with_capture(_CALLS + index)
            without = await _time_each(_without_capture)
            with_capture = await _time_each(_with_capture)
            return _p99(with_capture), _p99(without)
        finally:
            await close_db()

    p99_with, p99_without = asyncio.run(_run())
    state: Any = cast(Any, request).app.state
    print(f"capture p99 with={p99_with * 1000:.3f} ms without={p99_without * 1000:.3f} ms")

    assert state.capture_stats.failures == 0, "the bench must measure successful writes"
    assert p99_with - p99_without <= _BUDGET_SECONDS
