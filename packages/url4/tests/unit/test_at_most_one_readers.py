"""A public eager reader refuses a text too deep for it that names the C19 mark.

FEATURE: Router Recipe extension, contract C19. A url4 text too deep for the eager parser (about
140 nested groups) cannot be read, so a mark in it cannot be checked: one that names the mark is
refused, FAIL CLOSED, and any other keeps its base ``RecursionError``. ``compile_expression`` and
``run`` refused such a text; the public eager readers (``parse``, ``parse_value``, ``build``,
``Parser.build``, ``classify_intent``) and the client front door, which builds the text itself
for a node target or protocol params, let it escape as a ``RecursionError``. So did every other
entry that reads such a text as an intent: the builders and the client helpers (an intent, a
reducer), ``is_named_job`` (a named job ``render`` checks, a code name ``Url4Node.code`` mounts)
and ``render`` reading back a structured intent. The refusal costs a read no frame: each reader
reads a text from as deep a caller as its base entry did.

STORY: as a url4 SDK user, a marked expression too deep to check fails as ``malformed_source``
at whichever entry I call, never as an internal error, and before anything is fetched.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable

import pytest

from url4 import (
    Expression,
    Iteration,
    NamedJob,
    Node,
    RelUrl,
    Source,
    StaticIOLayer,
    Text,
    Url4Node,
    broadcast,
    build,
    expr,
    iterate,
    reduce,
    render,
)
from url4.core.at_most_one import AtMostOneFormError
from url4.core.errors import ErrorCode
from url4.core.grammar import _parse_source, _parse_value, intent_atom, parse, parse_value
from url4.core.intent import classify_intent, is_named_job
from url4.core.parser import IterationEnvelope, Parser, assemble_expression, decode_envelope
from url4.peer.client import Client

KEY = "expand.at_most_one"
_DEPTH = 300  # WHY: past the eager parser's reach (about 140 nested groups)
_MARK = f"*m:https://one;required;{KEY}=true"


def _deep(bottom: str, depth: int = _DEPTH) -> str:
    for _ in range(depth):
        bottom = f"(/b(y)!'w', {bottom})!'h'"
    return bottom


MARKED = _deep(_MARK)  # a well-formed mark, too deep to check
PLAIN = _deep("https://one")

_READERS: dict[str, Callable[[str], object]] = {
    "parse": parse,
    "parse_value": parse_value,
    "build": build,
    "Parser.build": Parser().build,
    "classify_intent": classify_intent,
}


@pytest.mark.parametrize("read", list(_READERS.values()), ids=list(_READERS))
def test_a_public_eager_reader_refuses_a_marked_text_too_deep_to_read(
    read: Callable[[str], object],
) -> None:
    # INVARIANT (FAIL CLOSED): the reader refuses it as compile_expression and run do. Before,
    # it escaped as a RecursionError, an internal error.
    with pytest.raises(AtMostOneFormError, match="nested too deeply") as caught:
        read(MARKED)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE


@pytest.mark.parametrize("read", list(_READERS.values()), ids=list(_READERS))
def test_a_public_eager_reader_keeps_its_base_error_for_an_unmarked_deep_text(
    read: Callable[[str], object],
) -> None:
    # WHY: a text that names the mark nowhere has no C19 form to check; it keeps its base error.
    with pytest.raises(RecursionError):
        read(PLAIN)


class _LoggedIO(StaticIOLayer):
    """A static IO layer that records every fetch."""

    def __init__(self) -> None:
        super().__init__(fetch_map={"https://one": "one"})
        self.fetches: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        return await super().fetch(target, relative=relative)


_FRONT_DOORS: dict[str, Callable[[Client, str], Awaitable[object]]] = {
    "params": lambda client, text: client.evaluate(text, params=(("k", "v"),)),
    "node": lambda client, text: client.evaluate(text, node="http://peer.invalid:1"),
}


@pytest.mark.parametrize("evaluate", list(_FRONT_DOORS.values()), ids=list(_FRONT_DOORS))
@pytest.mark.asyncio
async def test_the_client_front_door_refuses_a_marked_text_too_deep_to_read(
    evaluate: Callable[[Client, str], Awaitable[object]],
) -> None:
    # INVARIANT: the front door builds the text itself for a node target or protocol params;
    # it refuses there, before any fetch or call. Before, a RecursionError escaped.
    io = _LoggedIO()
    with pytest.raises(AtMostOneFormError, match="nested too deeply"):
        await evaluate(Client(io=io), MARKED)
    assert io.fetches == []
    with pytest.raises(RecursionError):
        await evaluate(Client(io=io), PLAIN)


# --- an intent, a reducer or a named job given to a builder, a client helper or render ----------


def _reducing(reducer: str) -> Iteration:
    """An iteration with a cross-row reducer: a source rewrites it to ``(iteration)!reducer``."""
    return Iteration(collection=RelUrl("/c"), body="$item", intent="'r'", reducer=reducer)


def _tree(bottom: Node, depth: int = 155) -> Node:
    """A tree too deep to read back as text, yet one the renderer can write. WHY 155: a level
    of it costs ``render`` fewer frames than the parser."""
    for _ in range(depth):
        bottom = Expression(sources=(bottom,), intent=Text("w"))
    return bottom


_MARKED_SOURCE = Source(
    RelUrl("/x"), name="m", expand=True, annotations=(("required", None), (KEY, "true"))
)
# WHY a tree per text: a structured intent is given as a tree, never as text; its rendering is
# the text read back.
_TREES = {MARKED: _tree(_MARKED_SOURCE), PLAIN: _tree(RelUrl("/x"))}


def _intent(intent: Node) -> Expression:
    return Expression(sources=(Text("a"),), intent=intent)


_BUILDERS: dict[str, Callable[[str], object]] = {
    "expr": lambda text: expr("a", intent=text),
    "broadcast": lambda text: broadcast("a", intent=text),
    "reduce": lambda text: reduce("/ep(a)!'i'", intent=text),
    "iterate-intent": lambda text: iterate("/c", "$item", intent=text),
    "iterate-reduce": lambda text: iterate("/c", "$item", intent="'r'", reduce=text),
    "iteration-reducer": lambda text: expr(_reducing(text), intent="'top'"),
    "is_named_job": is_named_job,
    "render-named-job": lambda text: render(_intent(NamedJob(text))),
    "code-name": lambda text: Url4Node("t").code(text),
    "render-structured-intent": lambda text: render(_intent(_TREES[text])),
    "render-unchecked": lambda text: render(_intent(_TREES[text]), check=False),
}


@pytest.mark.parametrize("read", list(_BUILDERS.values()), ids=list(_BUILDERS))
def test_a_builder_or_render_refuses_a_marked_intent_too_deep_to_read(
    read: Callable[[str], object],
) -> None:
    # INVARIANT (FAIL CLOSED): an intent text reaches the parser from a builder as from a reader,
    # so it is refused there too; an unmarked one keeps its base error. Before, a marked one
    # escaped as a RecursionError.
    with pytest.raises(AtMostOneFormError, match="nested too deeply") as caught:
        read(MARKED)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE
    with pytest.raises(RecursionError):
        read(PLAIN)


_HELPERS: dict[str, Callable[[Client, str], Awaitable[object]]] = {
    "query": lambda client, text: client.query("https://one", intent=text),
    "broadcast": lambda client, text: client.broadcast("https://one", intent=text),
    "reduce": lambda client, text: client.reduce("/ep(a)!'i'", intent=text),
    "iterate-intent": lambda client, text: client.iterate(["x"], "$item", intent=text),
    "iterate-reduce": lambda client, text: client.iterate(
        ["x"], "$item", intent="'r'", reduce=text
    ),
    "query-iteration": lambda client, text: client.query(_reducing(text), intent="'top'"),
    "remote-iteration": lambda client, text: client.evaluate(
        _reducing(text), node="http://peer.invalid:1"
    ),
    "named-job": lambda client, text: client.evaluate(_intent(NamedJob(text))),
    "structured-intent": lambda client, text: client.evaluate(_intent(_TREES[text])),
}


@pytest.mark.parametrize("helper", list(_HELPERS.values()), ids=list(_HELPERS))
@pytest.mark.asyncio
async def test_a_client_helper_refuses_a_marked_intent_too_deep_to_read(
    helper: Callable[[Client, str], Awaitable[object]],
) -> None:
    # INVARIANT: a helper builds or renders the tree before it runs, so it refuses there, before
    # any fetch or call. Before, a RecursionError escaped.
    io = _LoggedIO()
    with pytest.raises(AtMostOneFormError, match="nested too deeply"):
        await helper(Client(io=io), MARKED)
    assert io.fetches == []
    with pytest.raises(RecursionError):
        await helper(Client(io=io), PLAIN)


# --- the refusal costs a read no frame ------------------------------------------------------------


def _build_entry(text: str) -> object:
    """``build`` at base: its body, for a text that is no iteration."""
    env = decode_envelope(text)
    assert not isinstance(env, IterationEnvelope)
    return assemble_expression(env.source_expr, env.intent, env.broadcast, env.params)


def _nested(read: Callable[[str], object], frames: int) -> Callable[[str], object]:
    """``read`` called from ``frames`` frames: an entry's base path to its parser, frame for
    frame."""

    def call(text: str, left: int = frames - 1) -> object:
        return call(text, left - 1) if left else read(text)

    return call


# Each public reader beside its base entry: its parser, called from as many frames as the
# reader called it from at base (``expr`` → ``_intent_node``; a source's reducer through the
# generator, ``_coerce_source`` and ``_rewrite_reducer_iteration``).
_ENTRIES: dict[str, tuple[Callable[[str], object], Callable[[str], object]]] = {
    "parse": (parse, lambda text: _parse_source(text)),
    "parse_value": (parse_value, lambda text: _parse_value(text)),
    "build": (build, _build_entry),
    "Parser.build": (Parser().build, lambda text: _build_entry(text)),
    "classify_intent": (classify_intent, lambda text: intent_atom(text)),
    "is_named_job": (is_named_job, _nested(intent_atom, 1)),
    "expr": (lambda text: expr("a", intent=text), _nested(intent_atom, 3)),
    "iteration-reducer": (
        lambda text: expr(_reducing(text), intent="'t'"),
        _nested(intent_atom, 5),
    ),
}


def _outcome(read: Callable[[str], object], text: str, frames: int) -> type[Exception] | None:
    """What ``read(text)`` raises, called ``frames`` frames deeper than here; None if it reads."""
    if frames:
        return _outcome(read, text, frames - 1)
    try:
        read(text)
    except (RecursionError, AtMostOneFormError) as error:
        return type(error)
    return None


def _probe(read: Callable[[str], object], text: str, frames: int) -> type[Exception] | None:
    try:
        return _outcome(read, text, frames)
    except RecursionError:  # WHY: the frames below the read already ran out
        return RecursionError


def _reach(read: Callable[[str], object], text: str) -> tuple[int, type[Exception] | None]:
    """The most frames a caller may stand on for ``read`` to read ``text``, and what one more
    frame makes it raise."""
    lo, hi = 0, sys.getrecursionlimit()
    while lo < hi:
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if _probe(read, text, mid) is None else (lo, mid - 1)
    return lo, _probe(read, text, lo + 1)


@pytest.mark.parametrize(("public", "base"), list(_ENTRIES.values()), ids=list(_ENTRIES))
def test_a_public_eager_reader_reads_as_deep_as_its_base_entry(
    public: Callable[[str], object], base: Callable[[str], object]
) -> None:
    # INVARIANT: the refusal runs in the reader's own frame, after the stack unwinds, so a
    # near-limit unmarked text the base entry reads, the reader reads too; a marked one a frame
    # deeper is refused, never an internal error. WHY a small text and a deep caller: one frame
    # counts there, and a read stays cheap. Before, a wrapper frame (two for most readers)
    # failed such a text: an unmarked 141-group text that base build and parse_value read.
    plain, marked = _deep("https://one", 20), _deep(_MARK, 20)
    assert _reach(public, plain) == _reach(base, plain)
    room, refused = _reach(base, marked)
    assert (refused, _reach(public, marked)) == (RecursionError, (room, AtMostOneFormError))
