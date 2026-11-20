"""The ``expand.at_most_one=true`` package extension: form, builder and bytes (C19).

FEATURE: Router Recipe extension, contract C19 — a named ``;expand`` source bounded to zero
or one element. This module pins the form rules (parse, ``url4.src``, render) and the wire
bytes; ``test_at_most_one_runtime`` pins the execution.

STORY: as a Fusion author, I place a Router as a member whose abstention is absent, and the
written bytes parse back to exactly what I built.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from url4 import StaticIOLayer, Text, expr, render, src
from url4.core.errors import CollectionError, ErrorCode, ParseError
from url4.core.grammar import parse
from url4.core.nodes import Expression, Source, Url
from url4.core.render import RenderError
from url4.dag import run
from url4.peer._http import status_for

MARK = "expand.at_most_one=true"


def _member(text: str) -> Source:
    """The second source of a two-member panel ``(a:https://a, <text>)!'x'``."""
    node = parse(f"(a:https://a, {text})!'x'")
    assert isinstance(node, Expression)
    member = node.sources[1]
    assert isinstance(member, Source)
    return member


# --- parse: the accepted forms ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "guard"),
    [
        (f"*m:https://one;required;{MARK}", "required"),
        (f"*m:https://one;optional;{MARK}", "optional"),
        (f"m:https://one;expand;required;{MARK}", "required"),
    ],
)
def test_a_named_guarded_expansion_takes_the_mark(text: str, guard: str) -> None:
    member = _member(text)
    assert member.expand is True
    assert member.name == "m"
    assert member.annotations == ((guard, None), ("expand.at_most_one", "true"))


def test_on_an_expression_the_mark_after_the_guard_is_a_source_annotation() -> None:
    member = _member(f"*m:(https://b)!'q';required;{MARK}")
    assert isinstance(member.value, Expression)
    # INVARIANT: never read as an expression parameter.
    assert member.value.params == ()
    assert member.annotations == (("required", None), ("expand.at_most_one", "true"))


# --- parse: the refused forms --------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(f"m:https://one;required;{MARK}", id="no-expand"),
        pytest.param(f"*https://one;required;{MARK}", id="no-name"),
        pytest.param(f"*m:https://one;{MARK}", id="no-guard"),
        pytest.param(f"*m:https://one;required;optional;{MARK}", id="both-guards"),
        pytest.param("*m:https://one;required;expand.at_most_one=false", id="value-false"),
        pytest.param("*m:https://one;required;expand.at_most_one=1", id="value-1"),
        pytest.param("*m:https://one;required;expand.at_most_one", id="flag"),
        pytest.param(f"*m:https://one;required;{MARK};{MARK}", id="duplicate"),
        pytest.param(f"*m:(https://b)!'q';{MARK};required", id="expr-mark-first"),
        pytest.param(f"*m:(https://b)!'q';{MARK}", id="expr-mark-alone"),
        pytest.param(f"m:/p(https://b)!'q';{MARK};required;expand", id="call-mark-first"),
    ],
)
def test_a_broken_mark_is_refused_at_parse(text: str) -> None:
    with pytest.raises(ParseError) as caught:
        parse(f"(a:https://a, {text})!'x'")
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE


@pytest.mark.asyncio
async def test_the_text_path_refuses_the_mark_on_a_deferred_group() -> None:
    # WHY: `m=(…)!x;<mark>` is a group the DAG text path defers; it must not carry the
    # mark through as an expression parameter, so the run refuses it before any I/O.
    calls: list[str] = []

    async def process(sources: str, intent: str | None, scope: object) -> str:
        calls.append(sources)
        return "out"

    io = StaticIOLayer(fetch_map={"https://a": "A", "https://b": "B"})
    with pytest.raises(ParseError):
        await run(f"(a:https://a, m=(https://b)!'q';{MARK})!'x'", io, process=process)
    assert calls == []


# --- url4.src: the builder ---------------------------------------------------------------


def test_src_writes_the_mark_right_after_the_guard() -> None:
    member = src(Url("https://one"), name="m", required=True, expand=True, at_most_one=True)
    assert isinstance(member, Source)
    assert member.annotations == (("required", None), ("expand.at_most_one", "true"))
    panel = expr(src(Url("https://a"), name="a"), member, intent=Text("x"))
    text = render(panel)
    assert text == f"(a=https://a, *m:https://one;required;{MARK})!'x'"
    assert parse(text) == panel


