"""The runner's run-visibility log lines: `run claimed` (with the queue wait) and `run finished`.

FEATURE: queue visibility in the logs (OME-1924 part 1, epic OME-1314).
STORY: as on-call reading the runner log during a saturated queue, I can see when each run was
claimed, how long it waited in the queue, and how and when it ended — joined to the App's lines
by `topic=`. The runner never logs the identity (the message body carries the raw email).
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_supervisor_outcomes import _Owner, _Settling, _worker
from test_supervisor_terminal_root_source import _Launcher, _Msg, _Proc, _Publisher

from screamingface_engine import child_protocol
from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream

pytestmark = pytest.mark.asyncio
LOGGER = "screamingface_engine.worker.supervisor"


def _lines(caplog: pytest.LogCaptureFixture, prefix: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(prefix)]


async def test_a_claim_logs_how_long_the_run_waited(caplog: pytest.LogCaptureFixture) -> None:
    worker = _worker(_Publisher(), _Launcher(_Proc(code=0)), InMemoryCandidateOutcomeStream())
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await worker._supervisor.supervise(_Msg("t-wait", queued_for_s=42))  # type: ignore[arg-type]

    (line,) = _lines(caplog, "run claimed ")
    # WHY a range: the fake stamps "42 s ago" at construction and the claim reads the clock.
    assert re.fullmatch(r"run claimed topic=t-wait waited_s=4[23]", line), line


async def test_a_claim_without_a_stamp_logs_a_dash(caplog: pytest.LogCaptureFixture) -> None:
    worker = _worker(_Publisher(), _Launcher(_Proc(code=0)), InMemoryCandidateOutcomeStream())
    msg = _Msg("t-nostamp")
    # No header and no delivery timestamp: the wait is unknown, never an error.
    msg.metadata = SimpleNamespace(num_delivered=1)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await worker._supervisor.supervise(msg)  # type: ignore[arg-type]

    assert _lines(caplog, "run claimed ") == ["run claimed topic=t-nostamp waited_s=-"]


async def test_a_finished_run_logs_its_outcome_and_duration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settled = child_protocol.Settled("succeeded", None, Decimal("0.3"))
    worker = _worker(
        _Publisher(), _Settling(_Proc(code=0), settled), InMemoryCandidateOutcomeStream()
    )
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await worker._supervisor.supervise(_Msg("t-ok"))  # type: ignore[arg-type]

    (line,) = _lines(caplog, "run finished ")
    assert re.fullmatch(r"run finished topic=t-ok outcome=succeeded ran_s=\d+", line), line


async def test_a_claim_settled_elsewhere_logs_outcome_settled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # STORY: a redelivery another worker already owns is acked away without a child; the line
    # still says how this claim ended, so on-call never sees a claim with no end.
    worker = _worker(
        _Publisher(), _Launcher(_Proc(code=0)), InMemoryCandidateOutcomeStream(), control=_Owner()
    )
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await worker._supervisor.supervise(_Msg("t-dup", delivered=2))  # type: ignore[arg-type]

    assert _lines(caplog, "run claimed ") == []  # never claimed here: no child ran
    (line,) = _lines(caplog, "run finished ")
    assert line.startswith("run finished topic=t-dup outcome=settled ran_s=")
