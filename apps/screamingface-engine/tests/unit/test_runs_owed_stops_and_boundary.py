"""E5 P1 spec D2, D6, D12: a cancel stops exactly the topics it owes, and the `/runs` boundary
answers Runs off, identity and validation before and as Problems (OME-1785).

FEATURE: first-class Runs. STORY: as a researcher, a cancel I retry stops what the first try
could not, and never touches a Candidate that already ended on its own.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
)
from test_runs_routes import ALICE, _CanceledWhileScheduling, _Engine

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.config import Settings
from screamingface_engine.runs import wiring
from screamingface_engine.runs.records import owner_key
from screamingface_engine.runs.wiring import LocalDatabaseInUseError, hold_local_database

pytestmark = pytest.mark.asyncio

_ALICE_KEY = owner_key("alice@example.org")
_PRIVATE = ("private, no-store", "X-User-Email")


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


def _private(resp: object) -> tuple[str, str]:
    headers = resp.headers  # type: ignore[attr-defined]
    return headers["Cache-Control"], headers["Vary"]


class _FailsOnceFor(RecordingJobRunner):
    """Stops that fail once for one topic, recording every attempt."""

    def __init__(self, failing: str) -> None:
        super().__init__()
        self.failing: str | None = failing
        self.attempts: list[str] = []

    async def stop(self, topic: str) -> None:
        self.attempts.append(topic)
        if topic == self.failing:
            self.failing = None
            raise QueueReadError(topic)
        await super().stop(topic)


# --- owed stops (spec D12) -----------------------------------------------------------------


async def test_a_mixed_runs_failed_pending_stop_is_retried(registry: Registry) -> None:
    runner = _FailsOnceFor("topic-p")
    engine = _Engine(registry, runner=runner)
    run_id = (await engine.create(candidates=["p", "s"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-p")
    await registry.store.bind(_ALICE_KEY, run_id, 1, "topic-s")
    await registry.store.mark_scheduled("topic-s")

    failed = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)
    retried = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert failed.status_code == 503
    assert retried.status_code == 202
    # The failed pending stop is retried; the sibling whose stop succeeded is not stopped again.
    assert runner.attempts.count("topic-p") == 2
    assert runner.attempts.count("topic-s") == 1
    assert "topic-p" in runner.stopped


async def test_a_candidate_that_stopped_on_its_own_is_never_stopped(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")
    await registry.store.mark_scheduled("topic-a")
    await registry.store.settle("topic-a", CandidateOutcome("stopped"))

    first = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)
    again = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert (first.status_code, again.status_code) == (204, 204)
    assert engine.runner.stopped == []


async def test_a_repeated_successful_cancel_stops_nothing_again(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")
    await registry.store.mark_scheduled("topic-a")
    assert (await engine.client.delete(f"/runs/{run_id}", headers=ALICE)).status_code == 202
    await registry.store.settle("topic-a", CandidateOutcome("stopped"))

    again = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert again.status_code == 204
    assert engine.runner.stopped == ["topic-a"]


async def test_a_stream_delete_that_errors_is_a_private_retryable_503(
    registry: Registry,
) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")
    await registry.store.mark_scheduled("topic-a")

    async def _refuse(topic: str) -> None:
        raise RuntimeError("the broker refused")

    engine.app.state.stream.delete_stream = _refuse

    resp = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "5"
    assert _private(resp) == _PRIVATE
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_a_start_that_loses_to_a_cancel_answers_a_private_409(registry: Registry) -> None:
    runner = _CanceledWhileScheduling(registry)
    engine = _Engine(registry, runner=runner)
    runner.run_id = (await engine.create()).json()["id"]

    resp = await engine.start("topic-a", runner.run_id)

    assert (resp.status_code, resp.json()["code"]) == (409, "run_canceled")
    assert _private(resp) == _PRIVATE


# --- the `/runs` boundary (spec D2, D6) ----------------------------------------------------


async def test_an_unparseable_body_without_identity_is_401(registry: Registry) -> None:
    engine = _Engine(registry)

    resp = await engine.client.post(
        "/runs", content=b"{", headers={"Content-Type": "application/json"}
    )

    assert (resp.status_code, resp.json()["code"]) == (401, "identity_required")


async def test_an_unparseable_body_while_runs_are_off_is_a_plain_404() -> None:
    engine = _Engine(None)

    resp = await engine.client.post(
        "/runs", content=b"{", headers={"Content-Type": "application/json", **ALICE}
    )

    assert resp.status_code == 404
    assert resp.json().get("code") != "run_not_found"


async def test_an_invalid_field_is_a_private_422_problem(registry: Registry) -> None:
    engine = _Engine(registry)

    resp = await engine.create(case_count="many")

    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert _private(resp) == _PRIVATE
    assert "many" not in resp.text


async def test_the_openapi_declares_the_runs_422_as_a_problem() -> None:
    spec = (await _Engine(None).client.get("/openapi.json")).json()

    post_422 = spec["paths"]["/runs"]["post"]["responses"]["422"]
    (media,) = post_422["content"]
    assert media == "application/problem+json"
    assert post_422["content"][media]["schema"]["$ref"].endswith("/Problem")
    assert post_422["headers"].keys() == {"Cache-Control", "Vary"}
    start_503 = spec["paths"]["/"]["get"]["responses"]["503"]
    assert "Retry-After" in start_503["headers"]


# --- the Runs lifecycle --------------------------------------------------------------------


async def test_a_later_startup_hook_that_fails_releases_runs(tmp_path: Path) -> None:
    """WHY: a failed startup runs no shutdown hook, and a local Engine inside the Client's
    process lives on to start again."""
    app = FastAPI()
    url = f"sqlite://{tmp_path}/engine.sqlite3"
    wiring.install_runs(
        app, Settings(database_url=url), InMemoryCandidateOutcomeStream(), local=True
    )

    async def _fails() -> None:
        raise RuntimeError("a later hook failed")

    app.router.on_startup.append(_fails)

    with pytest.raises(RuntimeError, match="later hook"):
        async with app.router.lifespan_context(app):
            pass

    assert app.state.run_registry is None
    assert (app.state.outcome_writer_task, app.state.run_sweep_task) == (None, None)
    os.close(hold_local_database(url))


def test_a_url_query_finds_the_same_lock(tmp_path: Path) -> None:
    url = f"sqlite://{tmp_path}/engine.sqlite3"
    held = hold_local_database(url)
    try:
        with pytest.raises(LocalDatabaseInUseError):
            hold_local_database(f"{url}?journal_mode=WAL")
    finally:
        os.close(held)
