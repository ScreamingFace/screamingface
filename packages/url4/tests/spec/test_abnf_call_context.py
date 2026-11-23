"""ABNF conformance — call parens carry a resolved source-list (OME-535).

`relative-expr-sugar = "/" path "(" source-list ")" intent-op intent` and its
canonical relative twin (``/path?q=...``): the CALLER resolves the context
source-list before dispatch, packing per the OME-534 rules (named → ``name: value``,
weight-0.0 instrumental excluded). A context that does not parse as a source-list
falls back verbatim to raw text, so prose prompts keep working. Resolution happens
exactly once, caller-side — receivers still get opaque resolved data.

A remote call's context (``url4://...``) is not resolved here: it is
receiver-owned, forwarded byte for byte and parsed by the receiving node, so it is
checked separately (``tests/unit/test_at_most_one_receivers.py``).
"""

from __future__ import annotations

import pytest

from url4 import StaticIOLayer
from url4.dag import run

pytestmark = pytest.mark.asyncio


def _echo_io(**extra: str) -> StaticIOLayer:
    return StaticIOLayer(
        fetch_map={"/doc": "DOC", "https://x": "ARTICLE", **extra},
        routes={
            "/ep": lambda context, intent: f"EP[{context}|{intent}]",
            "/inner": lambda context, intent: f"IN[{context}|{intent}]",
        },
    )


async def test_named_uri_source_in_call_context_resolves_labeled() -> None:
    # INVARIANT: the receiver gets resolved DATA, never an unresolved URI.
    result = await run("/ep(judged: /doc)!'go'", _echo_io())
    assert result == "EP[judged: DOC|go]"


async def test_nested_call_in_context_executes() -> None:
    # The headline OME-535 fix: /python(judged:/gemini(...)!'grade') resolves
    # the inner judge before dispatching the outer call.
    result = await run("/ep(judged:/inner('x')!'grade')!'go'", _echo_io())
    # quotes are delimiters (§5.1): the inner receiver gets the VALUE x
    assert result == "EP[judged: IN[x|grade]|go]"


async def test_outer_binding_visible_inside_call_context() -> None:
    result = await run("(a:0:https://x, /ep(data: $a)!'go')!'noop'", _echo_io())
    assert "EP[data: ARTICLE|go]" in result


async def test_instrumental_context_member_excluded() -> None:
    result = await run("/ep(h:0:/doc, 'lit')!'go'", _echo_io())
    assert result == "EP[lit|go]"


async def test_prose_context_stays_verbatim() -> None:
    # A single prose segment is one bare text source — packs as itself.
    result = await run("/ep(Explain the critique of TWFE.)!'go'", _echo_io())
    assert result == "EP[Explain the critique of TWFE.|go]"


async def test_unparseable_source_list_falls_back_to_raw_text() -> None:
    # "run: 1" is a name with a non-value-shaped bare binding — not a legal
    # source-list — so the WHOLE context ships verbatim (prompt compatibility).
    result = await run("/ep(run: 1, question: x)!'go'", _echo_io())
    assert result == "EP[run: 1, question: x|go]"


async def test_absolute_url_in_context_is_fetched() -> None:
    # The decided behavioral flip: a URL in call parens is a SOURCE — the
    # receiver gets the fetched content, not the literal URL text.
    result = await run("/ep(https://x)!'go'", _echo_io())
    assert result == "EP[ARTICLE|go]"


async def test_empty_context_unchanged() -> None:
    result = await run("/ep()!'go'", _echo_io())
    assert result == "EP[|go]"


async def test_item_reference_in_call_context_inside_map_rows() -> None:
    io = _echo_io(**{"https://rows": '["1", "2"]'})
    result = await run("https://rows*(r:0:/ep(q: $item)!'go')!'$r'", io)
    assert "EP[q: 1|go]" in result
    assert "EP[q: 2|go]" in result
