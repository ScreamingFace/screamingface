"""Regression gates for quorum on every route (audit A2, A3 and A9).

A2: ``quorum=N`` gates the fan-out and broadcast routes, not only the local group.
A3: a failed optional broadcast source contributes no part and runs no intent.
A9: quorum counts every resolved post-expansion source, instrumental included.

Spec C §12.2 and Spec B §5.3.12.7, §6.1.2-6.1.3.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from url4.core.context import Context
from url4.core.errors import ResolutionError
from url4.dag import run
from url4.io.static import RouteHandler, StaticIOLayer


def _boom(context: str, intent: str) -> str:
    raise ResolutionError("down")


def _one_of_three_io() -> StaticIOLayer:
    # One of the three calls resolves; /b and /c fail.
    routes = {"/a": lambda c, i: "A", "/b": _boom, "/c": _boom, "/reduce": lambda c, i: "REDUCED"}
    return StaticIOLayer(fetch_map={"https://ok": "OK"}, routes=routes)


def _fanout_io(fail: set[int]) -> StaticIOLayer:
    return StaticIOLayer(routes={**_fanout_routes(fail), "/reduce": lambda c, i: "REDUCED"})


def _fanout_routes(fail: set[int]) -> dict[str, RouteHandler]:
    def make(i: int) -> RouteHandler:
        def handler(context: str, intent: str) -> str:
            if i in fail:
                raise ResolutionError("down")
            return f"resp{i}"

        return handler

    return {f"/m{i}": make(i) for i in range(4)}


@pytest.mark.asyncio
async def test_fanout_quorum_not_met_raises_resolution_error() -> None:
    # A2: the fan-out route honours quorum=3 when only one call resolves.
    with pytest.raises(ResolutionError) as exc_info:
        await run(
            "(/a(x)!'y', /b(x)!'y';optional, /c(x)!'y';optional)!'merge';quorum=3",
            _one_of_three_io(),
            processor="/reduce",
        )
    assert exc_info.value.code == "quorum_not_met"


@pytest.mark.asyncio
async def test_broadcast_calls_quorum_not_met_raises_resolution_error() -> None:
    # A2: the broadcast route honours quorum=3 when only one call resolves.
    with pytest.raises(ResolutionError) as exc_info:
        await run(
            "(/a(x)!'y', /b(x)!'y';optional, /c(x)!'y';optional)!*'merge';quorum=3",
            _one_of_three_io(),
            processor="/reduce",
        )
    assert exc_info.value.code == "quorum_not_met"


@pytest.mark.asyncio
async def test_local_group_quorum_not_met_raises_resolution_error() -> None:
    # Control: the local group already enforces quorum=3 with one source resolved.
    with pytest.raises(ResolutionError) as exc_info:
        await run(
            "(https://ok, /b(x)!'y';optional, /c(x)!'y';optional)!'merge';quorum=3",
            _one_of_three_io(),
        )
    assert exc_info.value.code == "quorum_not_met"


@pytest.mark.asyncio
async def test_instrumental_source_counts_toward_quorum() -> None:
    # A9: the scalar weight 0.0 source resolves, so quorum=2 is met.
    io = StaticIOLayer(fetch_map={"https://a": "A", "https://i": "I"})
    result = await run("(https://a, inst:0.0:https://i)!'go';quorum=2", io)
    assert result.startswith("go")


@pytest.mark.asyncio
async def test_instrumental_source_failure_counts_against_quorum() -> None:
    # Control (passes before A9 too): with the instrumental source failing, one resolves.
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    with pytest.raises(ResolutionError) as exc_info:
        await run("(https://a, inst:0.0:https://i;optional)!'go';quorum=2", io)
    assert exc_info.value.code == "quorum_not_met"


@pytest.mark.asyncio
async def test_expanded_source_counts_its_elements_toward_quorum() -> None:
    # A9: the expanded source contributes three elements, so 3 + 1 = 4 resolve.
    io = StaticIOLayer(fetch_map={"https://a": "A", "https://rows": '["r1","r2","r3"]'})
    assert (await run("(https://rows;expand, https://a)!'go';quorum=4", io)).startswith("go")
    with pytest.raises(ResolutionError) as exc_info:
        await run("(https://rows;expand, https://a)!'go';quorum=5", io)
    assert exc_info.value.code == "quorum_not_met"


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(n=st.integers(2, 4), data=st.data())
def test_fanout_quorum_enforced(n: int, data: st.DataObject) -> None:
    fail = data.draw(st.sets(st.integers(0, n - 1), max_size=n - 1))
    quorum = data.draw(st.integers(1, n))
    calls = ", ".join(f"/m{i}(x)!'y';optional" for i in range(n))
    expr = f"({calls})!'merge';quorum={quorum}"

    async def go() -> str:
        return await run(expr, _fanout_io(fail), processor="/reduce")

    successes = n - len(fail)
    try:
        asyncio.run(go())
        raised = False
    except ResolutionError as e:
        if e.code != "quorum_not_met":
            raise
        raised = True
    assert raised == (successes < quorum)


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(n=st.integers(2, 3), data=st.data())
def test_broadcast_omits_failed_optional_sources(n: int, data: st.DataObject) -> None:
    # A3: a failed optional source's part is omitted; survivors keep their positions.
    fail = data.draw(st.sets(st.integers(0, n - 1), max_size=n - 1))
    calls = ", ".join(f"/m{i}(x)!'y';optional" for i in range(n))
    expr = f"({calls})!*'merge'"

    async def positions() -> list[int]:
        parts = json.loads(await run(expr, _fanout_io(fail), processor="/reduce"))
        return sorted(int(p["source_position"]) for p in parts)

    assert asyncio.run(positions()) == [i + 1 for i in range(n) if i not in fail]


@pytest.mark.asyncio
async def test_broadcast_runs_no_intent_when_quorum_fails() -> None:
    # Spec B §6.1.2: the intent runs only once quorum is met — not per resolved source first.
    calls: list[str] = []

    async def counting_process(sources: str, intent: str | None, scope: Context) -> str:
        calls.append(sources)
        return sources

    expr = "(/m0(x)!'y', /m1(x)!'y';optional, /m2(x)!'y';optional)!*'merge';quorum=3"
    with pytest.raises(ResolutionError) as exc_info:
        await run(expr, _fanout_io({1, 2}), process=counting_process)
    assert exc_info.value.code == "quorum_not_met"
    assert calls == []


@pytest.mark.asyncio
async def test_broadcast_quorum_counts_expanded_elements() -> None:
    # Spec B §5.3.12.7 on the broadcast route: 3 expanded rows + 1 source = 4 resolved.
    io = StaticIOLayer(
        fetch_map={"https://a": "A", "https://rows": '["r1","r2","r3"]'},
        routes={"/reduce": lambda c, i: "REDUCED"},
    )
    await run("(https://rows;expand, https://a)!*'go';quorum=4", io, processor="/reduce")
    with pytest.raises(ResolutionError) as exc_info:
        await run("(https://rows;expand, https://a)!*'go';quorum=5", io, processor="/reduce")
    assert exc_info.value.code == "quorum_not_met"


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["!", "!*"], ids=["fanout", "broadcast"])
async def test_required_source_failure_fails_even_when_quorum_is_met(op: str) -> None:
    # Spec C §12.2: quorum cannot override a failed ;required source (the default).
    expr = f"(/m0(x)!'y', /m1(x)!'y', /m2(x)!'y';optional){op}'merge';quorum=1"
    with pytest.raises(ResolutionError) as exc_info:
        await run(expr, _fanout_io({1}), processor="/reduce")
    assert exc_info.value.code != "quorum_not_met"


@pytest.mark.asyncio
async def test_quorum_on_a_sugar_call_belongs_to_that_call() -> None:
    # Spec B §3.1.1.1: `/m0(x)!'go';quorum=2` is `/m0?quorum=2&q=(x)!'go'` — the quorum
    # is the remote call's own parameter, not a local quorum over one source.
    assert await run("/m0(x)!'go';quorum=2", _fanout_io(set())) == "resp0"
