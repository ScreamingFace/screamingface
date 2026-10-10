"""Spec §5.3 — collection iteration: directives, error policy, result shape,
empty/non-iterable handling, parenthesized collections."""

from __future__ import annotations

import json

import pytest

from url4 import StaticIOLayer
from url4.core.errors import CollectionError, ResolutionError
from url4.core.parser import build
from url4.dag import run

# --- parse level ----------------------------------------------------------------


def _iteration(node: object):
    """Narrow a parse result to Iteration for typed attribute access."""
    from url4.core.nodes import Iteration

    assert isinstance(node, Iteration)
    return node


def test_iteration_directives_parse() -> None:
    # §5.3.6 — iteration.concurrency / iteration.on_error
    node = _iteration(
        build("https://x*(b)!'i';iteration.concurrency=10;iteration.on_error=collect")
    )
    assert node.directives.concurrency == 10
    assert node.directives.on_error == "collect"


def test_on_error_default_is_collect() -> None:
    # §5.3.6 — default `collect`
    node = _iteration(build("https://x*(b)!'i'"))
    assert node.directives.on_error == "collect"


def test_on_error_skip_parses() -> None:
    # §5.3.6 — `skip`
    node = _iteration(build("https://x*(b)!'i';iteration.on_error=skip"))
    assert node.directives.on_error == "skip"


def test_on_error_fail_parses() -> None:
    # §5.3.6 — `fail`
    node = _iteration(build("https://x*(b)!'i';iteration.on_error=fail"))
    assert node.directives.on_error == "fail"


def test_slice_parses() -> None:
    # §5.3.6 — iteration.slice=start:end (half-open)
    node = _iteration(build("https://x*(b)!'i';iteration.slice=1:3"))
    assert node.directives.slice == (1, 3)


def test_fmt_result_parses() -> None:
    # §5.3.6 — iteration.fmt_result
    node = _iteration(build("https://x*(b)!'i';iteration.fmt_result=ndjson"))
    assert node.directives.fmt_result == "ndjson"


def test_deprecated_foreach_names_still_work_with_warning() -> None:
    # Contract #4 — foreach.* accepted one version behind a DeprecationWarning
    with pytest.warns(DeprecationWarning):
        node = _iteration(build("https://x*(b)!'i';foreach.concurrency=2"))
    assert node.directives.concurrency == 2


def test_deprecated_abort_maps_to_fail_with_warning() -> None:
    # Contract #4 — `abort` is a deprecated alias of `fail`
    with pytest.warns(DeprecationWarning):
        node = _iteration(build("https://x*(b)!'i';iteration.on_error=abort"))
    assert node.directives.on_error == "fail"


# --- runtime: result shape --------------------------------------------------------


@pytest.mark.asyncio
async def test_map_only_result_is_json_array() -> None:
    # §5.3.8 — protocol default serialization: JSON array (contract #6)
    io = StaticIOLayer({"https://rows": '["a", "b"]'})
    result = await run("https://rows*()!'T: $item'", io)
    assert json.loads(result) == ["T: a", "T: b"]


@pytest.mark.asyncio
async def test_result_ordered_by_element_index() -> None:
    # §5.3.8 — results ordered by original collection order
    io = StaticIOLayer({"https://rows": '["1", "2", "3"]'})
    result = await run("https://rows*()!'$item'", io)
    assert json.loads(result) == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_empty_collection_resolves_to_empty_result() -> None:
    # §5.3.9 — empty collection → success, zero evaluations (contract #5)
    io = StaticIOLayer({"https://rows": "[]"})
    result = await run("https://rows*()!'T: $item'", io)
    assert json.loads(result) == []


@pytest.mark.asyncio
async def test_non_iterable_scalar_fails_malformed_source() -> None:
    # §5.3.9 — scalar collection reference → malformed_source
    io = StaticIOLayer({"https://rows": "just one scalar sentence"})
    with pytest.raises(CollectionError) as exc_info:
        await run("https://rows*()!'T: $item'", io)
    assert exc_info.value.code == "malformed_source"


@pytest.mark.asyncio
async def test_json_object_collection_fails_malformed_source() -> None:
    # §5.3.7 — iteration over a non-array JSON object is an error
    io = StaticIOLayer({"https://rows": '{"not": "an array"}'})
    with pytest.raises(CollectionError) as exc_info:
        await run("https://rows*()!'T: $item'", io)
    assert exc_info.value.code == "malformed_source"


# --- runtime: $item placement (§5.3.4 placement examples) -------------------------


@pytest.mark.asyncio
async def test_item_in_source_values() -> None:
    # §5.3.4 — source-side fan-out
    io = StaticIOLayer({"https://rows": '["1", "2"]', "/api/1": "A", "/api/2": "B"})
    result = await run("https://rows*(r:0:/api/$item)!'$r'", io)
    assert json.loads(result) == ["A", "B"]


