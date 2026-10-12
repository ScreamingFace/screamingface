"""Broadcast over an expanded source applies the intent once per element.

Spec B §5.3.12.4 rule 3: each element of an expanded source "becomes an independent
source"; §6.1.2: the broadcast intent runs "once per *resolved* source". Expanded
elements take renumbered positions (§5.3.12.4 rule 4) and the names ``name[i]`` /
``src[i]`` (§5.3.12.5).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from url4.core.context import Context
from url4.core.errors import ResolutionError
from url4.dag import run
from url4.io.static import StaticIOLayer


def _io() -> StaticIOLayer:
    return StaticIOLayer(fetch_map={"https://a": "A", "https://rows": '["r1","r2"]'})


async def _echo(sources: str, intent: str | None, scope: Context) -> str:
    return f"{intent}:{sources}"


@pytest.mark.asyncio
async def test_broadcast_runs_the_intent_once_per_expanded_element() -> None:
    out = await run("(https://rows;expand, https://a)!*'go'", _io(), process=_echo)
    assert json.loads(out) == [
        {"source_position": 1, "source_name": "src[0]", "result": "go:r1"},
        {"source_position": 2, "source_name": "src[1]", "result": "go:r2"},
        {"source_position": 3, "source_name": None, "result": "go:A"},
    ]


@pytest.mark.asyncio
async def test_named_expanded_elements_take_indexed_names() -> None:
    out = await run("(rows=https://rows;expand, https://a)!*'$current'", _io(), process=_echo)
    rows = json.loads(out)
    assert [(r["source_position"], r["source_name"]) for r in rows] == [
        (1, "rows[0]"),
        (2, "rows[1]"),
        (3, None),
    ]
    # $current is the element, not the joined list.
    assert [r["result"] for r in rows] == ["r1:r1", "r2:r2", "A:A"]


@pytest.mark.asyncio
async def test_iteration_source_is_one_broadcast_source() -> None:
    # Spec B §5.3.8: an iteration expression "resolves to a single value". In source
    # position it is ONE resolved source, so §6.1.2 applies the intent to it once.
    io = StaticIOLayer(fetch_map={"https://data": '["r1","r2"]', "https://a": "A"})
    out = await run("(https://data*(x)!'y', https://a)!*'z'", io, process=_echo)
    rows = json.loads(out)
    assert [(r["source_position"], r["source_name"]) for r in rows] == [(1, None), (2, None)]
    assert rows[0]["result"].startswith("z:[")


@pytest.mark.asyncio
async def test_merge_node_joins_a_list_that_is_not_an_expansion() -> None:
    # Only an ExpandNode output is split per element; any other list is one source.
    from url4.dag import ExecutionContext
    from url4.dag.nodes import MergeNode

    ctx = ExecutionContext(StaticIOLayer(), process=_echo)
    out = await MergeNode(intent_template="go").resolve({"source": ["r1", "r2"]}, ctx)
    assert out == "go:r1\nr2"


def _feed(n: int) -> StaticIOLayer:
    rows = json.dumps([f"r{i}" for i in range(n)])
    return StaticIOLayer(fetch_map={"https://rows": rows})


@pytest.mark.asyncio
async def test_expanded_elements_run_under_the_map_concurrency_bound() -> None:
    from url4.dag.nodes import DEFAULT_MAP_CONCURRENCY

    active = peak = 0

    async def slow(sources: str, intent: str | None, scope: Context) -> str:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return sources

    n = DEFAULT_MAP_CONCURRENCY + 4
    out = await asyncio.wait_for(
        run("(https://rows;expand)!*'go'", _feed(n), process=slow), timeout=5
    )
    assert len(json.loads(out)) == n
    assert peak == DEFAULT_MAP_CONCURRENCY


@pytest.mark.asyncio
async def test_a_failing_element_cancels_its_siblings() -> None:
    cancelled: list[str] = []
    never = asyncio.Event()

    async def one_fails(sources: str, intent: str | None, scope: Context) -> str:
        if sources == "r0":
            raise ResolutionError("element down")
        try:
            await never.wait()
        except asyncio.CancelledError:
            cancelled.append(sources)
            raise
        return sources

    with pytest.raises(ResolutionError, match="element down"):
        await asyncio.wait_for(
            run("(https://rows;expand)!*'go'", _feed(3), process=one_fails), timeout=5
        )
    assert sorted(cancelled) == ["r1", "r2"]
