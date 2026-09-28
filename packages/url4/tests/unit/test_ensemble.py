"""Ensemble strategies + collection parsing."""

from __future__ import annotations

import json

import pytest
from conftest import RecordingIOLayer

from url4.core.context import Context
from url4.core.errors import CollectionError, ResolutionError, ScopeError
from url4.dag import ExecutionContext, run
from url4.dag.semantics.collection import parse_collection
from url4.dag.semantics.ensemble import (
    FanoutResponse,
    substitute_env_vars,
    substitute_item,
    substitute_response_vars,
)
from url4.io.static import StaticIOLayer
from url4.wire.subrequest import decode_subrequest


@pytest.mark.asyncio
async def test_fanout_reduce_builds_weighted_reducer_input() -> None:
    io = RecordingIOLayer()
    expr = "(claude:0.6:/claude(x)!answer, llama:0.4:/llama(x)!answer)!merge $claude and $llama"
    # The recorder declares no routes, so the processor is explicit (the core no
    # longer hardcodes /claude).
    await run(expr, io, processor="/claude")

    # Two relative-expression fetches in parallel, then the reducer fetch via the
    # explicit processor (/claude) — all encoded as /path?q=… localhost fetches.
    paths = [target.split("?q=")[0] for target in io.fetches]
    assert paths == ["/claude", "/llama", "/claude"]
    # The reducer input is wire-escaped into the URL; decode it back to assert on
    # the human-readable content the reducer route actually receives.
    _, reducer_input = decode_subrequest(io.fetches[-1].split("?q=", 1)[1])
    assert "claude (weight=0.6):" in reducer_input
    assert "llama (weight=0.4):" in reducer_input
    assert "[Instruction]" in reducer_input


@pytest.mark.asyncio
async def test_broadcast_applies_intent_per_source() -> None:
    # Spec §6.1.4 — a JSON collection of per-source results, 1-based positions.
    io = StaticIOLayer(fetch_map={"https://a": "A", "https://b": "B"})
    result = await run("(https://a, https://b)!*tag", io)
    assert json.loads(result) == [
        {"source_position": 1, "source_name": None, "result": "tag\n\nA"},
        {"source_position": 2, "source_name": None, "result": "tag\n\nB"},
    ]


@pytest.mark.asyncio
async def test_collection_iteration_with_item_field() -> None:
    rows = json.dumps([{"q": "2+2"}, {"q": "3+3"}])
    io = StaticIOLayer(
        fetch_map={"https://data": rows},
        routes={"/solve": lambda context, intent: f"Q={context}"},
    )
    result = await run("https://data*(r:0:/solve($item.q)!go)!'$r'", io)
    assert json.loads(result) == ["Q=2+2", "Q=3+3"]


@pytest.mark.asyncio
async def test_collection_iteration_missing_field_raises_in_strict_mode() -> None:
    # Spec §5.3.4.1 — RDS mode MUST fail; iteration.on_error=fail surfaces it.
    rows = json.dumps([{"other": "x"}])
    io = StaticIOLayer(fetch_map={"https://data": rows}, routes={"/solve": lambda c, i: c})
    with pytest.raises(ScopeError):
        await run(
            "https://data*(r=/solve($item.q)!go)!'$r';iteration.on_error=fail",
            io,
            strict_fields=True,
        )


@pytest.mark.asyncio
async def test_collection_on_error_collect() -> None:
    # collect is the DEFAULT policy (spec §5.3.6); strict fields make the bad
    # row a real failure for it to capture.
    rows = json.dumps([{"q": "ok"}, {"other": "bad"}])
    io = StaticIOLayer(
        fetch_map={"https://data": rows},
        routes={"/solve": lambda context, intent: f"OK:{context}"},
    )
    ctx = ExecutionContext(io, strict_fields=True)
    result = await run("https://data*(r:0:/solve($item.q)!go)!'$r'", ctx=ctx)
    assert "OK:ok" in result
    assert ctx.collected_errors == 1
    assert '"error"' in result


@pytest.mark.asyncio
async def test_empty_collection_resolves_to_empty_array() -> None:
    # Spec §5.3.9 — an empty collection is a success with zero evaluations.
    io = StaticIOLayer(fetch_map={"https://data": "[]"})
    assert await run("https://data*(r:0:/solve($item.q)!go)!'$r'", io) == "[]"


