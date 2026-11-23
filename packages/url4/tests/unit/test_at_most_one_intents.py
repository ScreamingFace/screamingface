"""A C19 form in a structured intent is refused, never read as prose or as a code pointer.

FEATURE: Router Recipe extension, contract C19. An intent is natural language first: a token
that only looks like url4 and fails to parse stays prose, and a ``/`` token that fails stays a
code pointer. A C19 error is not such a failure: the intent parsed as url4 up to a broken mark.
Before, that intent reached the model as a prompt (a group's intent, a row's intent, a Form-3
processor's), a relative one became a code pointer refused on another rule, and the public
intent classifier called it prose or a reference. A node's HTTP entry answers each such error,
and a mark too deep to check, with HTTP 400.

STORY: as a Fusion author, a mark I wrote wrong in a nested intent fails at once, before the
run fetches or calls anything, and is never sent to a model as text.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from url4 import StaticIOLayer, Url4Node, build
from url4.core.at_most_one import AtMostOneFormError
from url4.core.context import Context
from url4.core.errors import ErrorCode
from url4.core.intent import IntentForm, classify_intent
from url4.core.nodes import Expression, Iteration, Node, RelUrl, Text, Url
from url4.dag import compile_expression, run
from url4.peer._http import handle_http

KEY = "expand.at_most_one"
BAD = f"(*m:https://two;required;{KEY}=false)!'inner'"
GOOD = f"(*m:https://one;required;{KEY}=true)!'inner'"
MARK_PARAM = f"/p?{KEY}=true&q=(b)!'i'"


class _LoggedIO(StaticIOLayer):
    """A static IO layer that records every fetch."""

    def __init__(self) -> None:
        super().__init__(fetch_map={"https://list": '["1"]', "https://one": '["one"]'})
        self.fetches: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        return await super().fetch(target, relative=relative)


class _Calls:
    """A process double: records each call's intent."""

    def __init__(self) -> None:
        self.calls: list[str | None] = []

    async def __call__(self, sources: str, intent: str | None, scope: Context) -> str:
        self.calls.append(intent)
        return "done"


async def _refused(target: str | Node, processor: str | None = None) -> None:
    """Run ``target`` and assert a C19 ``malformed_source`` refusal with no fetch and no call."""
    io, process = _LoggedIO(), _Calls()
    with pytest.raises(AtMostOneFormError) as caught:
        await run(target, io, process=process, processor=processor)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE
    assert (io.fetches, process.calls) == ([], [])


_PARSED = {
    "group-intent": f"(a:'A')!{BAD}",
    "relative-intent": f"(a:'A')!{MARK_PARAM}",
}
_TARGETS: dict[str, str | Node] = {
    **_PARSED,
    "row-intent": f"https://list*($item)!{BAD}",
    "tree-row-intent": Iteration(collection=Url("https://list"), body="$item", intent=BAD),
}


@pytest.mark.parametrize("text", list(_PARSED.values()), ids=list(_PARSED))
def test_the_parser_refuses_a_c19_error_in_a_structured_intent(text: str) -> None:
    # INVARIANT: a C19 error is never prose and never a code pointer. Before, the group's intent
    # became Text and the relative one a RelUrl, and the error was lost.
    with pytest.raises(AtMostOneFormError):
        build(text)


@pytest.mark.parametrize("target", list(_TARGETS.values()), ids=list(_TARGETS))
@pytest.mark.asyncio
async def test_a_c19_error_in_a_structured_intent_is_refused_before_any_io(
    target: str | Node,
) -> None:
    # INVARIANT: compile_expression and run refuse it before any fetch or call. Before, the
    # group's and the row's intent reached the model as a prompt, the row's after the
    # collection fetch, and the relative one failed later on another rule.
    await _refused(target)
    with pytest.raises(AtMostOneFormError):
        compile_expression(target)


@pytest.mark.asyncio
async def test_a_form3_processor_with_a_c19_error_in_its_intent_is_refused_before_any_io() -> None:
    # INVARIANT: the run start reads a Form-3 processor as it reads the target.
    await _refused("(/a('x')!'i', /b('y')!'j')!'go'", processor=f"('x')!{BAD}")


@pytest.mark.parametrize("intent", [BAD, f"url4://n{MARK_PARAM}"], ids=["group", "remote"])
def test_the_intent_classifier_raises_a_c19_error_instead_of_reclassifying(intent: str) -> None:
    # INVARIANT: the classifier and the parser cannot disagree, and a text the parser refuses
    # raises its error. Before, the group read as prose and the remote call as a reference.
    with pytest.raises(AtMostOneFormError):
        classify_intent(intent)


def test_an_intent_without_a_c19_error_keeps_its_base_reading() -> None:
    # WHY: only a C19 error changes. A well-formed mark stays structured; a token that only
    # looks like url4 stays prose; a failing code pointer stays one, and so does a failing
    # reference; a remote call's context is its receiver's to read.
    marked, prose = build(f"(a:'A')!{GOOD}"), build("(a:'A')!(two words, here)")
    assert isinstance(marked, Expression) and isinstance(marked.intent, Expression)
    assert isinstance(prose, Expression) and prose.intent == Text("(two words, here)")
    pointer = build("(a:'A')!/p((")
    assert isinstance(pointer, Expression) and pointer.intent == RelUrl("/p((")
    assert classify_intent(GOOD) == IntentForm.EXPRESSION
    assert classify_intent("{not a struct") == IntentForm.PROSE
    assert classify_intent("url4://n/p((") == IntentForm.URL4_REFERENCE
    assert classify_intent(f"url4://n/p(*m:https://two;required;{KEY}=false)!'i'") == (
        IntentForm.EXPRESSION
    )


@pytest.mark.asyncio
async def test_a_well_formed_mark_in_a_structured_intent_still_runs() -> None:
    io, process = _LoggedIO(), _Calls()
    assert await run(f"(a:'A')!{GOOD}", io, process=process) == "done"
    assert io.fetches == ["https://one"]


# --- a node's HTTP entry -------------------------------------------------------------------------

_DEPTH = 300  # WHY: past the eager parser's reach (about 140 nested groups), not the compiler's


def _deep(bottom: str) -> str:
    for _ in range(_DEPTH):
        bottom = f"(/b(y)!'w', {bottom})!'h'"
    return bottom


_HTTP = {
    "structured-intent": f"q=(a:'A')!{BAD}",
    "deep-context": f"q=(/a, /p({_deep(f'*m:https://one;required;{KEY}=true')})!'o')!'r'",
    "deep-processor": f"processor={_deep(f'n=({GOOD})!{chr(39)}x{chr(39)}')}&q=('hi')!'i'",
}


@pytest.mark.parametrize("query", list(_HTTP.values()), ids=list(_HTTP))
@pytest.mark.asyncio
async def test_a_node_answers_a_c19_error_over_http_with_400(query: str) -> None:
    # INVARIANT: a node refuses over HTTP what it refuses in text, with HTTP 400. Before, the
    # structured intent ran as a prompt, and the deep context and processor escaped as a
    # RecursionError, an HTTP 500. WHY a raw query: an encoded processor reads as an id.
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": "/v1", "query_string": query.encode()}
    await handle_http(Url4Node("t", eval_path="/v1"), scope, send)
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert (sent[0]["status"], json.loads(body)["error"]["code"]) == (400, "malformed_source")
