"""E5 P1 spec D12: a cancel keeps a Run's queued Candidate from running even when the App
cannot know it was queued, and concurrent cancels answer only their own failures (OME-1785).

FEATURE: first-class Runs. STORY: as a researcher, I cancel a Run and none of its Candidates
runs afterwards, even if the Engine restarted or my cancel beat the Candidate's start.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from _fakes import RecordingJobRunner
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
)
from test_queue_runner_cancel import (
    _FakeControl,
    _FakeMsg,
    _FakePublisher,
    _runner,
    _supervisor,
)
from test_runs_routes import ALICE, _Engine

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.runner_queue import encode_message
from screamingface_engine.runs.records import owner_key
from url4.streaming.protocol import TerminatedEvent

pytestmark = pytest.mark.asyncio

_ALICE_KEY = owner_key("alice@example.org")


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


# --- the queue runner ----------------------------------------------------------------------


async def test_a_bound_stop_after_a_restart_keeps_the_queued_run_from_running() -> None:
    """WHY: a restarted App has no record of what the old one queued."""
    publisher = _FakePublisher()
    await _runner(publisher, _FakeControl(reply=False)).schedule("t", "'hi'", 60)
    restarted = _runner(publisher, _FakeControl(reply=False))

    await restarted.stop_bound("t")

    (frame,) = publisher.published
    assert isinstance(frame, TerminatedEvent) and frame.data.status == "stopped"
    msg = _FakeMsg(encode_message("t", "'hi'", 60))
    await _supervisor(publisher).supervise(msg)  # never spawns
    assert msg.acked


async def test_a_bound_stop_before_the_publish_keeps_the_run_from_running() -> None:
    publisher = _FakePublisher()
    runner = _runner(publisher, _FakeControl(reply=False))

    await runner.stop_bound("t")
    await runner.schedule("t", "'hi'", 60)

    msg = _FakeMsg(encode_message("t", "'hi'", 60))
    await _supervisor(publisher).supervise(msg)  # never spawns
    assert msg.acked
    assert len(publisher.published) == 1


# --- the Runs cancel -----------------------------------------------------------------------


class _BoundStops(RecordingJobRunner):
    def __init__(self) -> None:
        super().__init__()
        self.bound: list[str] = []

    async def stop_bound(self, topic: str) -> None:
        self.bound.append(topic)


async def test_a_cancel_stops_its_candidates_as_bound_topics(registry: Registry) -> None:
    runner = _BoundStops()
    engine = _Engine(registry, runner=runner)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")

    assert (await engine.client.delete(f"/runs/{run_id}", headers=ALICE)).status_code == 202
    assert runner.bound == ["topic-a"]


class _FailsAfterTheOtherStop(RecordingJobRunner):
    """The first stop fails, but only once a concurrent cancel's stop has cleared the debt."""

    def __init__(self, store: Any, run_id: str) -> None:
        super().__init__()
        self._store = store
        self._run_id = run_id
        self.attempts = 0

    async def stop(self, topic: str) -> None:
        self.attempts += 1
        if self.attempts == 1:
            while topic in await self._store.owed_stops(_ALICE_KEY, self._run_id):
                await asyncio.sleep(0.01)
            raise QueueReadError(topic)
        await super().stop(topic)


async def test_a_stop_another_cancel_completed_is_not_a_503(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")
    runner = _FailsAfterTheOtherStop(registry.store, run_id)
    engine.app.state.job_runner = runner

    first, second = await asyncio.wait_for(
        asyncio.gather(
            engine.client.delete(f"/runs/{run_id}", headers=ALICE),
            engine.client.delete(f"/runs/{run_id}", headers=ALICE),
        ),
        timeout=10,
    )

    assert runner.attempts == 2
    assert 503 not in (first.status_code, second.status_code)
