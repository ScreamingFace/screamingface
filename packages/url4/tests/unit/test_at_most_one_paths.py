"""Every reader of url4 refuses the at-most-one forms the parser refuses (C19).

FEATURE: Router Recipe extension, contract C19. ``test_at_most_one_form`` pins the parser,
``url4.src`` and the renderer. This module pins the other readers: the inner tail of a
reduce over iteration, the canonical call form, the HTTP query splitter and the direct tree
path (``run(tree)``), so none of them accepts what another refuses.

STORY: as a Fusion author, a mark I wrote wrong fails the same way whether I send text, a
canonical call, an HTTP request or a tree built in code.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from url4 import StaticIOLayer, Text, build, expr, render, src
from url4.core.context import Context
from url4.core.errors import ErrorCode, ParseError
from url4.core.grammar import parse
from url4.core.nodes import (
    Binding,
    Expression,
    Iteration,
    Node,
    RelExpr,
    RelUrl,
    RemoteExpr,
    Source,
    Url,
)
from url4.core.render import RenderError
from url4.dag import compile_expression, run
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes
from url4.peer._http import status_for
from url4.wire.subrequest import extract_expression_params

KEY = "expand.at_most_one"
MARK = f"{KEY}=true"
IMG = "https://img.example/a.png"
PNG = b"\x89PNG\r\n\x1a\n-c19"
BLOB = f"/blob/sha256/{hashlib.sha256(PNG).hexdigest()}"
_BODIES: dict[str, str | bytes] = {
    "https://a": "A",
    "https://one": '["x"]',
    "https://two": '["x","y"]',
    "https://list": '["1"]',
    IMG: PNG,
    BLOB: PNG,
}


class _LoggedIO(StaticIOLayer):
    """A static IO layer that records every fetch target, text and bytes alike."""

    def __init__(self) -> None:
        super().__init__(fetch_map=dict(_BODIES), media_types={IMG: "image/png", BLOB: "image/png"})
        self.fetches: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        return await super().fetch(target, relative=relative)

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.fetches.append(request.target)
        return await super().fetch_bytes(request)


class _Calls:
    """A process double: records each call's packed sources and intent."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def __call__(self, sources: str, intent: str | None, scope: Context) -> str:
        self.calls.append((sources, intent))
        return f"{intent}:{sources}"


async def _refused(target: str | Node) -> None:
    """Run ``target`` and assert a ``malformed_source`` refusal with no fetch and no call."""
    io, process = _LoggedIO(), _Calls()
    with pytest.raises(ParseError) as caught:
        await run(target, io, process=process)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE
    assert io.fetches == []
    assert process.calls == []


# --- reduce over iteration: the inner tail ----------------------------------------------------

_INNER_TAILS = [
    pytest.param(f"(https://list*('x $item')!'p';{MARK})!'r'", id="inner-tail"),
    pytest.param(
        f"(https://list*('x $item')!'p';iteration.on_error=skip;{MARK})!'r'",
        id="inner-tail-after-directive",
    ),
]


@pytest.mark.parametrize("text", _INNER_TAILS)
def test_build_refuses_the_mark_in_the_inner_tail_of_a_reduce_over_iteration(text: str) -> None:
    # INVARIANT: an Iteration has no params field, so the decoder must refuse the mark here
    # rather than drop it without a word.
    with pytest.raises(ParseError) as caught:
        build(text)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE


@pytest.mark.parametrize("text", _INNER_TAILS)
@pytest.mark.asyncio
async def test_the_text_path_refuses_the_inner_tail_mark_with_no_call(text: str) -> None:
    await _refused(text)


def test_an_inner_tail_directive_alone_still_builds_a_reduce_over_iteration() -> None:
    node = build("(https://list*('x $item')!'p';iteration.on_error=skip)!'r'")
    assert isinstance(node, Iteration)
    assert node.directives.on_error == "skip"


def test_a_marked_group_source_that_looks_like_the_inner_shape_still_builds() -> None:
    # WHY: the refusal sits on the collection branch only; a marked expression-valued source
    # carries the mark as its own annotation and must keep building.
    node = build(f"(*m:(https://a)!'q';required;{MARK})!'r'")
    assert isinstance(node, Expression)


# --- the canonical call form and the HTTP query ----------------------------------------------

_CANONICAL = [
    pytest.param(f"(/p?{MARK}&q=(https://a)!'i')!'x'", id="relative"),
    pytest.param(f"(url4://h/p?{MARK}&q=(https://a)!'i')!'x'", id="remote"),
    pytest.param(f"(/p?tone=formal&{MARK}&q=(https://a)!'i')!'x'", id="relative-after-a-param"),
    pytest.param(f"(/p?{KEY}&q=(https://a)!'i')!'x'", id="relative-flag"),
]


