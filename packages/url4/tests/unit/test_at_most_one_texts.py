"""A C19 form in url4 that a run parses later is refused before any fetch or call.

FEATURE: Router Recipe extension, contract C19. The parser keeps some url4 as raw text, and a
run parses it later: an iteration's body and intent once per row, its reducer at reduce time, a
relative call's context when the call is lowered (a source list, else prose) and, on the text
path, a deferred group when it runs. A malformed mark there once surfaced after the collection
fetch and the per-row calls, or never: a skipped row, a prose context shipped outbound.
``test_at_most_one_paths`` pins the tree nodes; this module pins those texts, and that every
other parse error in them keeps its base behavior.

STORY: as a Fusion author, a mark I wrote wrong inside an iteration, a nested group or a call's
context fails at once, before anything runs, never as a quietly skipped row.
"""

from __future__ import annotations

import pytest

from url4 import CodeCall, StaticIOLayer, Text, Url4Node, expr, src
from url4.core.at_most_one import AtMostOneFormError
from url4.core.context import Context
from url4.core.errors import ErrorCode, ParseError
from url4.core.nodes import Iteration, IterationDirectives, Node, OnErrorPolicy, RelExpr, Url
from url4.core.parser import build
from url4.dag import compile_expression, run
from url4.peer._http import status_for

KEY = "expand.at_most_one"
BAD = f"*m:https://two;required;{KEY}=false"
GOOD = f"*m:https://one;required;{KEY}=true"
OTHER = "https://two;bogus key=1"  # breaks the annotation-key rule, not C19
_BODIES = {
    "https://a": "A",
    "https://one": '["x"]',
    "https://two": '["x","y"]',
    "https://list": '["1","2"]',
}


class _LoggedIO(StaticIOLayer):
    """A static IO layer that records every fetch; a relative call answers ``REMOTE``."""

    def __init__(self) -> None:
        super().__init__(fetch_map=dict(_BODIES))
        self.fetches: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        return "REMOTE" if relative else await super().fetch(target, relative=relative)