@pytest.mark.asyncio
async def test_star_prefix_expands_collection_source() -> None:
    # Spec §5.3.12 — source-initial `*` is the expansion prefix: the source
    # resolves to a collection whose elements become independent sources.
    io = StaticIOLayer(fetch_map={"https://data": '["A", "B"]'})
    result = await run("*https://data", io)
    assert result == "A\nB"


@pytest.mark.asyncio
async def test_expansion_of_non_iterable_fails() -> None:
    # Spec §5.3.12.4 — a scalar expansion source is expansion_not_iterable.
    io = StaticIOLayer(fetch_map={"https://data": "one scalar"})
    with pytest.raises(CollectionError) as exc_info:
        await run("*https://data", io)
    assert exc_info.value.code == "expansion_not_iterable"


def test_parse_collection_json_array() -> None:
    assert parse_collection('["a", "b"]') == ["a", "b"]


def test_parse_collection_json_objects() -> None:
    assert parse_collection('[{"k": 1}]') == ['{"k": 1}']


def test_parse_collection_jsonl() -> None:
    assert parse_collection('{"a": 1}\n{"a": 2}') == ['{"a": 1}', '{"a": 2}']


def test_parse_collection_csv() -> None:
    assert parse_collection("name,age\nalice,30\nbob,25") == [
        '{"name": "alice", "age": "30"}',
        '{"name": "bob", "age": "25"}',
    ]


def test_parse_collection_empty() -> None:
    assert parse_collection("   ") == []


def test_parse_collection_html_raises() -> None:
    with pytest.raises(CollectionError):
        parse_collection("<!DOCTYPE html><html><body>not data</body></html>")


def test_parse_collection_plain_lines_with_commas_not_csv() -> None:
    # Ragged prose that merely contains commas must stay one item per line.
    body = "What is 2, 3, or 4?\nName a color, please"
    assert parse_collection(body) == ["What is 2, 3, or 4?", "Name a color, please"]


def test_parse_collection_even_column_prose_not_csv() -> None:
    # Two prose lines that each split into the SAME number of comma cells would
    # pass a rectangular-shape check; the header must still be recognized as prose.
    body = "What is your name, please?\nPick a color, any color"
    assert parse_collection(body) == ["What is your name, please?", "Pick a color, any color"]


def test_substitute_response_vars_prefix_name_not_corrupted() -> None:
    # A source name that is a prefix of another must not corrupt the longer $ref.
    entries = [FanoutResponse(text="A", name="gpt"), FanoutResponse(text="B", name="gpt4")]
    assert substitute_response_vars("compare $gpt4 vs $gpt", entries) == "compare B vs A"


def test_substitute_response_vars_escapes_inside_json_blob() -> None:
    entries = [FanoutResponse(text='has "quote"', name="a")]
    assert substitute_response_vars('{"k": "$a"}', entries) == '{"k": "has \\"quote\\""}'


def test_substitute_item_leaves_longer_identifier() -> None:
    # $items is a different variable; bare $item must not eat its prefix.
    assert substitute_item("$item and $items", '{"x": 1}') == '{"x": 1} and $items'


def test_substitute_item_bare_escaped_inside_json_blob() -> None:
    # A bare $item carrying a quote, inside a {...} blob, must be JSON-escaped so
    # the blob a reducer later json.loads stays valid.
    assert substitute_item('{"text": "$item"}', 'He said "hi"') == '{"text": "He said \\"hi\\""}'


def test_substitute_item_bare_raw_outside_json_blob() -> None:
    assert substitute_item("say $item", 'He said "hi"') == 'say He said "hi"'


def test_substitute_item_nonstring_field_escaped_inside_json_blob() -> None:
    # A non-string field is rendered as its JSON text and, inside a blob, that
    # text is itself escaped for the surrounding JSON string.
    assert substitute_item('{"wrap": "$item.n"}', '{"n": {"k": "v"}}') == (
        '{"wrap": "{\\"k\\": \\"v\\"}"}'
    )
    # ...but rendered raw outside a blob.
    assert substitute_item("n=$item.n", '{"n": {"k": "v"}}') == 'n={"k": "v"}'


