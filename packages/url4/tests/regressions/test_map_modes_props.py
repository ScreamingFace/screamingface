"""MapNode error-mode laws (regression safety net, F3 audit).

Ported from ``evidence/F3-semantics/test_props.py``. Only the three MapNode laws that
hold on the current code are kept: collect keeps order and loses no row, skip drops
exactly the failed rows, and fail is all-or-nothing.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from url4.core.errors import ResolutionError
from url4.core.nodes import Iteration, IterationDirectives, OnErrorPolicy, Url
from url4.dag import ExecutionContext, run
from url4.io.static import StaticIOLayer


def _map_io(n: int, fail: set[int], delays: list[float]) -> StaticIOLayer:
    async def solve(context: str, intent: str | None) -> str:
        i = int(context[1:])
        await asyncio.sleep(delays[i])
        if i in fail:
            raise ResolutionError(f"row {i} failed")
        return f"ok{i}"

    return StaticIOLayer(
        fetch_map={"https://data": json.dumps([f"r{i}" for i in range(n)])},
        routes={"/solve": solve},
    )


def _run_map(n: int, fail: set[int], delays: list[float], on_error: OnErrorPolicy, conc: int):
    io = _map_io(n, fail, delays)
    node = Iteration(
        collection=Url("https://data"),
        body="/solve($item)!'go'",
        directives=IterationDirectives(on_error=on_error, concurrency=conc),
    )
    ctx = ExecutionContext(io)

    async def go():
        return json.loads(await run(node, ctx=ctx))

    return asyncio.run(go()), ctx.collected_errors


map_case = st.integers(min_value=1, max_value=8).flatmap(
    lambda n: st.tuples(
        st.just(n),
        st.sets(st.integers(0, n - 1)),
        st.lists(st.sampled_from([0.0, 0.001, 0.003]), min_size=n, max_size=n),
        st.integers(1, 4),
    )
)


@settings(max_examples=60, deadline=None)
@given(case=map_case)
def test_map_collect_order_and_no_row_lost(case) -> None:
    n, fail, delays, conc = case
    out, collected = _run_map(n, fail, delays, "collect", conc)
    assert len(out) == n
    for i, row in enumerate(out):
        if i in fail:
            assert isinstance(row, dict) and "error" in row
        else:
            assert row == f"ok{i}"
    assert collected == len(fail)


@settings(max_examples=60, deadline=None)
@given(case=map_case)
def test_map_skip_drops_exactly_failed(case) -> None:
    n, fail, delays, conc = case
    out, collected = _run_map(n, fail, delays, "skip", conc)
    assert out == [f"ok{i}" for i in range(n) if i not in fail]
    assert collected == 0


@settings(max_examples=60, deadline=None)
@given(case=map_case)
def test_map_fail_all_or_nothing(case) -> None:
    n, fail, delays, conc = case
    if not fail:
        out, _ = _run_map(n, fail, delays, "fail", conc)
        assert out == [f"ok{i}" for i in range(n)]
        return
    with pytest.raises(ResolutionError):
        _run_map(n, fail, delays, "fail", conc)
