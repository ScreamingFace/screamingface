"""E5 P2 spec R5 and §4.3: a driver-started run's child folds its record from the frames it
published, and reports it with its outcome.

FEATURE: a detached Run (OME-1837).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runner import main
from screamingface_engine.runner.summary import RunSummary
from url4.streaming.codec import decode
from url4.streaming.protocol import OutboundFrame

pytestmark = pytest.mark.asyncio

RUN = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "candidate_runs" / "success.json").read_text()
)
TOPIC = RUN["frames"][0]["subject"]
TRACEPARENT = RUN["frames"][0]["traceparent"]
PREFIX = f"runs/run_{'a' * 32}/0"


class _Publisher:
    def __init__(self, *, refuse: str | None = None) -> None:
        self.frames: list[OutboundFrame] = []
        self._refuse = refuse

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        if event.type == self._refuse:
            raise OSError("the broker refused it")
        self.frames.append(event)

    async def flush(self) -> None:
        return None


def _executor() -> Any:
    return SimpleNamespace(
        last_summary=lambda: RunSummary(outcome="succeeded", trace_id=None, cost_usd=Decimal("1"))
    )


async def _replay(publisher: Any, *args: Any, **kwargs: Any) -> None:
    for frame in RUN["frames"]:
        try:
            await publisher.publish(TOPIC, decode(json.dumps(frame).encode()))
        except OSError:
            continue


def _params(prefix: str | None) -> main.RunnerParams:
    return main.RunnerParams(
        topic=TOPIC,
        url4=RUN["url4"],
        nats_url="nats://unused",
        deadline_s=1.0,
        result_prefix=prefix,
    )


async def _settle(publisher: _Publisher, prefix: str | None) -> CandidateOutcome:
    """The child's settlement of the recorded run."""
    return await main._run_and_log(_executor(), publisher, _params(prefix), TRACEPARENT)  # type: ignore[arg-type]  # noqa: SLF001


@pytest.fixture(autouse=True)
def _scripted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_log_terminal", lambda *a, **k: None)
    monkeypatch.setattr(main, "run", _replay)


async def test_a_driver_started_runs_outcome_carries_its_record() -> None:
    outcome = await _settle(_Publisher(), PREFIX)

    assert outcome.record == RUN["record"]
    assert main._settled(outcome).record == RUN["record"]  # noqa: SLF001


async def test_any_other_run_reports_no_record() -> None:
    """INVARIANT (plan E2): nothing asks such a run for a record, so its outcome is P1's."""
    outcome = await _settle(_Publisher(), None)

    assert outcome.record is None


async def test_a_frame_that_never_landed_is_not_in_the_record() -> None:
    """The record states what a follower could have seen: a refused result is no result."""
    publisher = _Publisher(refuse="ai.url4.result")

    outcome = await _settle(publisher, PREFIX)

    assert outcome.record is not None
    assert "result" not in outcome.record


def test_the_result_prefix_is_read_from_the_runs_env() -> None:
    env = {job_env.TOPIC: TOPIC, job_env.EXPRESSION: RUN["url4"], job_env.RESULT_PREFIX: PREFIX}

    assert main.params_from_env(env).result_prefix == PREFIX
    assert (
        main.params_from_env({job_env.TOPIC: TOPIC, job_env.EXPRESSION: "x"}).result_prefix is None
    )
