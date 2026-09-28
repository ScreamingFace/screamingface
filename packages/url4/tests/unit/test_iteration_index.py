"""A row's native index follows selected order, not task completion order."""

import json

import pytest

from url4 import StaticIOLayer
from url4.core.nodes import Iteration, IterationDirectives, Url
from url4.dag import run


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slice_,expected", [(None, ["0:a", "1:b", "2:c"]), ((1, 3), ["0:b", "1:c"]), ((3, 3), [])]
)
@pytest.mark.parametrize("policy", ["collect", "skip", "fail"])
async def test_index_is_zero_based_after_selection(slice_, expected, policy):
    io = StaticIOLayer(
        fetch_map={"https://rows": '["a","b","c"]'},
        routes={"/echo": lambda context, intent: context},
    )
    node = Iteration(
        collection=Url("https://rows"),
        body="/echo('$index:$item')!'read'",
        directives=IterationDirectives(slice=slice_, on_error=policy),
    )
    assert json.loads(await run(node, io)) == expected


@pytest.mark.asyncio
async def test_completion_order_does_not_change_index():
    import asyncio

    from url4.peer.server import Url4Node

    node = Url4Node()
    node.data("/rows", '["first","second"]', media_type="application/json")
    second_done = asyncio.Event()
    calls = []

    @node.endpoint("/work")
    async def work(request):
        if request.context == "first":
            await asyncio.wait_for(second_done.wait(), 1)
        calls.append((request.context, request.intent))
        if request.context == "second":
            second_done.set()
        return request.intent

    try:
        result = await run("/rows*(result:0.0:/work($item)!'$index')!'$result'", node)
        assert json.loads(result) == ["0", "1"]
        assert calls == [("second", "1"), ("first", "0")]
    finally:
        await node.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["collect", "skip"])
async def test_failed_row_does_not_renumber_later_rows(policy):
    from url4.core.errors import ResolutionError

    seen = []

    def work(context, intent):
        seen.append(intent)
        if context == "bad":
            raise ResolutionError("bad row", permanent=True)
        return intent

    io = StaticIOLayer(fetch_map={"/rows": '["ok","bad","ok"]'}, routes={"/work": work})
    result = json.loads(
        await run(
            f"/rows*(result:0.0:/work($item)!'$index')!'$result';iteration.on_error={policy}", io
        )
    )
    assert sorted(seen) == ["0", "1", "2"]
    assert result[0] == "0" and result[-1] == "2"
    assert len(result) == (3 if policy == "collect" else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("as_ast", [False, True])
async def test_index_in_nested_expression_and_struct(as_ast):
    from url4.core.grammar import parse

    expression = "/rows*(result:0.0:/echo({position:'$index',input:'$item'})!'read')!'$result'"
    io = StaticIOLayer(
        fetch_map={"/rows": '["a","b"]'}, routes={"/echo": lambda context, intent: context}
    )
    result = json.loads(await run(parse(expression) if as_ast else expression, io))
    assert result == [{"position": "0", "input": "a"}, {"position": "1", "input": "b"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("as_ast", [False, True])
async def test_nested_iteration_rebinds_index_and_can_capture_outer_index(as_ast):
    from url4.core.grammar import parse

    expression = (
        "/rows*(outer:0.0:$index, result:0.0:/inner*("
        "v:0.0:/echo('$outer:$index:$item')!'read')!'$v')!'$result'"
    )
    io = StaticIOLayer(
        fetch_map={"/rows": '["a","b"]', "/inner": '["x","y"]'},
        routes={"/echo": lambda context, intent: context},
    )
    result = json.loads(await run(parse(expression) if as_ast else expression, io))
    assert result == [["0:0:x", "0:1:y"], ["1:0:x", "1:1:y"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("as_ast", [False, True])
async def test_index_is_reserved_inside_iteration_but_ordinary_outside(as_ast):
    from url4.core.grammar import parse

    expression = (
        "(index:0.0:'named', outside:0.0:$index, "
        "rows:0.0:/rows*(index:0.0:'local', v:0.0:$index)!'$v')!"
        "'$outside|$rows|$index'"
    )
    io = StaticIOLayer(fetch_map={"/rows": '["a","b"]'})
    assert await run(parse(expression) if as_ast else expression, io) == 'named|["0", "1"]|named'


@pytest.mark.asyncio
async def test_index_preserves_reference_escaping_and_longer_names():
    io = StaticIOLayer(fetch_map={"/rows": '["a"]'})
    node = Iteration(collection=Url("/rows"), body="'$$index:$index:$indexes'", intent="''")
    assert json.loads(await run(node, io)) == ["$index:0:$indexes"]
    assert await run("()!'$index'", io) == "$index"


@pytest.mark.asyncio
async def test_retry_observes_the_same_index():
    from url4.core.errors import ResolutionError

    seen = []

    def work(context, intent):
        seen.append((context, intent))
        if len(seen) == 1:
            raise ResolutionError("temporary", permanent=False)
        return intent

    io = StaticIOLayer(fetch_map={"/rows": '["a"]'}, routes={"/work": work})
    expression = "/rows*(r:0.0:/work($item)!'$index';retry=1)!'$r'"
    assert json.loads(await run(expression, io)) == ["0"]
    assert seen == [("a", "0"), ("a", "0")]
