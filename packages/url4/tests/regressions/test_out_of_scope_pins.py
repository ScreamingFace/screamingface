"""Strict-xfail pins for audit findings this branch does not fix (regression safety net).

Each test asserts the CORRECT behaviour and is marked ``xfail(strict=True)``. The pin
records that the finding still reproduces. When a fix lands, the test XPASSes, which
fails the suite, and the marker must be removed.

Faithful or loud: where the spec allows a rejection as the correct fix, the test body
accepts that rejection. Each marker names the failure it expects today through
``raises=``. A wrong fix that raises any other exception therefore fails the suite
(it is not swallowed as an expected failure).

Ported from ``evidence/F3-semantics/test_props.py``, ``evidence/F4-language/tests/
test_findings_pins.py`` and ``evidence/F1-executor/repro.py``. Finding IDs follow the
audit report (``docs/spec/2026-10-09-url4-audit/report.md``, section 4).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from url4 import build, render, src, text
from url4.core.errors import CollectionError, ParseError, RenderError, ResolutionError, Url4Error
from url4.dag import ExecutionContext, Executor, compile_expression, run
from url4.dag.nodes import ExpandNode, GatherNode, GuardNode, JoinNode, WebFetchNode
from url4.dag.nodes._shared import _rows_to_json
from url4.io.static import StaticIOLayer


def _ctx() -> ExecutionContext:
    return ExecutionContext(StaticIOLayer())


def _reject_constant(token: str) -> None:
    raise ValueError(f"non-RFC JSON constant: {token}")


def _is_rfc_json(out: str) -> bool:
    try:
        json.loads(out, parse_constant=_reject_constant)
    except ValueError:
        return False
    return True


class _CountingIO:
    """Records every fetch and echoes the target back."""

    def __init__(self) -> None:
        self.fetches: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        await asyncio.sleep(0)
        return f"<{target}>"


class _FailingIO:
    """Fails the ``bad`` source and answers the others after a short wait."""

    async def fetch(self, target: str, *, relative: bool) -> str:
        if "bad" in target:
            raise ResolutionError("boom")
        await asyncio.sleep(0.05)
        return "v"


# A10 [F3-10] — GatherNode leaks an instrumental value through the fallback join.
# Correct: the instrumental value never reaches the output. Expected today: AssertionError.
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="A10: GatherNode leaks an instrumental value through the fallback join. "
    "Correct: output is '' (no instrumental text). "
    "Out of scope for the audit-fix branch",
)
@pytest.mark.asyncio
async def test_A10_gather_does_not_leak_instrumental_value():
    node = GatherNode(slots=((None, False), (None, True)))
    out = await node.resolve({"src:0": "", "src:1": "INSTRUMENTAL"}, _ctx())
    assert out == ""


# A11 [F3-11] — _rows_to_json emits NaN, which is not RFC JSON.
# Correct: RFC JSON output, OR a Url4Error. A raw ValueError must still fail the test.
# Expected today: AssertionError (the output is not RFC JSON).
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="A11: _rows_to_json emits NaN, which is not RFC JSON. "
    "Correct: RFC JSON output, or a Url4Error. "
    "Out of scope for the audit-fix branch",
)
def test_A11_rows_to_json_is_rfc_json():
    try:
        out = _rows_to_json(["[NaN]"])
    except Url4Error:
        return
    assert _is_rfc_json(out)


# A12 [F3-12] — ExpandNode has no fast path for a list payload.
# Correct: a list payload is already a collection and is returned as is.
# Expected today: CollectionError ("not iterable").
@pytest.mark.xfail(
    strict=True,
    raises=CollectionError,
    reason="A12: ExpandNode has no fast path for a list payload and raises 'not iterable'. "
    "Correct: returns ['one row']. "
    "Out of scope for the audit-fix branch",
)
@pytest.mark.asyncio
async def test_A12_expand_accepts_list_payload():
    out = await ExpandNode().resolve({"inner": ["one row"]}, _ctx())
    assert out == ["one row"]


# B8 [F4-F6] — render is not total on what build accepts.
# Correct: render accepts the built tree, OR build rejects the text with ParseError.
# Spec B §8 puts control characters, quoted param values, parens in a query and an
# empty source-list outside the grammar, so rejecting them in build is a correct fix.
# Expected today: RenderError.
@pytest.mark.xfail(
    strict=True,
    raises=RenderError,
    reason="B8: render is not total on build's image. "
    "Correct: render accepts the tree, or build raises ParseError. "
    "Out of scope for the audit-fix branch",
)
@pytest.mark.parametrize(
    "s",
    ["(https://a.io)!sum\nit", "(a)!go;note='a b'", "@", "/p?a=(1)", "()!()!@;broadcast"],
)
def test_B8_render_total_on_build_image(s):
    try:
        n = build(s)
    except ParseError:
        return
    render(n)


# B9 [F4-F8] — builder output is not always accepted by render.
# Correct: render accepts the node, OR the builder rejects its input with ValueError or
# TypeError (builder validation is a correct fix). Expected today: RenderError.
@pytest.mark.xfail(
    strict=True,
    raises=RenderError,
    reason="B9: a builder returns a node that render rejects. "
    "Correct: render accepts the node, or the builder raises ValueError or TypeError. "
    "Out of scope for the audit-fix branch",
)
@pytest.mark.parametrize(
    "mk",
    [lambda: text("a\nb"), lambda: src("https://x", name="a", weight=float("inf"))],
    ids=["text-newline", "src-inf-weight"],
)
def test_B9_builder_output_renders(mk):
    try:
        n = mk()
    except (ValueError, TypeError):
        return
    render(n)


# B10 [F4-F10] — a broadcast after an iteration is dropped with no error.
# Spec B §8 makes both forms VALID (`intent-op = "!" / "!*"`), so ParseError is NOT a
# correct outcome. Refusing them would need a spec change. The broadcast must survive
# render. Expected today: AssertionError (the broadcast is gone from the rendered text).
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="B10: a broadcast after an iteration is dropped silently. "
    "Correct: the broadcast survives render (the text contains '!*' or ';broadcast'). "
    "Out of scope for the audit-fix branch",
)
@pytest.mark.parametrize("s", ["src*(b)!*go", "src*(b)!go;broadcast"])
def test_B10_iteration_broadcast_survives_render(s):
    node = build(s)
    assert getattr(node, "intent", None) == "go"
    rendered = render(node)
    assert "!*" in rendered or ";broadcast" in rendered


# B11 [F4-F11] — empty text and an empty intent are accepted.
# Correct: build raises ParseError. Expected today: AssertionError (build accepts it).
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="B11: build accepts empty text or an empty intent. "
    "Correct: build raises ParseError. "
    "Out of scope for the audit-fix branch",
)
@pytest.mark.parametrize("s", ["", "(x)!"])
def test_B11_empty_text_or_intent_is_parse_error(s):
    try:
        build(s)
    except ParseError:
        return
    raise AssertionError(f"build accepted {s!r}")


# B12 [F4-F12] — an unmatched { swallows the commas after it.
# Correct: build raises ParseError, because an unmatched '{' is malformed.
# Expected today: AssertionError (build accepts it as one source).
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="B12: an unmatched '{' in bare text swallows the commas after it. "
    "Correct: build raises ParseError. "
    "Out of scope for the audit-fix branch",
)
def test_B12_unmatched_brace_is_parse_error():
    try:
        build("(a{b, c)!x")
    except ParseError:
        return
    raise AssertionError("build accepted an unmatched '{' as one source")


# C4 [F1-4] — a node shared inside and outside a GuardNode is fetched twice.
# Correct: the shared node is fetched once, OR the run raises the resolve-once debug
# guard in dag/executor.py (_check_resolve_counts), which is an AssertionError.
# Expected today: AssertionError from the fetch count (fetched 2 times).
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="C4: a hand-built graph fetches a shared node twice. "
    "Correct: fetched once, or the resolve-once debug guard raises AssertionError. "
    "Out of scope for the audit-fix branch",
)
@pytest.mark.asyncio
async def test_C4_shared_node_is_fetched_once():
    io = _CountingIO()
    shared = WebFetchNode("https://x.test/shared")
    guard = GuardNode(shared, retries=0, optional=True)
    root = JoinNode(deps={"0": shared, "1": guard})
    try:
        await run(root, io=io)
    except AssertionError as exc:
        assert "memo invariant" in str(exc)
        return
    assert io.fetches.count("https://x.test/shared") == 1


# C5 [F1-5] — reusing an Executor after a failed run raises CancelledError.
# Correct: the second run works, OR it raises an error that is not CancelledError.
# Expected today: AssertionError (CancelledError escapes the second run).
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="C5: reusing an Executor after a failed run raises CancelledError. "
    "Correct: the second run works, or raises a non-CancelledError error. "
    "Out of scope for the audit-fix branch",
)
@pytest.mark.asyncio
async def test_C5_reused_executor_does_not_raise_cancelled():
    graph = compile_expression("(https://x.test/bad, https://x.test/good)!'join'")
    ex = Executor(ExecutionContext(_FailingIO()))
    with pytest.raises(Url4Error):
        await ex.execute(graph.sink)
    try:
        await ex.execute(graph.sink)
    except BaseException as exc:
        assert not isinstance(exc, asyncio.CancelledError)
