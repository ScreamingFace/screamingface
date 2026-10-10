"""G10 follow-ups — envelope shapes the grammar has no reading for fail at parse time.

Spec B §8: an iteration is `collection-ref "*" expression`, and a collection-ref is
a value; a value never starts with `*` (the expansion prefix marks a SOURCE), and a
name-only descriptor (`n=`, `n:`) is not a value. A top-level absolute-URL intent is
`bare-value`, which has no `(`, `)` or `'`. Each shape below used to parse and then
fail late (or not render); now `build` and the text path both refuse it.
"""

from __future__ import annotations

import asyncio

import pytest

from url4 import build
from url4.core.errors import ParseError
from url4.core.parser import decode_envelope
from url4.dag import run
from url4.io.static import StaticIOLayer


def _refused_everywhere(text: str, match: str) -> None:
    with pytest.raises(ParseError, match=match):
        build(text)
    with pytest.raises(ParseError, match=match):
        asyncio.run(run(text, StaticIOLayer({"https://a.io": "[1]"})))


@pytest.mark.parametrize(
    "text", ["(n=*(https://a.io)!'i')!'k'", "n=*(https://a.io)!'i'", "n:*(https://a.io)!'i'"]
)
def test_a_name_only_descriptor_is_not_a_collection(text: str) -> None:
    _refused_everywhere(text, "name-only descriptor")


def test_an_expanded_source_is_not_a_collection() -> None:
    # `*(a)` marks a source for expansion; it cannot be a collection-ref.
    _refused_everywhere("*(a)*(b)!x", "collection cannot start with '\\*'")


@pytest.mark.parametrize("text", ["*(b)!x", "  *(b)!x"])
def test_an_iteration_with_no_collection_never_decodes(text: str) -> None:
    # The lowering's empty-collection branch is dead: no envelope yields one.
    with pytest.raises(ParseError):
        env = decode_envelope(text)
        assert getattr(env, "collection", "x") != ""
        build(text)


@pytest.mark.parametrize(
    "text",
    ["()!https://w.org/Fish_(animal)", "('a')!https://w.org/a)b", "('a')!https://w.org/it's"],
)
def test_a_top_level_url_intent_is_a_bare_value(text: str) -> None:
    _refused_everywhere(text, "bare value")


@pytest.mark.parametrize(
    "text",
    ["('a')!https://w.org/a*b", "('a')!/reduce()", "('a')!'https://w.org/Fish_(animal)'"],
)
def test_bare_value_url_intents_still_parse(text: str) -> None:
    build(text)
