"""The unclaimed-run notice carries the queue's waiting and running counts (OME-1924 part 1).

FEATURE: queue visibility in the logs (epic OME-1314).
STORY: as on-call reading `unclaimed run warned`, I see how many runs wait and how many run,
without a broker session; as the waiting user, my notice frame carries `run.queue_waiting`.
INVARIANT: the user-facing TEXT is unchanged (no internals); unknown counts log `-` and add no
attribute, so the pre-existing warner tests and their fakes keep passing untouched.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from test_unclaimed_run_warner import GRACE, T0, _Audience, _Runner

from screamingface_engine.runner_demand import RunnerDemand
from screamingface_engine.unclaimed import UNCLAIMED_MESSAGE, UnclaimedRunWarner
from url4.streaming.protocol import LogEvent

LOGGER = "screamingface_engine.unclaimed"


class _CountingRunner(_Runner):
    """A runner that also answers `queue_snapshot()` like `QueueJobRunner`."""

    def __init__(self, depth: int | None, oldest_age: float | None) -> None:
        super().__init__()
        self.snapshot = (depth, oldest_age)

    def queue_snapshot(self) -> tuple[int | None, float | None]:
        return self.snapshot


def _demand(running: int) -> tuple[RunnerDemand, datetime, float]:
    return (
        RunnerDemand(demand=running, running=running, claimable=0, queued=6, unbound_buckets=0),
        T0,
        1.0,
    )


def _warner(runs: Any, audience: _Audience, demand: Any = None) -> UnclaimedRunWarner:
    return UnclaimedRunWarner(runs, audience, grace_s=GRACE, frame_clock=lambda: T0, demand=demand)


def _warned_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    messages = (r.getMessage() for r in caplog.records)
    return [m for m in messages if m.startswith("unclaimed run warned")]


def _frame(audience: _Audience) -> LogEvent:
    """The one notice frame, narrowed to the LogEvent the warner sends."""
    [(_, frame)] = audience.notices
    assert isinstance(frame, LogEvent)
    return frame


@pytest.mark.asyncio
async def test_the_notice_log_line_names_waiting_and_running(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner, audience = _CountingRunner(6, 310.0), _Audience({"t"})
    runner.ages["t"] = 301.7
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await _warner(runner, audience, demand=lambda: _demand(8)).sweep()

    assert _warned_lines(caplog) == ["unclaimed run warned topic=t wait_s=302 waiting=6 running=8"]
    frame = _frame(audience)
    assert frame.data.body == UNCLAIMED_MESSAGE
    assert frame.data.attributes == {"run.wait_s": 301, "run.queue_waiting": 6}


@pytest.mark.asyncio
async def test_unknown_counts_log_dashes_and_add_no_attribute(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The pre-existing `_Runner` has no `queue_snapshot`, and no demand reader is wired.
    runner, audience = _Runner(), _Audience({"t"})
    runner.ages["t"] = 301.7
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await _warner(runner, audience).sweep()

    assert _warned_lines(caplog) == ["unclaimed run warned topic=t wait_s=302 waiting=- running=-"]
    frame = _frame(audience)
    assert frame.data.attributes == {"run.wait_s": 301}


@pytest.mark.asyncio
async def test_a_stale_demand_sample_logs_running_dash(caplog: pytest.LogCaptureFixture) -> None:
    # `RunnerDemandSampler.fresh()` answers None past `stale_s`: never a stale or made-up 0.
    runner, audience = _CountingRunner(6, 310.0), _Audience({"t"})
    runner.ages["t"] = 301.7
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await _warner(runner, audience, demand=lambda: None).sweep()

    assert _warned_lines(caplog) == ["unclaimed run warned topic=t wait_s=302 waiting=6 running=-"]


@pytest.mark.asyncio
async def test_a_depth_not_yet_read_adds_no_attribute(caplog: pytest.LogCaptureFixture) -> None:
    # `queue_snapshot()` returns (None, None) before the first refresh.
    runner, audience = _CountingRunner(None, None), _Audience({"t"})
    runner.ages["t"] = 301.7
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await _warner(runner, audience, demand=lambda: _demand(8)).sweep()

    assert _warned_lines(caplog) == ["unclaimed run warned topic=t wait_s=302 waiting=- running=8"]
    frame = _frame(audience)
    assert frame.data.attributes == {"run.wait_s": 301}


def test_the_message_text_is_unchanged() -> None:
    assert UNCLAIMED_MESSAGE == (
        "the runner service is at capacity; your run is queued and has not started yet"
    )
    assert datetime.now(UTC) > T0  # the fixture clock is in the past, as every frame test assumes
