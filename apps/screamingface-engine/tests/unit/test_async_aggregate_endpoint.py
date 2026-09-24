"""Async aggregation retains the synchronous endpoint contract without thread handoff."""

import asyncio
import json

import pytest

from screamingface_engine.benchmarks.evaluation import async_aggregate_endpoint
from url4.core.errors import ResolutionError
from url4.peer.server import Request


def _request(intent="aggregate:2"):
    return Request(path="/aggregate", context='[{"case_id":1}]', intent=intent, params={})


@pytest.mark.asyncio
async def test_async_aggregate_awaits_in_callers_task():
    owner = asyncio.current_task()

    async def aggregate(rows, count):
        await asyncio.sleep(0)
        assert asyncio.current_task() is owner
        return {"rows": json.loads(rows), "count": count}

    endpoint = async_aggregate_endpoint(
        label="Example", available_case_count=2, aggregate=aggregate
    )
    assert json.loads(await endpoint(_request())) == {"rows": [{"case_id": 1}], "count": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent,code",
    [
        ("aggregate:0", "benchmark_definition_error"),
        ("aggregate:3", "benchmark_definition_error"),
        ("aggregate:invalid", "benchmark_definition_error"),
        ("other:2", "benchmark_operation_unsupported"),
    ],
)
async def test_async_aggregate_rejects_invalid_selection_before_scoring(intent, code):
    async def aggregate(rows, count):
        pytest.fail("invalid selection reached scorer")

    endpoint = async_aggregate_endpoint(
        label="Example", available_case_count=2, aggregate=aggregate
    )
    with pytest.raises(ResolutionError) as caught:
        await endpoint(_request(intent))
    assert caught.value.code == code


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("bad rows"), OSError("missing asset")])
async def test_async_aggregate_translates_same_public_failures(error):
    async def aggregate(rows, count):
        raise error

    endpoint = async_aggregate_endpoint(
        label="Example", available_case_count=2, aggregate=aggregate
    )
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

    endpoint = async_aggregate_endpoint(
        label="Example", available_case_count=2, aggregate=aggregate
    )
    task = asyncio.ensure_future(endpoint(_request()))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()
