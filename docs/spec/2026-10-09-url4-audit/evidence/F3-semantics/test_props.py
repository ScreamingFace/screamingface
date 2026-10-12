"""Property tests for url4 fan-out / fan-in data semantics (F3 lane).

Run:  .venv/bin/python -m pytest test_props.py -q -p no:cacheprovider

Each test states the law that SHOULD hold. A failing test is a counterexample
to that law against the real code (packages/url4, editable install).
"""

from __future__ import annotations

import asyncio
import json
import random

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from url4.core.context import Context
from url4.core.errors import CollectionError, ResolutionError
from url4.core.nodes import IterationDirectives, Iteration, Url
from url4.dag import ExecutionContext, run
from url4.dag.node import SourceFailure
from url4.dag.nodes._shared import _ITEM_KEY, _check_quorum, _gather, _rows_to_json, _substitute
from url4.dag.nodes.iteration import MapNode
from url4.dag.semantics.collection import parse_collection
from url4.dag.semantics.ensemble import substitute_env_vars, substitute_item
from url4.io.static import StaticIOLayer

SETTINGS = settings(
    max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
# Text that includes the url4 metacharacters on purpose.
META = st.text(alphabet=st.sampled_from(list("ab $.{}[]\"\\item01_x\n")), max_size=24)
TOKENS = st.lists(
    st.sampled_from(["$item", "$item.a", "$x", "$$", "$index", "{", "}", '"', "\\", "a", " ", ".", "\n"]),
    max_size=6,
).map("".join)
ANY = st.one_of(TOKENS, META, st.text(max_size=24))


class _Strict:
    strict_fields = False


# --- 1. substitution: a value is inserted exactly once (no re-scan) -------------


@SETTINGS
@given(v=ANY)
def test_item_path_value_not_rescanned(v: str) -> None:
    """LAW: substitute_item('<$item.a>', row) == '<' + row.a + '>' (outside a blob)."""
    out = substitute_item("<$item.a>", json.dumps({"a": v}))
    assert out == f"<{v}>"


@SETTINGS
@given(v=ANY)
def test_row_value_opaque_through_leaf_pipeline(v: str) -> None:
    """LAW (the _substitute docstring): a row value is opaque data, not re-scanned for $name."""
    scope = Context(bindings={_ITEM_KEY: json.dumps({"q": v}), "x": "BOUND"}, parent=None)
    assert _substitute("Q=$item.q", scope, _Strict()) == f"Q={v}"


@SETTINGS
@given(v=ANY)
def test_env_value_not_rescanned(v: str) -> None:
    """LAW: substitute_env_vars is one pass — a bound value containing $name stays literal."""
    scope = Context(bindings={"a": v, "b": "BBB"}, parent=None)
    assert substitute_env_vars("<$a>", scope) == f"<{v}>"


# --- 2. JSON escaping inside a {...} blob yields valid JSON -------------------


@SETTINGS
@given(v=ANY)
def test_env_value_in_blob_is_valid_json(v: str) -> None:
    scope = Context(bindings={"a": v}, parent=None)
    out = substitute_env_vars('{"k": "$a"}', scope)
    assert json.loads(out) == {"k": v}


@SETTINGS
@given(v=ANY)
def test_bare_item_in_blob_is_valid_json(v: str) -> None:
    row = json.dumps({"a": v})
    out = substitute_item('{"k": "$item"}', row)
    assert json.loads(out) == {"k": row}


@SETTINGS
@given(prefix=ANY, v=ANY)
def test_blob_after_path_value_is_valid_json(prefix: str, v: str) -> None:
    """LAW: a path value inserted BEFORE a blob must not change how the blob is escaped."""
    row = json.dumps({"a": prefix})
    out = substitute_item('$item.a {"k": "$item"}', row)
    tail = out[len(prefix) + 1:]
    assert json.loads(tail) == {"k": row}


# --- 3. collection parsing ---------------------------------------------------


@SETTINGS
@given(items=st.lists(st.one_of(st.text(max_size=8), st.integers(), st.none(),
                                 st.dictionaries(st.text(max_size=3), st.integers(), max_size=2)),
                       min_size=1, max_size=4))
def test_json_array_items_are_injective(items: list) -> None:
    """LAW: two different JSON arrays never parse to the same item list."""
    as_strings = [i if isinstance(i, str) else json.dumps(i) for i in items]
    other = json.dumps(as_strings)  # the same items, all as JSON strings
    if json.loads(other) == items:
        return
    assert parse_collection(json.dumps(items)) != parse_collection(other)


@SETTINGS
@given(lines=st.lists(st.from_regex(r"[A-Za-z]{1,6},[A-Za-z]{1,6}", fullmatch=True),
                      min_size=2, max_size=4))
def test_plain_lines_count_preserved(lines: list[str]) -> None:
    """EXPECTATION (spec-level): N undeclared text lines → N items. (CSV sniff breaks it.)"""
    assert len(parse_collection("\n".join(lines))) == len(lines)


@SETTINGS
@given(lines=st.lists(st.from_regex(r"[0-9]{1,3}\.[0-9]{1,2}0", fullmatch=True),
                      min_size=2, max_size=4))
def test_numeric_text_lines_round_trip(lines: list[str]) -> None:
    """EXPECTATION: an undeclared line of text comes back as the same text."""
    assert parse_collection("\n".join(lines)) == lines


@SETTINGS
@given(rows=st.lists(st.text(max_size=12), max_size=5))
def test_rows_to_json_is_rfc_json(rows: list[str]) -> None:
    """LAW: the reducer input is strict JSON (no NaN/Infinity tokens)."""
    out = _rows_to_json(rows)
    json.loads(out, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))