@pytest.mark.asyncio
async def test_item_in_intent_only() -> None:
    # §5.3.4 — intent-side fan-out
    io = StaticIOLayer({"https://rows": '["x"]'})
    result = await run("https://rows*()!'Translate: $item'", io)
    assert json.loads(result) == ["Translate: x"]


@pytest.mark.asyncio
async def test_item_in_both_sources_and_intent() -> None:
    # §5.3.4 — $item in both
    io = StaticIOLayer({"https://rows": '["1"]', "/api/1": "A"})
    result = await run("https://rows*(x:0:/api/$item)!'[$item] $x'", io)
    assert json.loads(result) == ["[1] A"]


@pytest.mark.asyncio
async def test_item_field_access() -> None:
    # §5.3.4 — $item.field on structured rows
    io = StaticIOLayer({"https://rows": '[{"q": "one"}, {"q": "two"}]'})
    result = await run("https://rows*()!'Q: $item.q'", io)
    assert json.loads(result) == ["Q: one", "Q: two"]


@pytest.mark.asyncio
async def test_item_array_index_access() -> None:
    # §5.3.4.1 — $item.tags[0] index segment
    io = StaticIOLayer({"https://rows": '[{"tags": ["a", "b"]}]'})
    result = await run("https://rows*()!'First: $item.tags[0]'", io)
    assert json.loads(result) == ["First: a"]


# --- runtime: error policy ----------------------------------------------------------


@pytest.mark.asyncio
async def test_on_error_collect_default_includes_error_objects() -> None:
    # §5.3.6 — collect (the default): failed elements become error objects
    io = StaticIOLayer({"https://rows": '["ok", "bad"]', "/api/ok": "OK"})
    result = await run("https://rows*(r:0:/api/$item)!'$r'", io)
    rows = json.loads(result)
    assert rows[0] == "OK"
    assert isinstance(rows[1], dict) and "error" in rows[1]


@pytest.mark.asyncio
async def test_on_error_skip_omits_failed_elements() -> None:
    # §5.3.6 — skip: omit failed elements from the result
    io = StaticIOLayer({"https://rows": '["ok", "bad"]', "/api/ok": "OK"})
    result = await run("https://rows*(r:0:/api/$item)!'$r';iteration.on_error=skip", io)
    assert json.loads(result) == ["OK"]


@pytest.mark.asyncio
async def test_on_error_fail_aborts_on_first_error() -> None:
    # §5.3.6 — fail: abort on first error
    io = StaticIOLayer({"https://rows": '["ok", "bad"]', "/api/ok": "OK"})
    with pytest.raises(ResolutionError):
        await run("https://rows*(r=/api/$item)!'$r';iteration.on_error=fail", io)


@pytest.mark.asyncio
async def test_slice_evaluates_only_range() -> None:
    # §5.3.6 — iteration.slice=[start, end)
    io = StaticIOLayer({"https://rows": '["a", "b", "c", "d"]'})
    result = await run("https://rows*()!'X $item';iteration.slice=1:3", io)
    assert json.loads(result) == ["X b", "X c"]


# --- parenthesized collections (§5.3.11) ---------------------------------------------


@pytest.mark.asyncio
async def test_parenthesized_collection_scalar_elements() -> None:
    # §5.3.11.2 — quoted scalar elements, $item binds to the scalar
    io = StaticIOLayer({})
    result = await run("('alpha','beta')*()!'X $item'", io)
    assert json.loads(result) == ["X alpha", "X beta"]


@pytest.mark.asyncio
async def test_empty_parenthesized_collection() -> None:
    # §5.3.11.4 — ()*(...)!... resolves to an empty collection
    io = StaticIOLayer({})
    result = await run("()*()!'X $item'", io)
    assert json.loads(result) == []


# --- reduce over iteration ------------------------------------------------------------


@pytest.mark.asyncio
async def test_reducer_receives_json_array_of_rows() -> None:
    # §5.3 example — (src*(body))!reducer: cross-row reduce via relative expression
    seen: dict[str, str] = {}

    def reducer(context: str, intent: str) -> str:
        seen["intent"] = intent
        return "REDUCED"

    io = StaticIOLayer({"https://rows": '["a", "b"]'}, routes={"/reduce": reducer})
    result = await run("(https://rows*()!'R $item')!/reduce()!'agg'", io)
    assert result == "REDUCED"
    assert json.loads(seen["intent"]) == ["R a", "R b"]


# --- nested iteration as a source (§5.3.1 example) ---------------------------------------


def test_iteration_as_source_in_outer_expression_parses() -> None:
    # §5.3.1 — "The iteration expression as a source in an outer expression"
    from url4.core.nodes import Expression, Iteration, Source

    node = build("(scores:0.0:https://data.com/records*(t=$item.answer)!/score())!'Agg $scores'")
    assert isinstance(node, Expression)
    outer_sources = node.sources
    assert len(outer_sources) == 1
    src = outer_sources[0]
    assert isinstance(src, Source)
    assert src.name == "scores" and src.weight == 0.0
    assert isinstance(src.value, Iteration)
