"""B2 regression: a leading ``*(`` at the envelope is expansion, never iteration.

Audit report §4.B (B2). The source-initial ``*`` (the first non-space character) is the
expansion prefix (§5.2 rule 9), so ``*(body)`` there must not be read as the §5.3.3
iteration operator. Before the fix, ``*(https://a, https://b)!go`` parsed as an
iteration over an empty collection and returned ``[]`` without fetching anything.

Grammar reading (Spec B §8): ``bare-source = value`` and ``value`` includes ``local-expr``,
so ``*(...)!i`` is a valid expansion source inside a source list. That is why the nested
forms below agree on both paths. At top level the ``!`` takes the intent, so the group
after ``*`` has none. The parser therefore rejects a top-level ``*(...)!x`` with
``MISSING_INTENT`` on both paths. That is the correct loud result.

Run: pytest -q tests/regressions/test_leading_star.py
"""

from __future__ import annotations

import asyncio
from collections import Counter

import pytest
from conftest import RecordingIOLayer

from url4 import build
from url4.core.errors import ErrorCode, ParseError
from url4.dag import run


def observe(source: str, *, via_ast: bool) -> tuple:
    io = RecordingIOLayer()
    try:
        target = build(source) if via_ast else source
        out = asyncio.run(run(target, io))
    except ParseError as e:
        return ("parse-error", e.code), Counter(io.fetches)
    return ("ok", out), Counter(io.fetches)


@pytest.mark.parametrize("source", ["*(https://a, https://b)!go", "*(https://a.io)!'i'"])
def test_top_level_leading_star_group_is_a_parse_error_not_an_empty_iteration(source: str) -> None:
    io = RecordingIOLayer()
    with pytest.raises(ParseError, match="a leading '\\*' expands a source") as text_error:
        asyncio.run(run(source, io))
    assert text_error.value.code == ErrorCode.MISSING_INTENT
    assert io.fetches == []
    with pytest.raises(ParseError):
        build(source)


@pytest.mark.parametrize(
    "source",
    [
        "*(https://a, https://b)!go",
        "*(https://a.io)!'i'",
        "(x, (*(https://a.io)!'i')!'j')!'k'",
        "(*(https://a.io)*('$item')!'i')!'k'",
        "(x, *(https://a.io)*('$item')!'i')!'k'",
        "( *(https://a.io)!'i')!'k'",
    ],
)
def test_leading_star_text_path_matches_ast_path(source: str) -> None:
    assert observe(source, via_ast=False) == observe(source, via_ast=True)


def test_nested_leading_star_expands_its_source() -> None:
    result, fetches = observe("(x, (*(https://a.io)!'i')!'j')!'k'", via_ast=False)
    assert result == ("ok", "k\n\nx\nj\n\ni\n<https://a.io>")
    assert fetches == Counter({"https://a.io": 1})


def test_expansion_of_iteration_as_only_source_runs() -> None:
    # F1: the expansion-of-an-iteration is the only source, so it must not decode
    # as a reduce-over-iteration with collection "*(https://a.io)".
    result, fetches = observe("(*(https://a.io)*('$item')!'i')!'k'", via_ast=False)
    assert result == ("ok", "k\n\ni\n\n<https://a.io>")
    assert fetches == Counter({"https://a.io": 1})


def test_iteration_with_collection_before_star_still_iterates() -> None:
    result, fetches = observe("(https://a.io, https://b.io)*('$item')!'go'", via_ast=False)
    assert result == ("ok", '["go\\n\\n<https://a.io>", "go\\n\\n<https://b.io>"]')
    assert fetches == Counter({"https://a.io": 1, "https://b.io": 1})
