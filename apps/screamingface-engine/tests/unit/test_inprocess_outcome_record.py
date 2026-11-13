"""E5 P2 spec R14 and §4.3: a local run started with a result prefix reports its record too.

FEATURE: a detached Run (OME-1837). STORY: as a researcher on a laptop, a Run I detach locally
reattaches with the same Report as a hosted one.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from test_inprocess_outcomes import _Executor, _published

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import (
    InMemoryCandidateOutcomeStream,
    InMemoryEventStream,
)
from url4.streaming.interfaces import Executor

pytestmark = pytest.mark.asyncio

TOPIC = "t-local-record"
PREFIX = f"runs/run_{'a' * 32}/0"
TRACE = "0af7651916cd43dd8448eb211c80319c"


def _runner(
    outcomes: InMemoryCandidateOutcomeStream, seen: list[Mapping[str, str]]
) -> InProcessJobRunner:
    def factory(env: Mapping[str, str]) -> Executor:
        seen.append(dict(env))
        return _Executor()

    return InProcessJobRunner(InMemoryEventStream(), factory, outcomes=outcomes)


async def test_a_local_run_with_a_result_prefix_reports_its_record() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    seen: list[Mapping[str, str]] = []

    await _runner(outcomes, seen).schedule(
        TOPIC, "q", 10, traceparent=f"00-{TRACE}-b7ad6b7169203331-01", result_prefix=PREFIX
    )
    delivery = await _published(outcomes)

    record = delivery.outcome.record
    assert record is not None
    assert record["trace_id"] == TRACE
    assert record["result"]["size_bytes"] == len(b"ok")
    assert seen[0][job_env.RESULT_PREFIX] == PREFIX


async def test_a_local_run_without_one_reports_no_record() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    seen: list[Mapping[str, str]] = []

    await _runner(outcomes, seen).schedule(TOPIC, "q", 10)
    delivery = await _published(outcomes)

    assert delivery.outcome.record is None
    assert job_env.RESULT_PREFIX not in seen[0]