class _Calls:
    """A process double: records each call's packed sources and intent."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def __call__(self, sources: str, intent: str | None, scope: Context) -> str:
        self.calls.append((sources, intent))
        return "done"


async def _ran(target: str | Node) -> tuple[str, _LoggedIO, _Calls]:
    io, process = _LoggedIO(), _Calls()
    return await run(target, io, process=process), io, process


async def _refused(target: str | Node) -> None:
    """Run ``target`` and assert a C19 ``malformed_source`` refusal with no fetch and no call."""
    io, process = _LoggedIO(), _Calls()
    with pytest.raises(AtMostOneFormError) as caught:
        await run(target, io, process=process)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE
    assert io.fetches == []
    assert process.calls == []


_TEXTS = {
    "row-skipped": f"https://list*({BAD})!'row';iteration.on_error=skip",
    "row-collected": f"https://list*({BAD})!'row';iteration.on_error=collect",
    "row-unnamed": f"https://list*(*https://two;required;{KEY}=true)!'row';iteration.on_error=skip",
    "row-in-a-reduce": f"(https://list*({BAD})!'per')!'r'",
    "row-group": f"https://list*(n=({BAD})!'inner')!'row'",
    "row-call-context": f"https://list*(/p({BAD})!'i')!'row'",
    "deferred-named-group": f"(a:https://a, n=({BAD})!'nested')!'outer'",
    "deferred-bare-group": f"(a:https://a, ({BAD})!'nested')!'outer'",
    "call-context": f"/p({BAD})!'i'",
    "call-context-second-segment": f"/p(a:https://a, {BAD})!'i'",
    "call-context-in-a-group": f"(a:https://a, c=/p({BAD})!'i')!'outer'",
}


@pytest.mark.parametrize("text", list(_TEXTS.values()), ids=list(_TEXTS))
@pytest.mark.asyncio
async def test_a_text_the_run_parses_later_is_refused_before_any_fetch(text: str) -> None:
    # INVARIANT: run(text) refuses a C19 form in a row, a reducer, a deferred group or a call's
    # context before any fetch or call. Before, a skipped row swallowed it, a context shipped it
    # outbound as prose, and a deferred group fetched its siblings first.
    await _refused(text)


@pytest.mark.parametrize("text", list(_TEXTS.values()), ids=list(_TEXTS))
def test_compile_refuses_a_c19_form_in_a_text_the_run_parses_later(text: str) -> None:
    # WHY compile too: the eager parser already refuses the deferred group; compile accepted it.
    with pytest.raises(ParseError) as caught:
        compile_expression(text)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE


_MARK_PARAM = f"{KEY}=true"
_TREES = {
    "body": Iteration(Url("https://list"), BAD, "'row'"),
    "body-no-intent": Iteration(Url("https://list"), BAD),
    "intent": Iteration(Url("https://list"), "'row'", f"'per';{_MARK_PARAM}"),
    "reducer": Iteration(Url("https://list"), "'row'", "'per'", f"/r(ctx)!'reduce';{_MARK_PARAM}"),
    "reducer-source": Iteration(Url("https://list"), "'row'", "'per'", f"({BAD})!'reduce'"),
    "call-context": expr(src(RelExpr("/p", BAD, Text("i")), name="c"), intent=Text("go")),
}


@pytest.mark.parametrize("tree", list(_TREES.values()), ids=list(_TREES))
@pytest.mark.asyncio
async def test_a_tree_s_raw_text_is_refused_before_any_fetch(tree: Node) -> None:
    # INVARIANT: run(tree) reads an iteration's body, intent and reducer and a relative call's
    # context as the run will, before any fetch. Before, the reducer failed after the collection
    # fetch and a call per row, and a reserved intent param became a collected row error.
    await _refused(tree)


@pytest.mark.parametrize("tree", list(_TREES.values()), ids=list(_TREES))
def test_compile_refuses_a_c19_form_in_a_tree_s_raw_text(tree: Node) -> None:
    with pytest.raises(ParseError) as caught:
        compile_expression(tree)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE


@pytest.mark.asyncio
async def test_a_code_reducer_over_skipped_rows_is_never_called() -> None:
    # WHY: with every row skipped, the code reducer once ran on an empty rows input: a broken
    # mark turned into a successful code call.
    io, code_calls = _LoggedIO(), list[CodeCall]()
    node = Url4Node("t", outbound=io)

    @node.code("/combine")
    def combine(call: CodeCall) -> str:
        code_calls.append(call)
        return "COMBINED"

    with pytest.raises(ParseError) as caught:
        await node._run_text(f"(https://list*({BAD})!'per';iteration.on_error=skip)!/combine")
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE
    assert (io.fetches, code_calls) == ([], [])


def test_a_row_s_call_context_refuses_a_c19_form_instead_of_prose() -> None:
    # INVARIANT: a C19 error is never prose. A row is compiled as an engine fragment, past the
    # entry check, so the lowering itself must not read the broken context as prose.
    with pytest.raises(ParseError) as caught:
        compile_expression(f"(/p({BAD})!'i')", bare_root_ok=True)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE


_PROCESSORS = {
    "row": f"(https://list*({BAD})!'row';iteration.on_error=skip)!'r'",
    "call-context": f"(/p({BAD})!'i')!'r'",
}


@pytest.mark.parametrize("processor", list(_PROCESSORS.values()), ids=list(_PROCESSORS))
@pytest.mark.asyncio
async def test_a_form3_processor_with_a_c19_form_is_refused_before_any_io(processor: str) -> None:
    # INVARIANT: a Form-3 processor is url4 its user wrote; the run start reads it as it reads
    # the target. Before, its C19 error was swallowed at run start and its spawn skipped the
    # check: both relative calls, the collection fetch and the reduce ran first.
    io, process = _LoggedIO(), _Calls()
    with pytest.raises(AtMostOneFormError):
        await run("(/a('x')!'i', /b('y')!'j')!'go'", io, processor=processor, process=process)
    assert (io.fetches, process.calls) == ([], [])


_MASKED = {
    "other-first": (f"{OTHER}, {BAD}", "'row'"),
    "c19-first": (f"{BAD}, {OTHER}", "'row'"),
    "nested-other-first": (f"n=({OTHER}, {BAD})!'inner'", "'row'"),
    "nested-c19-first": (f"n=({BAD}, {OTHER})!'inner'", "'row'"),
    "other-before-an-intent-call": (OTHER, f"/p({BAD})!'i'"),
}
_ON_ERROR: tuple[OnErrorPolicy, ...] = ("skip", "collect")


@pytest.mark.parametrize("on_error", _ON_ERROR)
@pytest.mark.parametrize("row", list(_MASKED.values()), ids=list(_MASKED))
@pytest.mark.asyncio
async def test_another_error_in_a_row_never_hides_a_c19_error(
    row: tuple[str, str], on_error: OnErrorPolicy
) -> None:
    # INVARIANT: among one group's members a C19 error outranks any other, at every depth, and
    # a row's body and intent are read apart. Before, the first error stopped the parse, the
    # row failed on it alone and was skipped or collected: the malformed mark vanished.
    body, intent = row
    text = f"https://list*({body})!{intent};iteration.on_error={on_error}"
    await _refused(text)
    with pytest.raises(AtMostOneFormError):
        compile_expression(text)


def _row(body: str, intent: str, on_error: OnErrorPolicy) -> Iteration:
    directives = IterationDirectives(on_error=on_error)
    return Iteration(Url("https://list"), body, intent, directives=directives)


_MASKED_TREES = {**_MASKED, "other-in-the-intent": (BAD, "'row';bogus key=1")}


@pytest.mark.parametrize("on_error", _ON_ERROR)
@pytest.mark.parametrize("row", list(_MASKED_TREES.values()), ids=list(_MASKED_TREES))
@pytest.mark.asyncio
async def test_another_error_in_a_tree_s_row_never_hides_a_c19_error(
    row: tuple[str, str], on_error: OnErrorPolicy
) -> None:
    # WHY the intent case: a row's intent params are read before its body, so an intent that
    # breaks another rule once hid the body's C19 error; body and intent are read apart.
    tree = _row(*row, on_error)
    await _refused(tree)
    with pytest.raises(AtMostOneFormError):
        compile_expression(tree)


_DEPTH = 300  # WHY: past the eager parser's reach (about 140 nested groups), not the compiler's


def _deep(bottom: str) -> str:
    text = bottom
    for _ in range(_DEPTH):
        text = f"(/b(y)!'w', {text})!'h'"
    return text


_UNMARKED = _deep("/b(z)!'k'")
_MARKED = _deep(f"n=({GOOD})!'x'")
_IN_A_RUN = "(/a(x)!'q', {})!'m'"
_IN_A_ROW = f"https://list*({OTHER}, {{}})!'row';iteration.on_error=skip"


@pytest.mark.parametrize("shape", [_IN_A_RUN, _IN_A_ROW], ids=["in-a-run", "in-a-row"])
@pytest.mark.asyncio
async def test_a_mark_too_deep_to_check_is_refused_before_any_fetch(shape: str) -> None:
    # INVARIANT (FAIL CLOSED): a text too deep for the eager parser cannot be checked, so one
    # that names the mark is refused, a well-formed mark included; one that does not keeps its
    # base behavior (below). The remote-call precheck reads such a text the same way. In a row
    # the deep member comes after one that breaks another rule: read only to find a C19 error.
    text = shape.format(_MARKED)
    await _refused(text)
    with pytest.raises(AtMostOneFormError, match="nested too deeply"):
        compile_expression(text)


@pytest.mark.parametrize("shape", [_IN_A_RUN, _IN_A_ROW], ids=["in-a-run", "in-a-row"])
def test_a_text_too_deep_for_the_eager_parser_still_compiles(shape: str) -> None:
    # WHY: the compiler reads a deep group lazily; the entry check once failed such a text with
    # a RecursionError although it names no mark.
    compile_expression(shape.format(_UNMARKED))


# --- controls: every other parse error keeps its base behavior --------------------------------


@pytest.mark.asyncio
async def test_a_row_that_fails_on_another_rule_is_still_skipped() -> None:
    # WHY: `bogus key` breaks the annotation-key rule, not C19; the row still fails alone.
    text = "https://list*(https://two;bogus key=1)!'row';iteration.on_error=skip"
    result, io, process = await _ran(text)
    assert result == "[]"
    assert io.fetches == ["https://list"]
    assert process.calls == []


def test_without_a_c19_error_a_group_still_reports_its_first_error() -> None:
    # WHY: the members after a failed one are read only to find a C19 error; without one the
    # first error is raised, as before.
    with pytest.raises(ParseError, match="bogus key"):
        build(f"({OTHER}, https://one;other key=1)!'x'")


@pytest.mark.asyncio
async def test_a_tree_s_row_that_fails_on_another_rule_alone_is_still_skipped() -> None:
    result, io, process = await _ran(_row(f"{OTHER}, https://one", "'row';bogus key=1", "skip"))
    assert (result, io.fetches, process.calls) == ("[]", ["https://list"], [])


@pytest.mark.parametrize(
    "context",
    [
        pytest.param(f"run: 1, {BAD}", id="prose-first"),
        pytest.param(f"{BAD}, run: 1", id="prose-last"),
        pytest.param(f"'{BAD}'", id="quoted"),
    ],
)
@pytest.mark.asyncio
async def test_a_prose_or_quoted_context_still_ships_verbatim(context: str) -> None:
    # WHY: a context with a segment that is not a source is prose, and a quoted text is data; a
    # mark written in either is data too, whatever the order of the segments.
    result, io, process = await _ran(f"/p({context})!'i'")
    assert result == "REMOTE"
    assert len(io.fetches) == 1
    assert io.fetches[0].startswith("/p?q=(")
    assert f"{KEY}=false" in io.fetches[0]
    assert process.calls == []


def test_a_prose_row_context_still_ships_verbatim() -> None:
    compile_expression(f"(/p(run: 1, {BAD})!'i')", bare_root_ok=True)


@pytest.mark.asyncio
async def test_a_well_formed_mark_still_runs_in_every_raw_text() -> None:
    row, _, row_process = await _ran(f"https://list*(a:https://a, {GOOD})!'row'")
    assert row == '["done", "done"]'
    assert row_process.calls == [("a: A\nm: x", "row"), ("a: A\nm: x", "row")]
    group, _, group_process = await _ran(f"(a:https://a, n=({GOOD})!'nested')!'outer'")
    assert group == "done"
    assert group_process.calls == [("m: x", "nested"), ("a: A\nn: done", "outer")]
    call, call_io, _ = await _ran(f"/p(a:https://a, {GOOD})!'i'")
    assert call == "REMOTE"
    assert call_io.fetches == ["https://a", "https://one", "/p?q=(a:%20A%0Am:%20x)!%27i%27"]


# --- ninth review: a tree reducer's chain, a deep processor -------------------------------------

_REDUCERS = {
    "group": f"('a')!'agg';{_MARK_PARAM}",
    "relative": f"/r(x)!'agg';{_MARK_PARAM}",
    "prompt": f"'agg';{_MARK_PARAM}",
}


@pytest.mark.parametrize("reducer", list(_REDUCERS.values()), ids=list(_REDUCERS))
@pytest.mark.asyncio
async def test_a_tree_reducer_s_chain_refuses_the_mark_before_any_fetch(reducer: str) -> None:
    # INVARIANT: the text path splits a reducer's `;` params off and refuses the mark there,
    # whatever its source side holds (`test_at_most_one_form`); a tree's reducer reads the same.
    # Before, the group reducer failed on its source side alone, after the fetch and the rows.
    tree = Iteration(collection=Url("https://list"), body="$item", intent="'row'", reducer=reducer)
    await _refused(tree)
    with pytest.raises(AtMostOneFormError):
        compile_expression(tree)


@pytest.mark.asyncio
async def test_a_mark_too_deep_to_check_in_a_processor_is_refused_before_any_io() -> None:
    # WHY: the run start built a Form-3 processor before its C19 check, so one too deep for the
    # eager parser escaped as a RecursionError, an HTTP 500, where the run text gets this 400.
    io, process = _LoggedIO(), _Calls()
    with pytest.raises(AtMostOneFormError, match="nested too deeply") as caught:
        await run("('x')!'y'", io, processor=_MARKED, process=process)
    assert status_for(caught.value) == 400
    assert (io.fetches, process.calls) == ([], [])
