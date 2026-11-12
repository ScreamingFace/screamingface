"""E5 P2 spec R1, R2, R7, R8 and R14: the Engine's driver starts every Candidate of a Run.

FEATURE: a detached Run (OME-1837). STORY: as a researcher who starts an evaluation and walks
away, every Candidate starts, at most 8 at a time, and none starts twice.

Same databases as `test_run_registry_contract.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from run_driver_support import SETTINGS, DriverRunner, drivers
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    spec,
    start_spec,
)

from screamingface_engine import job_env
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.ports import StoppedBeforeSchedule
from screamingface_engine.runner_queue import RunQueueUnavailable
from screamingface_engine.runs.records import CandidateStart, RunRecord, owner_key
from url4.core.errors import ResolutionError
from url4.streaming.interfaces import JobAlreadyExists, JobRunnerAtCapacity
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for
from url4.streaming.protocol.taxonomy import ErrorInfo
from url4.streaming.trace import parse_traceparent

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")
NAMES = tuple(f"c{n}" for n in range(10))


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def _record(registry: Registry, run_id: str) -> RunRecord:
    record = await registry.store.get(ALICE, run_id)
    assert record is not None
    return record


def _states(record: RunRecord) -> list[str]:
    return [candidate.state for candidate in record.candidates]


async def test_every_candidate_starts_with_at_most_8_in_flight(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec(*NAMES))
    runner = DriverRunner()
    driver = drivers(registry.store, runner, registry.clock)

    assert await driver.drive_once(run.id)
    record = await _record(registry, run.id)
    assert _states(record) == ["scheduled"] * 8 + ["pending"] * 2

    await registry.store.settle(runner.starts[0]["topic"], CandidateOutcome("succeeded"))
    await driver.drive_once(run.id)

    assert _states(await _record(registry, run.id)).count("scheduled") == 8
    assert len(runner.starts) == 9


async def test_a_start_carries_what_the_start_route_gives_a_run(registry: Registry) -> None:
    """R1: the Run's email and client version, a cache policy from `use_cache`, the job deadline,
    the Candidate's trace, its result prefix and `exclusive`."""
    starts = (
        CandidateStart(name="a", url4="openai/gpt-5?q=Hi", answer_seed=7),
        CandidateStart(name="b", url4="openai/gpt-5?q=Hi", use_cache=False, capture=True),
    )
    run, _ = await registry.store.register(ALICE, replace(start_spec("a", "b"), starts=starts))
    runner = DriverRunner()

    await drivers(registry.store, runner, registry.clock).drive_once(run.id)

    first, second = runner.starts
    assert first["identity"] == {"X-User-Email": "alice@example.org"}
    assert first["client_version"] == "1.2.3"
    assert first["deadline_s"] == SETTINGS.job_deadline_s
    assert first["result_prefix"] == f"runs/{run.id}/0"
    assert second["result_prefix"] == f"runs/{run.id}/1"
    assert first["exclusive"] is True
    assert first["answer_seed"] == 7
    assert first["cache"].participate is None
    assert second["cache"].participate is False
    assert second["capture"] is True
    assert parse_traceparent(first["traceparent"]) is not None


async def test_a_run_without_an_owner_email_sends_no_identity(registry: Registry) -> None:
    """R14: local mode has no owner email."""
    run, _ = await registry.store.register(ALICE, start_spec("a", owner_email=None))
    runner = DriverRunner()

    await drivers(registry.store, runner, registry.clock).drive_once(run.id)

    assert runner.starts[0]["identity"] is None


@pytest.mark.parametrize(
    "refusal",
    [JobRunnerAtCapacity(8, 8, retry_after_s=3), RunQueueUnavailable("the queue is down")],
    ids=["at capacity", "queue outage"],
)
async def test_a_refused_start_is_retried_with_its_topic_and_trace(
    registry: Registry, refusal: BaseException
) -> None:
    """R1, D6: nothing was started, so the Candidate stays pending with its topic, and the next
    try sends the same start."""
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    runner = DriverRunner()
    runner.refusals = [refusal]
    driver = drivers(registry.store, runner, registry.clock)

    await driver.drive_once(run.id)
    assert _states(await _record(registry, run.id)) == ["pending"]
    plan = await registry.store.pending_starts(run.id)
    assert plan is not None and plan.pending[0].topic is not None

    await driver.drive_once(run.id)

    (started,) = runner.starts
    assert started["topic"] == plan.pending[0].topic
    assert parse_traceparent(started["traceparent"]) == plan.pending[0].trace_id
    assert _states(await _record(registry, run.id)) == ["scheduled"]


async def test_a_permanent_refusal_settles_the_candidate_failed_with_its_code(
    registry: Registry,
) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    runner = DriverRunner()
    runner.refusals = [ResolutionError("no such model", code="model_not_found", permanent=True)]

    await drivers(registry.store, runner, registry.clock).drive_once(run.id)

    (candidate,) = (await _record(registry, run.id)).candidates
    assert (candidate.state, candidate.error_code) == ("failed", "model_not_found")


async def test_a_topic_the_in_process_runner_holds_counts_as_started(registry: Registry) -> None:
    """R14: that runner refuses a topic while its task runs, which means the start landed."""
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    runner = DriverRunner()
    runner.refusals = [JobAlreadyExists("url4-run:t")]

    await drivers(registry.store, runner, registry.clock).drive_once(run.id)

    assert _states(await _record(registry, run.id)) == ["scheduled"]


