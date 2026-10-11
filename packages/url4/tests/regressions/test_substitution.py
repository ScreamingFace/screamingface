"""Audit A1, A4, A5 — a substituted value is inserted once and never scanned again.

Spec B §6.2 and §8.2.5: one interpolation scan over the template. Row data
(`$item`) and bound values (`$name`) are opaque: a `$` inside them is text, not
a reference, and `$$` collapses exactly once. Report:
docs/spec/2026-10-09-url4-audit/report.md §4.A (A1, A4, A5).
"""

from __future__ import annotations

import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from url4.core.context import Context
from url4.core.nodes import Iteration, Url
from url4.dag import ExecutionContext, run
from url4.dag.nodes._shared import _ITEM_KEY, _substitute
from url4.dag.semantics.ensemble import substitute_env_vars, substitute_item
from url4.io.static import StaticIOLayer

SETTINGS = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
# Text that carries the url4 metacharacters on purpose.
META = st.text(alphabet=st.sampled_from(list('ab $.{}[]"\\item01_x\n')), max_size=24)
TOKENS = st.lists(
    st.sampled_from(
        ["$item", "$item.a", "$x", "$$", "$index", "{", "}", '"', "\\", "a", " ", ".", "\n"]
    ),
    max_size=6,
).map("".join)
ANY = st.one_of(TOKENS, META, st.text(max_size=24))


_LENIENT = ExecutionContext(StaticIOLayer())


# --- properties ------------------------------------------------------------------


@SETTINGS
@given(v=ANY)
def test_item_path_value_not_rescanned(v: str) -> None:
    assert substitute_item("<$item.a>", json.dumps({"a": v})) == f"<{v}>"


@SETTINGS
@given(v=ANY)
def test_row_value_opaque_through_leaf_pipeline(v: str) -> None:
    scope = Context(bindings={_ITEM_KEY: json.dumps({"q": v}), "x": "BOUND"}, parent=None)
    assert _substitute("Q=$item.q", scope, _LENIENT) == f"Q={v}"


@SETTINGS
@given(v=ANY)
def test_env_value_not_rescanned(v: str) -> None:
    scope = Context(bindings={"a": v, "b": "BBB"}, parent=None)
    assert substitute_env_vars("<$a>", scope) == f"<{v}>"


@SETTINGS
@given(v=ANY)
def test_env_value_in_blob_is_valid_json(v: str) -> None:
    scope = Context(bindings={"a": v}, parent=None)
    assert json.loads(substitute_env_vars('{"k": "$a"}', scope)) == {"k": v}


@SETTINGS
@given(v=ANY)
def test_bare_item_in_blob_is_valid_json(v: str) -> None:
    row = json.dumps({"a": v})
    assert json.loads(substitute_item('{"k": "$item"}', row)) == {"k": row}


@SETTINGS
@given(prefix=ANY, v=ANY)
def test_blob_after_path_value_is_valid_json(prefix: str, v: str) -> None:
    """A path value inserted before a blob does not change how the blob is escaped."""
    row = json.dumps({"a": prefix})
    out = substitute_item('$item.a {"k": "$item"}', row)
    assert json.loads(out[len(prefix) + 1 :]) == {"k": row}


# --- explicit cases from the report ------------------------------------------------


@pytest.mark.parametrize(
    "row",
    ["costs $$5", "see $index here", "literal $item", "$x", "$item.a", "{$x}"],
)
def test_row_text_arrives_unchanged(row: str) -> None:
    scope = Context(bindings={_ITEM_KEY: row, "x": "BOUND", "\x00index": "1"}, parent=None)
    assert _substitute("<$item>", scope, _LENIENT) == f"<{row}>"


def test_bare_item_value_is_not_rescanned_for_item() -> None:
    assert substitute_item("<$item.a>", '{"a":"$item"}') == "<$item>"


def test_path_value_with_brace_keeps_later_blob_valid_json() -> None:
    row = '{"a":"{"}'
    out = substitute_item('$item.a {"k": "$item"}', row)
    assert out.startswith("{ ")
    assert json.loads(out[2:]) == {"k": row}


def test_escape_and_reference_in_one_template() -> None:
    scope = Context(bindings={_ITEM_KEY: '{"a": "A"}', "a": "BOUND"}, parent=None)
    out = _substitute("$$a $$item $item.a $a", scope, _LENIENT)
    assert out == "$a $item A BOUND"


def _echo_io() -> StaticIOLayer:
    return StaticIOLayer(
        fetch_map={"https://rows": json.dumps(["costs $$5", "see $index here", "$x"])},
        routes={"/echo": lambda context, intent: intent},
    )


