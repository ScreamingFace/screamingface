"""The runner's process-level summary and its log rendering (OME-1069).

The run's telemetry lives in the CloudEvents stream; the summary is the small, exact record
the run mode logs to its own process output so an operator reading a Job's logs gets the
one-stop answer. Exact-only, like the rest of the run's accounting: a failed run states no
cost and no cache counts, because neither is exact.
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal

import pytest
from _fakes import MockExecutor

from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.runner.main import (
    RunnerParams,
    _log_boot,
    _log_terminal,
    _nats_host,
)
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from screamingface_engine.runner.summary import RunSummary
from url4.core.errors import ParseError
from url4.io.static import StaticIOLayer
from url4.streaming.interfaces import TraceContext

TRACE = TraceContext(trace_id="ab" * 16, root_span_id="cd" * 8)
_MAIN_LOGGER = "screamingface_engine.runner.main"


class _SummarizingExecutor:
    """A fake executor that records a summary, for `_log_terminal` tests."""

    def __init__(self, summary: RunSummary | None) -> None:
        self._summary = summary

    def last_summary(self) -> RunSummary | None:
        return self._summary


# --- Url4Executor.last_summary -------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_summary_is_none_before_any_execute() -> None:
    executor = Url4Executor(StaticIOLayer())

    assert executor.last_summary() is None


@pytest.mark.asyncio
async def test_a_completed_run_records_an_exact_summary() -> None:
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    executor = Url4Executor(io)

    async for _ in executor.execute("https://a!go", trace=TRACE):
        pass

    summary = executor.last_summary()
    assert summary is not None
    assert summary.outcome == "succeeded"
    # The trace id the stream frames carry — recorded from the TraceContext the executor
    # received, never re-derived.
    assert summary.trace_id == TRACE.trace_id
    # A static run makes no model call: the subtree is unpriced, never a false zero.
    assert summary.pricing_version == "unpriced"
    assert summary.cost_usd == Decimal("0")
    assert summary.cache_attributes == {
        "cache.hits": 0,
        "cache.misses": 0,
        "cache.bypasses": 0,
    }
    assert summary.error_code is None
    assert summary.error_type is None
    assert summary.duration_s is not None


@pytest.mark.asyncio
async def test_a_failed_run_records_failed_without_cost_or_cache() -> None:
    executor = Url4Executor(StaticIOLayer())

    with pytest.raises(ParseError):
        async for _ in executor.execute("((("):
            pass

    summary = executor.last_summary()
    assert summary is not None
    assert summary.outcome == "failed"
    assert summary.error_code == "malformed_source"
    assert summary.error_type == "ParseError"
    # Exact-only: a failed run's cost and cache figures are partial and must not read as exact.
    assert summary.cost_usd is None
    assert summary.pricing_version is None
    assert summary.cache_attributes is None


@pytest.mark.asyncio
async def test_a_cancelled_run_records_stopped() -> None:
    gate = asyncio.Event()

    async def gated(_context: str, _intent: str) -> str:
        await gate.wait()
        return "GATED"

    io = StaticIOLayer(fetch_map={"https://fast": "FAST"}, routes={"/gated": gated})
    executor = Url4Executor(io)
    gen = executor.execute("(f=https://fast, g=/gated()!go)!'$f $g'", trace=TRACE)

    # The run starts and blocks on the gate; the first frame is already out.
    await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    pending = asyncio.ensure_future(gen.__anext__())
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    summary = executor.last_summary()
    assert summary is not None
    assert summary.outcome == "stopped"
    assert summary.trace_id == TRACE.trace_id
    assert summary.cost_usd is None


# --- OperationCapturingExecutor.last_summary ------------------------------------------------


@pytest.mark.asyncio
async def test_the_wrapper_delegates_last_summary_to_the_inner_executor() -> None:
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    wrapper = OperationCapturingExecutor(Url4Executor(io))

    async for _ in wrapper.execute("https://a!go", trace=TRACE):
        pass

    summary = wrapper.last_summary()
    assert summary is not None
    assert summary.outcome == "succeeded"
    assert summary.trace_id == TRACE.trace_id


def test_the_wrapper_answers_none_for_an_inner_executor_without_a_summary() -> None:
    # A test double that does not record a summary must not crash the accessor.
    wrapper = OperationCapturingExecutor(MockExecutor())

    assert wrapper.last_summary() is None


# --- _log_terminal / _log_boot rendering ----------------------------------------------------


def test_log_terminal_renders_the_finished_and_summary_lines(
    caplog: pytest.LogCaptureFixture,
) -> None:
    summary = RunSummary(
        outcome="succeeded",
        trace_id="ab" * 16,
        duration_s=1.5,
        cost_usd=Decimal("0.0042"),
        pricing_version="2026-07-01",
        cache_attributes={"cache.hits": 3, "cache.misses": 1, "cache.bypasses": 0},
        dropped_logs=0,
        high_water=5,
    )
    with caplog.at_level(logging.INFO, logger=_MAIN_LOGGER):
        _log_terminal(_SummarizingExecutor(summary), "cap-topic", time.monotonic() - 1.5)

    messages = [record.message for record in caplog.records]
    assert any(
        "run finished topic=cap-topic outcome=succeeded duration_s=" in message
        for message in messages
    )
    assert any(
        "run summary topic=cap-topic trace_id=" in message
        and "cost_usd=0.0042" in message
        and "cache.hits=3" in message
        and "dropped_logs=0" in message
        and "high_water=5" in message
        for message in messages
    )


def test_log_terminal_omits_cost_and_cache_for_a_failed_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    summary = RunSummary(
        outcome="failed",
        trace_id=None,
        error_code="provider_refusal",
        error_type="RunnerRequestError",
        duration_s=2.0,
    )
    with caplog.at_level(logging.INFO, logger=_MAIN_LOGGER):
        _log_terminal(_SummarizingExecutor(summary), "cap-topic", time.monotonic() - 2.0)

    messages = [record.message for record in caplog.records]
    assert any(
        "run finished topic=cap-topic outcome=failed code=provider_refusal "
        "type=RunnerRequestError" in message
        for message in messages
    )
    assert not any("run summary" in message for message in messages)


def test_log_terminal_warns_when_no_summary_exists(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_MAIN_LOGGER):
        _log_terminal(_SummarizingExecutor(None), "cap-topic", time.monotonic())

    assert any(
        "run ended without an executor summary topic=cap-topic" in record.message
        for record in caplog.records
    )


def test_log_boot_sanitizes_the_nats_url_and_never_logs_the_expression(
    caplog: pytest.LogCaptureFixture,
) -> None:
    params = RunnerParams(
        topic="cap-topic",
        url4="(secret prompt here)!'$x'",
        nats_url="nats://user:pass@nats.example.com:4222",
        deadline_s=3600.0,
    )
    with caplog.at_level(logging.INFO, logger=_MAIN_LOGGER):
        _log_boot(params, "00-" + "ab" * 16 + "-" + "cd" * 8 + "-01")

    messages = [record.message for record in caplog.records]
    assert any(
        "runner boot topic=cap-topic url4_chars=25 deadline_s=3600.0 "
        "nats_host=nats.example.com traceparent=present" in message
        for message in messages
    )
    # The expression may carry prompts; the NATS URL may carry credentials. Neither is logged.
    assert not any("secret prompt" in message for message in messages)
    assert not any("user:pass" in message for message in messages)


def test_nats_host_strips_userinfo() -> None:
    assert _nats_host("nats://user:pass@nats.example.com:4222") == "nats.example.com"
    assert _nats_host("nats://localhost:4222") == "localhost"
    assert _nats_host("nats.example.com:4222") == "nats.example.com:4222"
