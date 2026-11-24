"""E5 P2 spec R14: the reaper never stops a topic the Engine's driver started.

FEATURE: a detached Run (OME-1837). STORY: as a researcher, a raw WebSocket that attaches to one
of my detached Run's Candidates and leaves does not get that Candidate stopped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    spec,
    start_spec,
)

from screamingface_engine.reaper import RunReaper
from screamingface_engine.runs.records import owner_key

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")


class _Runner:
    def __init__(self) -> None:
        self.stopped: list[str] = []

    async def exists(self, topic: str) -> bool:
        return True

    async def stop(self, topic: str) -> None:
        self.stopped.append(topic)


class _Nobody:
    async def has_subscriber(self, topic: str) -> bool:
        return False


class _Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


async def _reaped(driven: set[str], topic: str) -> list[str]:
    runner, clock = _Runner(), _Clock()

    async def is_driven(candidate: str) -> bool:
        return candidate in driven

    reaper = RunReaper(runner, _Nobody(), grace_s=120, clock=clock, driven=is_driven)
    reaper.audience_left(topic)
    clock.now = 121
    await reaper.sweep()
    return runner.stopped


async def test_a_driver_started_topic_with_no_follower_is_not_reaped() -> None:
    assert await _reaped({"t-driven"}, "t-driven") == []


async def test_a_raw_topic_with_no_follower_still_is() -> None:
    assert await _reaped({"t-driven"}, "t-raw") == ["t-raw"]


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def test_the_registry_names_the_topics_of_runs_that_have_starts(registry: Registry) -> None:
    driven, _ = await registry.store.register(ALICE, start_spec("a", client_key="k1"))
    legacy, _ = await registry.store.register(ALICE, spec("a", client_key="k2"))
    await registry.store.bind(ALICE, driven.id, 0, "t-driven")
    await registry.store.bind(ALICE, legacy.id, 0, "t-legacy")

    assert await registry.store.has_start("t-driven")
    assert not await registry.store.has_start("t-legacy")
    assert not await registry.store.has_start("t-raw")