async def test_a_start_that_loses_to_a_stop_is_left_to_the_stop(registry: Registry) -> None:
    """R1, R9: `StoppedBeforeSchedule` is not a refusal; the stop settles the Candidate."""
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    runner = DriverRunner()
    runner.refusals = [StoppedBeforeSchedule("t")]

    await drivers(registry.store, runner, registry.clock).drive_once(run.id)

    (candidate,) = (await _record(registry, run.id)).candidates
    assert (candidate.state, candidate.error_code) == ("pending", None)


async def test_a_stopped_run_takes_no_new_start(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    await registry.store.stop(run.id, "canceled")
    runner = DriverRunner()

    assert not await drivers(registry.store, runner, registry.clock).drive_once(run.id)

    assert runner.starts == []


async def test_a_stop_landing_during_a_start_stops_the_start(registry: Registry) -> None:
    """R9: `mark_scheduled` reports the start must be stopped, and the driver stops it."""
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    runner = DriverRunner()

    async def cancel(topic: str) -> None:
        await registry.store.stop(run.id, "canceled")

    runner.during_schedule = cancel

    await drivers(registry.store, runner, registry.clock).drive_once(run.id)

    assert runner.stopped == [runner.starts[0]["topic"]]


async def test_a_candidate_keeps_its_topic_across_an_app_restart(registry: Registry) -> None:
    """R2: the restarted driver sends the same start again; the queue or a worker drops it if the
    first one landed."""
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    first = DriverRunner()
    first.refusals = [RunQueueUnavailable("the publish's result is unknown")]
    await drivers(registry.store, first, registry.clock).drive_once(run.id)
    plan = await registry.store.pending_starts(run.id)
    assert plan is not None
    registry.clock.advance(seconds=SETTINGS.lease_s + 1)

    restarted = registry.restarted(survives_restart=True)
    second = DriverRunner()
    await drivers(restarted, second, registry.clock).drive_once(run.id)

    assert [start["topic"] for start in second.starts] == [plan.pending[0].topic]


async def test_a_candidate_waiting_for_a_slot_keeps_its_full_deadline(registry: Registry) -> None:
    """R8: its 16 h counts from the publish a worker takes, and reconcile never settles it."""
    run, _ = await registry.store.register(ALICE, start_spec(*NAMES))
    runner = DriverRunner()
    driver = drivers(registry.store, runner, registry.clock)
    await driver.drive_once(run.id)
    registry.clock.advance(hours=72)

    assert await registry.store.reconcile() == 8
    await driver.drive_once(run.id)

    assert all(
        "enqueued_at" not in start or start["enqueued_at"] is None for start in runner.starts
    )
    assert _states(await _record(registry, run.id)).count("lost") == 8
    assert _states(await _record(registry, run.id)).count("scheduled") == 2


async def test_a_run_registered_without_starts_is_never_driven(registry: Registry) -> None:
    """R11: a Run a Client from before P2 registered; the tick settles its Candidates."""
    run, _ = await registry.store.register(ALICE, spec("a"))
    runner = DriverRunner()
    driver = drivers(registry.store, runner, registry.clock)

    await driver.tick()

    assert runner.starts == []
    assert _states(await _record(registry, run.id)) == ["stopped"]


async def test_a_run_whose_outcome_never_arrived_settles_from_its_terminal_frame(
    registry: Registry,
) -> None:
    """R7: state and error code from the frame, once its time plus the grace has passed."""
    run, _ = await registry.store.register(ALICE, start_spec("a", "b"))
    runner = DriverRunner()
    driver = drivers(registry.store, runner, registry.clock)
    await driver.drive_once(run.id)
    old, young = (start["topic"] for start in runner.starts)
    ended = registry.clock() + timedelta(seconds=10)
    runner.frames[old] = _terminated(old, ended, "failed", "provider_error")
    runner.frames[young] = _terminated(young, ended + timedelta(seconds=60), "succeeded", None)
    registry.clock.advance(seconds=10 + SETTINGS.outcome_grace_s + 1)

    await driver.drive_once(run.id)

    first, second = (await _record(registry, run.id)).candidates
    assert (first.state, first.error_code, first.cost_usd) == ("failed", "provider_error", None)
    assert second.state == "scheduled"


def _terminated(topic: str, at: object, status: object, code: str | None) -> TerminatedEvent:
    error = None if code is None else ErrorInfo(code=code, message="ended")
    return TerminatedEvent.model_validate(
        {
            "id": "e" * 32,
            "source": source_for(topic),
            "subject": topic,
            "time": at,
            "data": TerminatedData.model_validate({"status": status, "error": error}),
        }
    )


def test_the_driver_settings_come_from_the_engine_settings() -> None:
    from screamingface_engine.config import Settings
    from screamingface_engine.runs.driver import DriverSettings

    settings = DriverSettings.from_settings(
        Settings(run_driver_inflight=4, orphan_grace_s=60, job_deadline_s=3600)
    )

    assert (settings.inflight, settings.orphan_grace_s, settings.job_deadline_s) == (4, 60, 3600)
    assert job_env.DRIVER_SPEC_VERSION == "3"
