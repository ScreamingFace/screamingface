"""A run leaves greppable evidence in the engine's process log (OME-940).

Rung 4a of the correlation ladder. A run's whole diagnostic record — the NATS frame stream —
is deleted 60 s after it ends (`DEFAULT_STREAM_GRACE_S`), so a failed deployed run is not
reconstructable after ~2 minutes. These lines put the essentials where `kubectl logs` keeps
them for the pod-log window.

Two defects are pinned here, both of which made the previous behaviour useless for exactly the
runs that need it:

- **The rich line was success-only.** `runner/main.py::_log_terminal` returned early unless the
  outcome was `succeeded`, so a FAILED run's line carried no trace id — inverted from the point.
- **In local mode no such line existed at all.** `InProcessJobRunner` calls `lifecycle_run`
  directly and never reaches the Job entrypoint that logs it.

And the case a green ladder would still hide: a run whose caller sent NO inbound traceparent
still has a trace id (url4 mints one), and it must reach the log too.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

import pytest

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.interfaces import Completed, Executor, TraceContext
from url4.streaming.protocol import ResultData
from url4.streaming.protocol.signals import CostUsageData
from url4.streaming.protocol.taxonomy import CostBreakdown, TokenUsage

pytestmark = pytest.mark.asyncio

TOPIC = "run-evidence-topic"
INBOUND_TRACE = "4" * 32
INBOUND = f"00-{INBOUND_TRACE}-{'1' * 16}-01"


def _subtree() -> CostUsageData:
    """The exact-cost shape `Completed` requires — mirrors `test_inprocess_runner._subtree`."""
    return CostUsageData(
        scope="self",
        provider="test",
        model="test-model",
        pricing_version="v0",
        usage=TokenUsage(input_tokens=0, output_tokens=0),
        cost=CostBreakdown(total_usd=Decimal("0")),
    )


class _Executor(Executor):
    """A minimal Executor that completes, or fails, and remembers the trace it was handed."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.trace: TraceContext | None = None

    async def execute(  # type: ignore[override]
        self, url4: str, *, trace: TraceContext | None = None
    ):
        self.trace = trace
        if self._fail:
            raise RuntimeError("the provider refused")
        yield Completed(result=ResultData(body="ok"), subtree_cost=_subtree())


async def _run_once(caplog, *, fail: bool = False, traceparent: str | None = INBOUND) -> str:
    """Drive one in-process run to completion and return everything it logged."""
    executor = _Executor(fail=fail)
    runner = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda _env: executor,
    )
    with caplog.at_level(logging.INFO, logger="screamingface_engine"):
        await runner.schedule(TOPIC, "gpt(hi)", 60, traceparent=traceparent)
        # The run is a task; let it finish and let the done-callback fire.
        for _ in range(200):
            await asyncio.sleep(0)
            if runner.active_count() == 0:
                break
    return "\n".join(record.getMessage() for record in caplog.records)


# --- the identity line ---------------------------------------------------------------------


async def test_a_scheduled_run_logs_its_identity(caplog) -> None:
    """topic <-> trace_id <-> job name, recorded nowhere before this."""
    text = await _run_once(caplog)

    assert "run scheduled" in text, "no identity line at schedule"
    assert TOPIC in text
    assert INBOUND_TRACE in text


async def test_a_run_without_an_inbound_traceparent_gets_one_at_the_edge(caplog) -> None:
    """The control plane MINTS when the caller sent none, rather than deferring to url4.

    `lifecycle.run` would mint one itself, but internally and after the adapter has returned —
    leaving the control plane unable to name the run it just scheduled, and leaving
    `job_env.TRACEPARENT` unset so the runner's whole log context has no trace id either.
    Minting at the edge is also what W3C describes: a service with no inbound trace context
    starts the trace where the request arrives.

    So there is never a `pending`: the id is known from the first line onward.
    """
    text = await _run_once(caplog, traceparent=None)

    scheduled = [ln for ln in text.splitlines() if "run scheduled" in ln]
    assert scheduled, "no identity line at schedule"
    trace_field = next(f for f in scheduled[0].split() if f.startswith("trace_id="))
    minted = trace_field.removeprefix("trace_id=")
    assert len(minted) == 32 and set(minted) <= set("0123456789abcdef"), scheduled[0]
    assert minted != "0" * 32, "an all-zero trace id parses everywhere and joins nothing"


# --- the terminal line ---------------------------------------------------------------------


async def test_a_terminated_run_leaves_a_control_plane_evidence_line(caplog) -> None:
    text = await _run_once(caplog)

    assert "run terminated" in text, "no terminal evidence line"
    assert INBOUND_TRACE in text


async def test_a_FAILED_run_leaves_the_evidence_line_too(caplog) -> None:
    """THE defect: the rich line used to be success-only.

    `_log_terminal` returned early unless the outcome was `succeeded`, so the run whose evidence
    is actually needed — the failed one — carried no trace id anywhere.
    """
    text = await _run_once(caplog, fail=True)

    terminal = [ln for ln in text.splitlines() if "run terminated" in ln]
    assert terminal, "a failed run left no evidence line — the exact defect OME-940 fixes"
    assert INBOUND_TRACE in terminal[0], terminal[0]
    assert "outcome=failed" in terminal[0], terminal[0]


async def test_a_failed_run_names_the_error(caplog) -> None:
    """`kubectl logs` is the whole record after 60 s; an outcome with no reason is half of one."""
    text = await _run_once(caplog, fail=True)

    terminal = next(ln for ln in text.splitlines() if "run terminated" in ln)
    assert "error=" in terminal, terminal


async def test_the_terminal_line_carries_the_minted_id_when_none_was_inbound(caplog) -> None:
    """The case a green ladder would still hide.

    The e2e client always originates a traceparent, so rung 4a can pass while every deployed
    run that arrives without one stays anonymous. url4 mints an id for those; the terminal line
    must carry the REAL id, not `pending` and not nothing.
    """
    text = await _run_once(caplog, traceparent=None)

    scheduled = next(ln for ln in text.splitlines() if "run scheduled" in ln)
    terminal = next(ln for ln in text.splitlines() if "run terminated" in ln)
    at_schedule = next(f for f in scheduled.split() if f.startswith("trace_id="))
    at_end = next(f for f in terminal.split() if f.startswith("trace_id="))

    assert at_end == at_schedule, (
        "the two evidence lines name different traces for one run, so neither can be trusted "
        f"to find the other: {at_schedule} vs {at_end}"
    )
    minted = at_end.removeprefix("trace_id=")
    assert len(minted) == 32 and minted != "none", terminal


# --- what must NOT change --------------------------------------------------------------------


async def test_the_raw_topic_is_logged_like_every_other_line(caplog) -> None:
    """Deliberate, and contrary to the issue's "digest only" instruction — see the ledger.

    The topic is the SUBJECT of a capability, not the capability: `auth/jwt.py` signs
    `{"sub": topic}` and every route reads it out of already-verified claims, so knowing a
    topic grants nothing. Meanwhile `logs.RunContextFilter` puts `topic=` on every engine log
    line already. Digesting it here alone would make these the only two lines that cannot be
    grepped against the rest of the run's output.
    """
    text = await _run_once(caplog)

    assert f"topic={TOPIC}" in text
