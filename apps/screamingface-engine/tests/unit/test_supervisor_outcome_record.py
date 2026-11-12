"""E5 P2 spec R5 and §4.3: the worker relays the record its child reported on the outcome.

FEATURE: a detached Run (OME-1837).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from test_supervisor_outcomes import _published, _Settling, _worker
from test_supervisor_terminal_root_source import _Msg, _Proc, _Publisher

from screamingface_engine import child_protocol
from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream

pytestmark = pytest.mark.asyncio

RECORD = {"trace_id": "a" * 32, "cache_hits": 1, "client_version": "1.4.0"}


async def test_the_childs_record_rides_its_outcome() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    settled = child_protocol.Settled("succeeded", None, Decimal("0.3"), record=RECORD)
    worker = _worker(_Publisher(), _Settling(_Proc(code=0), settled), outcomes)

    await worker._supervisor.supervise(_Msg("t-ok"))  # type: ignore[arg-type]

    ((topic, outcome),) = await _published(outcomes)
    assert (topic, outcome.status, outcome.record) == ("t-ok", "succeeded", RECORD)


async def test_a_child_that_reported_no_record_publishes_none() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    settled = child_protocol.Settled("succeeded", None, Decimal("0.3"))
    worker = _worker(_Publisher(), _Settling(_Proc(code=0), settled), outcomes)

    await worker._supervisor.supervise(_Msg("t-ok"))  # type: ignore[arg-type]

    ((_, outcome),) = await _published(outcomes)
    assert outcome.record is None
