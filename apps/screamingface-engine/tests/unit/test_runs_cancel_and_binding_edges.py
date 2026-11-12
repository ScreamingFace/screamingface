"""E5 P1 spec D6, D12: what a cancel stops, and what every `/runs` answer carries (OME-1785).

FEATURE: first-class Runs. STORY: as a researcher, I cancel a Run and every Candidate on a
runner stops, a Candidate that already finished is left alone, and nothing another person runs
is touched.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
)
from test_runs_routes import ALICE, BOB, _Engine, _record

from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import owner_key
from screamingface_engine.runs.sweeps import RunSweeper
from screamingface_engine.runs.wiring import LocalDatabaseInUseError, hold_local_database

pytestmark = pytest.mark.asyncio

_ALICE_KEY = owner_key("alice@example.org")
_PRIVATE = ("private, no-store", "X-User-Email")


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


# --- cancel (spec D12) ---------------------------------------------------------------------


async def test_cancel_stops_a_bound_candidate_not_yet_confirmed(registry: Any) -> None:
    """A start bound its topic and reached the runner, but `mark_scheduled` had not landed."""
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")

    resp = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert resp.status_code == 202
    assert engine.runner.stopped == ["topic-a"]
    # E5 P2 spec R9: its start may have landed, so it is `scheduled` until its stop's outcome.
    assert (await _record(registry, run_id)).candidates[0].state == "scheduled"


async def test_a_sibling_cancel_never_stops_a_candidate_that_succeeded(registry: Any) -> None:
    """A fast Candidate settled before its start confirmed it; a cancel then flagged the Run
    because of a sibling. The confirmation must not read that as this Candidate's cancel."""
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a", "b"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")
    await registry.store.settle("topic-a", CandidateOutcome("succeeded"))
    await registry.store.bind(_ALICE_KEY, run_id, 1, "topic-b")
    await registry.store.mark_scheduled("topic-b")
    assert (await engine.client.delete(f"/runs/{run_id}", headers=ALICE)).status_code == 202

    assert await registry.store.mark_scheduled("topic-a") is True
    assert "topic-a" not in engine.runner.stopped


class _LastOutcomeFirst:
    """A registry whose last live Candidate settles just before the cancel takes the lock."""

    def __init__(self, store: Any, topic: str) -> None:
        self._store = store
        self._topic = topic

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    async def cancel(self, owner: Any, run_id: str) -> Any:
        await self._store.settle(self._topic, CandidateOutcome("succeeded"))
        return await self._store.cancel(owner, run_id)


async def test_a_cancel_the_last_outcome_beat_answers_204(registry: Any) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")
    await registry.store.mark_scheduled("topic-a")
    engine.app.state.run_registry = _LastOutcomeFirst(registry.store, "topic-a")

    resp = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert resp.status_code == 204
    assert engine.runner.stopped == []
    assert (await _record(registry, run_id)).state == "complete"


# --- every answer is private (spec D5, D6) -------------------------------------------------


async def test_a_foreign_ids_404_is_private(registry: Any) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]

    resp = await engine.client.get(f"/runs/{run_id}", headers=BOB)

    assert resp.status_code == 404
    assert (resp.headers["Cache-Control"], resp.headers["Vary"]) == _PRIVATE


async def test_cancel_answers_are_private(registry: Any) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]

    accepted = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)
    unchanged = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert (accepted.status_code, unchanged.status_code) == (202, 204)
    for resp in (accepted, unchanged):
        assert (resp.headers["Cache-Control"], resp.headers["Vary"]) == _PRIVATE


# --- identity before validation (spec D6) --------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [("POST", "/runs", {"case_count": "many"}), ("GET", "/runs?limit=0", None)],
    ids=["malformed-post", "invalid-query"],
)
async def test_a_call_without_identity_is_401_whatever_its_shape(
    registry: Any, method: str, path: str, body: dict[str, Any] | None
) -> None:
    engine = _Engine(registry)

    resp = await engine.client.request(method, path, json=body)

    assert (resp.status_code, resp.json()["code"]) == (401, "identity_required")


# --- one text rule for both stores ---------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [{"benchmark": "gsm\x00k"}, {"client_key": "k\x00"}, {"candidates": ["a\x00b"]}],
    ids=["benchmark", "client-key", "candidate"],
)
async def test_a_nul_in_a_run_field_is_422_on_either_database(
    registry: Any, field: dict[str, Any]
) -> None:
    engine = _Engine(registry)

    assert (await engine.create(**field)).status_code == 422


# --- the documented contract ---------------------------------------------------------------


async def test_the_openapi_documents_the_runs_answers() -> None:
    engine = _Engine(None)
    spec = (await engine.client.get("/openapi.json")).json()

    runs, run = spec["paths"]["/runs"], spec["paths"]["/runs/{run_id}"]
    assert {"200", "201", "401", "409", "422"} <= runs["post"]["responses"].keys()
    assert {"202", "204", "401", "404", "503"} <= run["delete"]["responses"].keys()
    (tag,) = [t for t in spec["tags"] if t["name"] == "Runs"]
    assert "/runs" in tag["description"]


# --- the local database has one owner ------------------------------------------------------


def test_a_second_local_engine_on_one_database_refuses_to_start(tmp_path: Path) -> None:
    """WHY: each local Engine reconciles Candidates bound before it started as `lost`."""
    url = f"sqlite://{tmp_path}/engine.sqlite3"
    first = hold_local_database(url)
    try:
        with pytest.raises(LocalDatabaseInUseError, match="another local Engine"):
            hold_local_database(url)
    finally:
        os.close(first)

    os.close(hold_local_database(url))


# --- the startup sweep ---------------------------------------------------------------------


class _CountingRegistry:
    def __init__(self) -> None:
        self.sweeps = 0

    async def reconcile(self) -> int:
        self.sweeps += 1
        return 0

    async def expiring(self, older_than: datetime) -> list[str]:
        return []

    async def expire(self, run_ids: Sequence[str]) -> int:
        return 0


async def test_the_periodic_loop_can_leave_the_first_sweep_to_startup() -> None:
    counting = _CountingRegistry()
    sweeper = RunSweeper(counting, retention=timedelta(days=1), clock=lambda: datetime.now(UTC))
    task = asyncio.create_task(sweeper.run(interval_s=60, sweep_first=False))
    await asyncio.sleep(0.05)
    task.cancel()

    assert counting.sweeps == 0