@pytest.mark.asyncio
async def test_call_intent_escape_collapses_once() -> None:
    """A4: `$$a` in a call intent reaches the handler as `$a`, even with `a` bound."""
    scope = Context(bindings={"a": "BOUND"}, parent=None)
    out = await run("/echo(x)!'literal $$a'", ctx=ExecutionContext(_echo_io(), scope=scope))
    assert out == "literal $a"


@pytest.mark.asyncio
async def test_call_intent_bound_value_is_not_rescanned() -> None:
    scope = Context(bindings={"a": "has $b inside", "b": "B"}, parent=None)
    out = await run("/echo(x)!'<$a>'", ctx=ExecutionContext(_echo_io(), scope=scope))
    assert out == "<has $b inside>"


@pytest.mark.asyncio
async def test_row_reaches_call_intent_unchanged() -> None:
    """A1 end to end: rows from fetched data are opaque in a per-row call intent."""
    scope = Context(bindings={"x": "BOUND"}, parent=None)
    node = Iteration(collection=Url("https://rows"), body="/echo(x)!'<$item>'")
    out = await run(node, ctx=ExecutionContext(_echo_io(), scope=scope))
    assert json.loads(out) == ["<costs $$5>", "<see $index here>", "<$x>"]


@pytest.mark.asyncio
async def test_fanout_instruction_escape_collapses_once() -> None:
    """A4 (fan-out): `$$a` in a reducer instruction stays `$a`, even when `a` names a response."""
    io = StaticIOLayer(
        routes={
            "/a": lambda context, intent: "RESP-A",
            "/r": lambda context, intent: intent,
        }
    )
    out = await run("(a:/a(x)!'i', b:/a(y)!'i')!'pay $$a then $a'", io, processor="/r")
    assert out.endswith("[Instruction]\npay $a then RESP-A")


@pytest.mark.asyncio
async def test_fanout_instruction_bound_value_is_not_rescanned() -> None:
    """A bound value inserted into a reducer instruction is not re-scanned for response names."""
    io = StaticIOLayer(
        routes={
            "/a": lambda context, intent: "RESP-A",
            "/r": lambda context, intent: intent,
        }
    )
    scope = Context(bindings={"note": "see $a"}, parent=None)
    ctx = ExecutionContext(io, processor="/r", scope=scope)
    out = await run("(a:/a(x)!'i', b:/a(y)!'i')!'$note'", ctx=ctx)
    assert out.endswith("[Instruction]\nsee $a")


def _fanout_io(**fetch: str) -> StaticIOLayer:
    return StaticIOLayer(
        fetch_map={f"https://{k}": v for k, v in fetch.items()},
        routes={
            "/a": lambda context, intent: "RESP-A",
            "/j": lambda context, intent: '{"x": "X1"}',
            "/r": lambda context, intent: intent,
        },
    )


@pytest.mark.asyncio
async def test_fanout_response_name_shadows_outer_binding() -> None:
    """Response names are the sibling frame: they shadow an outer binding of the same name."""
    scope = Context(bindings={"a": "OUTER"}, parent=None)
    ctx = ExecutionContext(_fanout_io(), processor="/r", scope=scope)
    out = await run("(a:/a(x)!'i', b:/a(y)!'i')!'pay $a'", ctx=ctx)
    assert out.endswith("[Instruction]\npay RESP-A")


@pytest.mark.asyncio
async def test_fetched_fanout_instruction_is_not_scanned() -> None:
    """A fetched reducer instruction is data: `$a` and `$$` in it stay as written."""
    io = _fanout_io(ins="use $a and $$")
    out = await run("(a:/a(x)!'i', b:/a(y)!'i')!https://ins", io, processor="/r")
    assert out.endswith("[Instruction]\nuse $a and $$")


@pytest.mark.asyncio
async def test_response_field_path_agrees_on_fanout_and_base_paths() -> None:
    """Spec B §6.2: `$a.x` traverses a response like any `$name` — on both strategies."""
    fanout = await run("(a:/j(x)!'i', b:/j(y)!'i')!'got $a.x'", _fanout_io(), processor="/r")
    base = await run("(a:/j(x)!'i', c:'plain')!'got $a.x'", _fanout_io())
    assert fanout.endswith("[Instruction]\ngot X1")
    assert base.startswith("got X1")


@pytest.mark.asyncio
async def test_fetched_call_intent_reaches_handler_unchanged() -> None:
    """A4: a fetched call intent is data — `$o` in it is not interpolated."""
    scope = Context(bindings={"o": "BOUND"}, parent=None)
    io = StaticIOLayer(
        fetch_map={"https://ci": "call $o"}, routes={"/echo": lambda context, intent: intent}
    )
    out = await run("/echo(x)!https://ci", ctx=ExecutionContext(io, scope=scope))
    assert out == "call $o"
