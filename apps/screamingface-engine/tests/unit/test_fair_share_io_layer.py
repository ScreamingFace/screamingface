"""The fair-share I/O layer wrapper contract (OME-908).

``FairShareIOLayer`` wraps an inner URL4 capability layer and claims one gate permit
per fetch, releasing it on every path — success, error, or cancellation — and
forwarding the inner layer's capability ports exactly (bound only when the inner
layer has them). Fetches park on an ``asyncio.Event`` until the test lets them
proceed, so scheduling is deterministic and nothing sleeps.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from screamingface_engine.runner.fair_share import (
    FairShareGate,
    FairShareIOLayer,
    GateSnapshot,
    RunShare,
)


async def _settle(rounds: int = 3) -> None:
    """Let every already-scheduled task step until it parks (grants land within 2)."""
    for _ in range(rounds):
        await asyncio.sleep(0)


def _share(snapshot: GateSnapshot, run: str) -> RunShare:
    return next(entry for entry in snapshot.runs if entry.run == run)


class _CapabilityInner:
    """An inner layer exposing every capability port, with controllable fetches."""

    def __init__(self) -> None:
        self.fetches: list[str] = []
        self.proceed = asyncio.Event()
        self.fail = False

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        if self.fail:
            raise RuntimeError("inner exploded")
        await self.proceed.wait()
        return f"got:{target}"

    async def fetch_ex(self, request: Any) -> str:
        return await self.fetch(request.target, relative=True)

    async def fetch_holdings(self, identity: str | None, collection: str | None) -> str:
        return await self.fetch(f"holdings:{identity}:{collection}", relative=True)

    def processor_routes(self) -> list[str]:
        return ["/model"]  # not I/O: must be forwarded unbounded

    def default_route(self) -> str:
        return "/model"  # a declaration, not I/O: forwarded so fan-out reduce resolves


@pytest.mark.asyncio
async def test_the_layer_binds_and_releases_one_permit_per_fetch() -> None:
    gate = FairShareGate(2)
    inner = _CapabilityInner()
    layer = FairShareIOLayer(inner, gate, "run-a")

    tasks = [
        asyncio.get_running_loop().create_task(layer.fetch(f"t{i}", relative=True))
        for i in range(3)
    ]
    await _settle()
    snapshot = gate.snapshot()
    assert _share(snapshot, "run-a") == RunShare(run="run-a", in_flight=2, waiting=1)

    inner.proceed.set()
    results = await asyncio.gather(*tasks)
    assert results == ["got:t0", "got:t1", "got:t2"]
    assert gate.snapshot().runs == ()  # every permit returned


@pytest.mark.asyncio
async def test_the_layer_releases_the_permit_when_the_fetch_fails() -> None:
    gate = FairShareGate(1)
    inner = _CapabilityInner()
    inner.fail = True
    layer = FairShareIOLayer(inner, gate, "run-a")

    with pytest.raises(RuntimeError, match="inner exploded"):
        await layer.fetch("boom", relative=True)

    assert gate.snapshot().in_flight == 0


@pytest.mark.asyncio
async def test_the_layer_releases_the_permit_when_the_fetch_is_cancelled() -> None:
    gate = FairShareGate(1)
    inner = _CapabilityInner()
    layer = FairShareIOLayer(inner, gate, "run-a")

    task = asyncio.get_running_loop().create_task(layer.fetch("stuck", relative=True))
    await _settle()
    assert gate.snapshot().in_flight == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await _settle()
    assert gate.snapshot().in_flight == 0


def test_the_layer_forwards_exactly_the_inner_capability_ports() -> None:
    full = FairShareIOLayer(_CapabilityInner(), FairShareGate(1), "run-a")
    assert hasattr(full, "fetch_ex")
    assert hasattr(full, "fetch_holdings")
    assert full.processor_routes() == ["/model"]
    assert full.default_route() == "/model"

    class _Bare:
        async def fetch(self, target: str, *, relative: bool) -> str:
            return target

    bare = FairShareIOLayer(_Bare(), FairShareGate(1), "run-a")  # type: ignore[arg-type]
    assert not hasattr(bare, "fetch_ex")
    assert not hasattr(bare, "fetch_holdings")
    assert not hasattr(bare, "processor_routes")
