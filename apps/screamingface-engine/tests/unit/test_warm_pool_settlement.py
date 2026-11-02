"""The warm pool reads a child's `SETTLED` line after its run (OME-1785, E5 P1 spec R3)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from test_warm_pool import RUN_ENV, _FakeChild, _settle, _Spawner

from screamingface_engine import child_protocol as cp
from screamingface_engine.worker.warm_pool import WarmChildPool

pytestmark = pytest.mark.asyncio


async def _launched(child: _FakeChild) -> tuple[WarmChildPool, _FakeChild]:
    pool = WarmChildPool(spawn_warm=_Spawner(child, _FakeChild(99)), size=1)
    pool.start()
    await _settle()
    assert await pool.launch(RUN_ENV, io_budget=lambda: 1) is child
    return pool, child


async def test_a_settled_line_is_read_after_the_run() -> None:
    pool, child = await _launched(_FakeChild(1))
    settled = cp.Settled("succeeded", None, Decimal("0.5"))
    child.control.feed_data(cp.encode_settled(settled))
    child.exit(0)

    assert await pool.settlement(child) == settled
    await pool.drain()


async def test_a_child_that_died_before_reporting_has_none() -> None:
    pool, child = await _launched(_FakeChild(1))
    child.kill()

    assert await pool.settlement(child) is None
    await pool.drain()


async def test_a_malformed_settled_line_reads_as_none() -> None:
    pool, child = await _launched(_FakeChild(1))
    child.control.feed_data(b"SETTLED nonsense\n")
    child.exit(0)

    assert await pool.settlement(child) is None
    await pool.drain()


async def test_a_settlement_is_read_once() -> None:
    pool, child = await _launched(_FakeChild(1))
    child.control.feed_data(cp.encode_settled(cp.Settled("stopped", None, None)))
    child.exit(0)

    assert await pool.settlement(child) is not None
    assert await pool.settlement(child) is None
    await pool.drain()


async def test_a_forgotten_child_has_none() -> None:
    pool, child = await _launched(_FakeChild(1))
    pool.forget(child)
    child.exit(0)

    assert await pool.settlement(child) is None
    await pool.drain()