def test_src_writes_the_mark_after_optional_and_after_a_weighted_expression() -> None:
    # The SDK's member slot shape: a named, weighted, guarded expression.
    member = src(
        expr(Url("https://b"), intent=Text("q")),
        name="member_3",
        weight=1.0,
        required=False,
        expand=True,
        at_most_one=True,
    )
    panel = expr(src(Url("https://a"), name="a"), member, intent=Text("x"))
    text = render(panel)
    assert text == f"(a=https://a, *member_3:1.0:(https://b)!'q';optional;{MARK})!'x'"
    assert text.count("expand.at_most_one") == 1
    assert parse(text) == panel


def test_src_accepts_the_same_mark_through_annotations() -> None:
    by_keyword = src(Url("https://one"), name="m", required=True, expand=True, at_most_one=True)
    by_annotation = src(
        Url("https://one"),
        name="m",
        required=True,
        expand=True,
        annotations=[("expand.at_most_one", "true")],
    )
    assert by_annotation == by_keyword


def test_src_without_the_mark_writes_the_bytes_it_always_wrote() -> None:
    member = src(Url("https://one"), name="m", required=True, expand=True)
    panel = expr(src(Url("https://a"), name="a"), member, intent=Text("x"))
    assert render(panel) == "(a=https://a, *m:https://one;required)!'x'"


_ONE = Url("https://one")


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda: src(_ONE, name="m", required=True, at_most_one=True), id="no-expand"),
        pytest.param(lambda: src(_ONE, required=True, expand=True, at_most_one=True), id="no-name"),
        pytest.param(lambda: src(_ONE, name="m", expand=True, at_most_one=True), id="no-guard"),
        pytest.param(
            lambda: src(
                _ONE,
                name="m",
                required=True,
                expand=True,
                at_most_one=True,
                annotations=[("optional", None)],
            ),
            id="both-guards",
        ),
        pytest.param(
            lambda: src(
                _ONE,
                name="m",
                required=True,
                expand=True,
                at_most_one=True,
                annotations=[("expand.at_most_one", "true")],
            ),
            id="duplicate",
        ),
    ],
)
def test_src_refuses_a_broken_form_of_the_keyword(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError, match="expand.at_most_one"):
        build()


@pytest.mark.parametrize(
    ("value", "annotations"),
    [
        pytest.param(
            Url("https://one"),
            [("required", None), ("expand.at_most_one", "false")],
            id="another-value",
        ),
        pytest.param(
            expr(Url("https://b"), intent=Text("q")),
            [("expand.at_most_one", "true"), ("required", None)],
            id="expr-mark-first",
        ),
    ],
)
def test_src_refuses_a_broken_mark_passed_through_annotations(
    value: Url | Expression, annotations: list[tuple[str, str | None]]
) -> None:
    with pytest.raises(ValueError, match="expand.at_most_one"):
        src(value, name="m", expand=True, annotations=annotations)


# --- render ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "member",
    [
        pytest.param(
            Source(
                value=Url("https://one"),
                name="m",
                annotations=(("required", None), ("expand.at_most_one", "true")),
            ),
            id="no-expand",
        ),
        pytest.param(
            Source(
                value=expr(Url("https://b"), intent=Text("q")),
                name="m",
                annotations=(("expand.at_most_one", "true"), ("required", None)),
                expand=True,
            ),
            id="expr-mark-first",
        ),
    ],
)
def test_render_refuses_a_broken_mark(member: Source) -> None:
    with pytest.raises(RenderError):
        render(expr(src(Url("https://a"), name="a"), member, intent=Text("x")))


# --- the failure code -------------------------------------------------------------------------


def test_too_many_elements_is_a_permanent_422() -> None:
    assert ErrorCode.EXPANSION_TOO_MANY == "x.expansion_too_many"
    exc = CollectionError("two elements", code=ErrorCode.EXPANSION_TOO_MANY)
    assert exc.permanent is True
    assert status_for(exc) == 422