@pytest.mark.parametrize("text", _CANONICAL)
def test_parse_refuses_the_mark_in_the_canonical_call_form(text: str) -> None:
    # INVARIANT: `/p?k=v&q=(a)!'i'` writes the same params field as `/p(a)!'i';k=v`, which
    # already refuses the mark; the two spellings must agree.
    with pytest.raises(ParseError) as caught:
        parse(text)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE


def test_the_canonical_call_form_keeps_its_other_params() -> None:
    node = parse("(/p?tone=formal&q=(https://a)!'i')!'x'")
    assert isinstance(node, Expression)
    call = node.sources[0]
    assert isinstance(call, RelExpr)
    assert call.params == (("tone", "formal"),)


def _calls_with_the_mark() -> list[object]:
    params = ((KEY, "true"),)
    return [
        pytest.param(RelExpr("/p", "https://a", Text("i"), params=params), id="relative"),
        pytest.param(
            RemoteExpr(
                authority="h", path="/p", context="https://a", intent=Text("i"), params=params
            ),
            id="remote",
        ),
    ]


@pytest.mark.parametrize("check", [True, False])
@pytest.mark.parametrize("node", _calls_with_the_mark())
def test_render_refuses_the_mark_as_a_call_query_param(node: Node, check: bool) -> None:
    with pytest.raises(RenderError):
        render(node, check=check)


@pytest.mark.parametrize(
    "query",
    [
        pytest.param(f"{MARK}&q=(a)!'i'", id="valued"),
        pytest.param(f"{KEY}&q=(a)!'i'", id="flag"),
        pytest.param(f"tone=formal&{MARK}&q=(a)!'i'", id="after-a-param"),
    ],
)
def test_the_http_query_splitter_refuses_the_mark(query: str) -> None:
    # INVARIANT (OME-507): a node refuses over HTTP what it refuses in expression text, with
    # the status any other invalid query param gets.
    with pytest.raises(ParseError) as caught:
        extract_expression_params(query)
    with pytest.raises(ParseError) as invalid:
        extract_expression_params("bad!key=1&q=(a)!'i'")
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE
    assert status_for(caught.value) == status_for(invalid.value) == 400


def test_the_http_query_splitter_keeps_its_other_params() -> None:
    assert extract_expression_params("tone=formal&q=(a)!'i'") == ({"tone": "formal"}, "(a)!'i'")


# --- the direct tree path ----------------------------------------------------------------------


def _a() -> Node:
    return src(Url("https://a"), name="a")


_MALFORMED_MEMBERS = {
    "mark-false": Source(
        Url("https://two"), name="m", annotations=(("required", None), (KEY, "false")), expand=True
    ),
    "valued-guard": Source(
        Url("https://two"),
        name="m",
        annotations=(("optional", "false"), (KEY, "true")),
        expand=True,
    ),
    "no-expand": Source(
        Url("https://two"), name="m", annotations=(("required", None), (KEY, "true"))
    ),
    "unnamed": Source(
        Url("https://two"), annotations=(("required", None), (KEY, "true")), expand=True
    ),
    # WHY: the one element keeps the source's name, so the name must be one the text form and
    # url4.src accept: an identifier, never empty, never the reserved `src` (§4.3).
    **{
        f"{label}-name": Source(
            Url("https://one"),
            name=name,
            annotations=(("required", None), (KEY, "true")),
            expand=True,
        )
        for label, name in (("empty", ""), ("reserved", "src"), ("non-identifier", "bad-name"))
    },
}


@pytest.mark.parametrize(
    "intent", [pytest.param(Text("go"), id="panel"), pytest.param("/combine", id="code")]
)
@pytest.mark.parametrize("member", list(_MALFORMED_MEMBERS.values()), ids=list(_MALFORMED_MEMBERS))
@pytest.mark.asyncio
async def test_the_tree_path_refuses_a_malformed_marked_source(
    member: Source, intent: Node | str
) -> None:
    # INVARIANT: run(tree) refuses the C19 forms run(text) refuses. Before, `=false` ran as `true`,
    # `;optional=false` swallowed the two-plus failure and a mark without `;expand` was ignored.
    await _refused(expr(_a(), member, intent=intent))


@pytest.mark.parametrize("member", list(_MALFORMED_MEMBERS.values()), ids=list(_MALFORMED_MEMBERS))
def test_compile_refuses_a_malformed_marked_source(member: Source) -> None:
    with pytest.raises(ParseError):
        compile_expression(expr(_a(), member, intent=Text("go")))


def _trees_with_the_mark_as_a_param() -> list[object]:
    params = [(KEY, "true")]
    top = expr(_a(), intent=Text("go"), params=params)
    rel = RelExpr("/p", "https://a", Text("i"), params=((KEY, "true"),))
    remote = RemoteExpr(
        authority="h", path="/p", context="https://a", intent=Text("i"), params=((KEY, "true"),)
    )
    return [
        pytest.param(top, id="expression"),
        pytest.param(expr(src(top, name="x", required=True), intent=Text("outer")), id="nested"),
        pytest.param(expr(src(rel, name="r"), intent=Text("go")), id="relative-call"),
        pytest.param(expr(src(remote, name="r"), intent=Text("go")), id="remote-call"),
    ]


