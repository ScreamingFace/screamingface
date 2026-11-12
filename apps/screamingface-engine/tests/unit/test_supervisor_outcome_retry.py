"""E5 P2 spec R6 in the worker: only a driver-started run's refused outcome is retried.

FEATURE: a detached Run (OME-1837).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, cast

import pytest
from test_supervisor_outcomes import _Settling
from test_supervisor_terminal_root_source import _Msg, _Proc, _Publisher, _worker

from screamingface_engine import child_protocol, job_env
from screamingface_engine.candidate_outcomes import CandidateOutcome, OutcomeNotAccepted
from screamingface_engine.worker.outcome_retry import OutcomeRetries

pytestmark = pytest.mark.asyncio


class _Refusing:
    """An outcome stream that cannot take the first ``refusals`` publishes."""

    def __init__(self, refusals: int) -> None:
        self.refusals = refusals
        self.published: list[tuple[str, CandidateOutcome]] = []

    async def publish(self, topic: str, outcome: CandidateOutcome) -> None:
        if self.refusals:
            self.refusals -= 1
            raise OutcomeNotAccepted("the stream is full")
        self.published.append((topic, outcome))


def _driver_started(msg: _Msg) -> _Msg:
    body = json.loads(msg.data)
    body.update({job_env.EXCLUSIVE: "1", job_env.SPEC_VERSION: "3"})
    msg.data = json.dumps(body).encode()
    return msg


def _worker_with(stream: _Refusing) -> Any:
    settled = child_protocol.Settled("succeeded", None, Decimal("0.3"))
    worker = _worker(_Publisher(), _Settling(_Proc(code=0), settled))
    retries = OutcomeRetries(stream, first_delay_s=0.01, max_delay_s=0.02)
    worker._supervisor._outcomes = cast(Any, stream)  # noqa: SLF001 - the seam under test
    worker._supervisor._outcome_retries = retries  # noqa: SLF001
    return worker, retries


async def test_a_driver_started_runs_refused_outcome_is_retried_until_it_lands() -> None:
    stream = _Refusing(2)
    worker, retries = _worker_with(stream)
    msg = _driver_started(_Msg("t-driver"))

    await worker._supervisor.supervise(msg)
    await retries.drain(grace_s=5)

    assert msg.acked
    assert [(topic, outcome.status) for topic, outcome in stream.published] == [
        ("t-driver", "succeeded")
    ]


async def test_any_other_runs_refused_outcome_is_dropped_as_today() -> None:
    stream = _Refusing(1)
    worker, retries = _worker_with(stream)

    await worker._supervisor.supervise(_Msg("t-raw"))
    await retries.drain(grace_s=5)

    assert stream.published == []
    assert retries.pending == 0