def test_substitute_env_vars_escapes_in_deeply_nested_blob() -> None:
    # A value landing inside a doubly-nested JSON object must still be escaped;
    # a fixed-depth regex would miss it.
    ctx = Context.root().child(x='a"b')
    assert substitute_env_vars('{"a": {"b": {"c": "$x"}}}', ctx) == '{"a": {"b": {"c": "a\\"b"}}}'


def test_substitute_env_vars_brace_inside_json_string_still_escaped() -> None:
    # BUG-2 regression: a '{' that appears INSIDE a JSON string value used to
    # inflate the brace-depth count, so the enclosing blob was never recognised
    # and the value was inserted raw — producing invalid JSON that broke a
    # reducer's later json.loads. The brace scan must ignore string-literal
    # contents, so a value landing in the string is still JSON-escaped.
    ctx = Context.root().child(x='has "quote"')
    template = '{"k": "a{b $x"}'  # valid JSON; the string value contains a literal {
    out = substitute_env_vars(template, ctx)
    assert out == '{"k": "a{b has \\"quote\\""}'
    # The property the golden string can't prove: the result stays valid JSON.
    import json as _json

    assert _json.loads(out) == {"k": 'a{b has "quote"'}


def test_substitute_env_vars_terminated_string_with_escaped_quote() -> None:
    # A '\"' inside a JSON string must not be mistaken for the string's close,
    # or a brace after it would be mis-counted.
    ctx = Context.root().child(x="v")
    template = '{"k": "a\\"{b $x"}'  # valid JSON; value string has an escaped quote then a brace
    out = substitute_env_vars(template, ctx)
    import json as _json

    assert _json.loads(out) == {"k": 'a"{b v'}


def test_substitute_env_vars_unterminated_quote_keeps_old_behavior() -> None:
    # A stray '"' in non-JSON text is NOT a string delimiter (no close), so
    # braces after it still count exactly as before the fix — no behavior change
    # for malformed input. Here the unbalanced '{' yields no blob → no escaping.
    ctx = Context.root().child(x='has "quote"')
    assert substitute_env_vars("{not closed $x", ctx) == '{not closed has "quote"'


def test_substitute_item_field_inside_json_string_with_brace() -> None:
    # BUG-2 regression for the $item path (shares _json_blob_spans): a field
    # value substituted into a JSON string that contains a '{' must stay escaped.
    out = substitute_item('{"k": "a{b $item.f"}', '{"f": "q\\"r"}')
    import json as _json

    assert _json.loads(out) == {"k": 'a{b q"r'}


@pytest.mark.asyncio
async def test_fanout_reduce_uses_first_declared_route_when_processor_unset() -> None:
    # WHY: no hardcoded default processor — an unset processor resolves to the
    # io world's FIRST declared route, mirroring `url4 serve`'s default_route.
    seen: list[str] = []

    def route(tag: str):
        def handler(context: str, intent: str) -> str:
            seen.append(tag)
            return f"{tag}:{intent}"

        return handler

    io = StaticIOLayer(routes={"/reducer": route("reducer"), "/leaf": route("leaf")})
    result = await run("(/leaf(a)!go)!'pick best'", io)
    assert seen == ["leaf", "reducer"]
    assert result.startswith("reducer:")


@pytest.mark.asyncio
async def test_fanout_reduce_explicit_processor_wins_over_declared_routes() -> None:
    seen: list[str] = []

    def route(tag: str):
        def handler(context: str, intent: str) -> str:
            seen.append(tag)
            return f"{tag}:{intent}"

        return handler

    io = StaticIOLayer(routes={"/first": route("first"), "/pick": route("pick")})
    result = await run("(/first(a)!go)!'choose'", io, processor="/pick")
    assert seen == ["first", "pick"]
    assert result.startswith("pick:")


@pytest.mark.asyncio
async def test_fanout_reduce_without_processor_or_routes_is_a_clear_error() -> None:
    # Leaves resolve via exact fetch_map entries; the io declares NO routes and
    # no processor was set — the reduce fails with an error naming the fix, not
    # a dispatch to a phantom hardcoded path.
    io = StaticIOLayer(fetch_map={"/x?q=(a)!go": "X", "/y?q=(b)!go": "Y"})
    with pytest.raises(ResolutionError, match="processor"):
        await run("(/x(a)!go, /y(b)!go)!'merge'", io)