@pytest.mark.parametrize("tree", _trees_with_the_mark_as_a_param())
@pytest.mark.asyncio
async def test_the_tree_path_refuses_the_mark_as_an_expression_param(tree: Node) -> None:
    await _refused(tree)


@pytest.mark.asyncio
async def test_a_well_formed_marked_tree_still_runs() -> None:
    io, process = _LoggedIO(), _Calls()
    member = src(Url("https://one"), name="m", expand=True, at_most_one=True, required=True)
    assert await run(expr(_a(), member, intent=Text("go")), io, process=process) == "go:a: A\nm: x"
    assert process.calls == [("a: A\nm: x", "go")]


@pytest.mark.asyncio
async def test_an_unmarked_tree_keeps_its_valued_guard() -> None:
    # WHY: the form check reads only a marked source; an unmarked one keeps the base language.
    io, process = _LoggedIO(), _Calls()
    member = Source(Url("https://missing"), name="m", annotations=(("optional", "false"),))
    assert await run(expr(_a(), member, intent=Text("go")), io, process=process) == "go:a: A"


# --- the tree path before any run-start I/O ----------------------------------------------------


def _files() -> tuple[Node, ...]:
    """A blob ref and an image opt-in: both fetched at run start, before any member runs."""
    return (
        Binding(name="b", value=RelUrl(BLOB), kind=":"),
        Source(Url(IMG), name="img", annotations=(("accept", "image/png"),)),
    )


def _broken_trees_beside_files() -> list[object]:
    member = _MALFORMED_MEMBERS["mark-false"]
    return [
        pytest.param(
            Expression(sources=(*_files(), member), intent=Text("go")), id="malformed-member"
        ),
        pytest.param(
            Expression(sources=_files(), intent=Text("go"), params=((KEY, "true"),)),
            id="mark-as-param",
        ),
    ]


@pytest.mark.parametrize("tree", _broken_trees_beside_files())
@pytest.mark.asyncio
async def test_the_tree_path_refuses_before_any_file_fetch(tree: Node) -> None:
    # INVARIANT: run(tree) checks the C19 form before the run-start file phase, as run(text)
    # does by parsing; a blob ref or an image opt-in is never fetched for a refused tree.
    await _refused(tree)


@pytest.mark.asyncio
async def test_the_same_text_beside_files_is_refused_with_no_fetch() -> None:
    await _refused(
        f"(b:{BLOB}, img:{IMG};accept=image/png, *m:https://two;required;{KEY}=false)!'go'"
    )


@pytest.mark.asyncio
async def test_a_well_formed_marked_tree_beside_files_fetches_them() -> None:
    # WHY: the control that makes the refusals above mean something: this double does record
    # the run-start fetches when they happen.
    io, process = _LoggedIO(), _Calls()
    member = src(Url("https://one"), name="m", expand=True, at_most_one=True, required=True)
    await run(Expression(sources=(*_files(), member), intent=Text("go")), io, process=process)
    assert {BLOB, IMG} <= set(io.fetches)
    assert len(process.calls) == 1


# --- an inline collection ----------------------------------------------------------------------


def _marked_inline_collection() -> Iteration:
    return Iteration(
        collection=Expression(
            sources=(Source(value=Text("a")), Source(value=Text("b"))), params=((KEY, "true"),)
        ),
        body="$item",
        intent="'ok'",
    )


def _inline_collection_trees() -> list[object]:
    inner = _marked_inline_collection()
    nested = Expression(sources=(Source(inner, name="x", annotations=(("required", None),)),))
    return [
        pytest.param(inner, id="iteration"),
        pytest.param(replace(nested, intent=Text("outer")), id="nested"),
    ]


@pytest.mark.parametrize("tree", _inline_collection_trees())
def test_compile_refuses_the_mark_on_an_inline_collection(tree: Node) -> None:
    # INVARIANT: an inline collection is lowered as a list, not through the expression
    # lowering, so the tree's params check must not depend on which lowering reads them.
    with pytest.raises(ParseError) as caught:
        compile_expression(tree)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE


@pytest.mark.parametrize("tree", _inline_collection_trees())
@pytest.mark.asyncio
async def test_run_refuses_the_mark_on_an_inline_collection(tree: Node) -> None:
    await _refused(tree)


@pytest.mark.asyncio
async def test_an_unmarked_inline_collection_still_iterates() -> None:
    marked = _marked_inline_collection()
    assert isinstance(marked.collection, Expression)
    tree = replace(marked, collection=replace(marked.collection, params=()))
    io, process = _LoggedIO(), _Calls()
    assert await run(tree, io, process=process) == '["ok:a", "ok:b"]'
