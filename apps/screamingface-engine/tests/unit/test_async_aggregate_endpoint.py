"""Async aggregation retains the synchronous endpoint contract without thread handoff.

WHY code calls (spec 2026-10-20 R1): the aggregate is a code mount that reads its named
sources — the Case rows as ``evaluations`` and the selection as ``selected`` — not an
``aggregate:N`` intent.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import cast

import pytest

from screamingface_engine.benchmarks.case_evaluation import aggregate_code
from url4 import CodeCall, CodeInput
from url4.core.errors import ResolutionError


def _endpoint(aggregate) -> Callable[[CodeCall], Awaitable[str]]:
    # WHY cast: the factory returns url4's sync-or-async CodeHandler; this one is async.
    return cast(
        Callable[[CodeCall], Awaitable[str]],
        aggregate_code(label="Example", available_case_count=2, aggregate=aggregate),
    )


def _request(selected="2"):
    return CodeCall(
        "/aggregate",
        {},
        (
            CodeInput(1, "evaluations", '[{"case_id":1}]', 0.0),
            CodeInput(2, "selected", selected, 0.0),
        ),
    )


@pytest.mark.asyncio
async def test_async_aggregate_awaits_in_callers_task():
    owner = asyncio.current_task()

    async def aggregate(rows, count):
        await asyncio.sleep(0)
        assert asyncio.current_task() is owner
        return {"rows": json.loads(rows), "count": count}

    endpoint = _endpoint(aggregate)
    assert json.loads(await endpoint(_request())) == {"rows": [{"case_id": 1}], "count": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selected,code",
    [
        ("0", "benchmark_definition_error"),
        ("3", "benchmark_definition_error"),
        ("invalid", "benchmark_definition_error"),
        # WHY: the retired `other:2` operation case has no successor — the code pointer IS the
        # operation; a negative selection takes its slot.
        ("-1", "benchmark_definition_error"),
    ],
)
async def test_async_aggregate_rejects_invalid_selection_before_scoring(selected, code):
    async def aggregate(rows, count):
        pytest.fail("invalid selection reached scorer")

    endpoint = _endpoint(aggregate)
    with pytest.raises(ResolutionError) as caught:
        await endpoint(_request(selected))
    assert caught.value.code == code


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("bad rows"), OSError("missing asset")])
async def test_async_aggregate_translates_same_public_failures(error):
    async def aggregate(rows, count):
        raise error

    endpoint = _endpoint(aggregate)
    with pytest.raises(ResolutionError) as caught:
        await endpoint(_request())
    assert caught.value.code == "benchmark_unavailable"
    assert str(error) in str(caught.value)


@pytest.mark.asyncio
async def test_async_aggregate_cancellation_reaches_scorer_cleanup():
    entered, cleaned = asyncio.Event(), asyncio.Event()

    async def aggregate(rows, count):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()
        return {}

    endpoint = _endpoint(aggregate)
    task = asyncio.ensure_future(endpoint(_request()))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()