# --- 4. MapNode concurrency: order, collect, skip ----------------------------


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


def _run_map(n: int, fail: set[int], delays: list[float], on_error: str, conc: int):
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


# --- 5. quorum -----------------------------------------------------------------


@SETTINGS
@given(
    slots=st.lists(st.tuples(st.sampled_from(["ok", "fail", "expand2", "expand0"]), st.booleans()),
                   min_size=1, max_size=5),
    quorum=st.integers(0, 6),
)
def test_quorum_counts_resolved_sources(slots, quorum) -> None:
    """SPEC (§9.1 table, package spec line 132): 'require >= N sources to resolve'.

    Resolved authored sources = slots whose value is not a SourceFailure.
    """
    specs = tuple((f"s{i}", instr) for i, (_, instr) in enumerate(slots))
    inputs = {}
    for i, (kind, _) in enumerate(slots):
        inputs[f"src:{i}"] = {
            "ok": "v",
            "fail": SourceFailure("x", "boom"),
            "expand2": ["e1", "e2"],
            "expand0": [],
        }[kind]
    resolved = sum(1 for kind, _ in slots if kind != "fail")
    g = _gather(inputs, specs)
    raised = False
    try:
        _check_quorum(g, quorum)
    except ResolutionError:
        raised = True
    assert raised == (resolved < quorum)


def _fanout_io(fail: set[int]) -> StaticIOLayer:
    def make(i):
        def h(c, it):
            if i in fail:
                raise ResolutionError("down")
            return f"resp{i}"
        return h

    routes = {f"/m{i}": make(i) for i in range(4)}
    routes["/reduce"] = lambda c, it: "REDUCED"
    return StaticIOLayer(routes=routes)


@settings(max_examples=40, deadline=None)
@given(n=st.integers(2, 4), data=st.data())
def test_fanout_quorum_enforced(n: int, data) -> None:
    fail = data.draw(st.sets(st.integers(0, n - 1), max_size=n - 1))
    quorum = data.draw(st.integers(1, n))
    calls = ", ".join(f"/m{i}(x)!'y';optional" for i in range(n))
    expr = f"({calls})!'merge';quorum={quorum}"

    async def go():
        return await run(expr, _fanout_io(fail), processor="/reduce")

    successes = n - len(fail)
    try:
        asyncio.run(go())
        raised = False
    except ResolutionError as e:
        raised = getattr(e, "code", None) == "quorum_not_met"
    assert raised == (successes < quorum)


@settings(max_examples=30, deadline=None)
@given(n=st.integers(2, 3), data=st.data())
def test_broadcast_omits_failed_optional_sources(n: int, data) -> None:
    """DOCSTRING (BroadcastCollectNode, §6.1.3): a failed optional source's part is omitted."""
    fail = data.draw(st.sets(st.integers(0, n - 1), max_size=n - 1))
    calls = ", ".join(f"/m{i}(x)!'y';optional" for i in range(n))
    expr = f"({calls})!*'merge'"

    async def go():
        return json.loads(await run(expr, _fanout_io(fail), processor="/reduce"))

    parts = asyncio.run(go())
    assert sorted(p["source_position"] for p in parts) == [i + 1 for i in range(n) if i not in fail]
