"""Collection parsing must not multiply a large fetched body in memory.

# FEATURE: url4 `src*(…)` iteration over large fetched collections (benchmark case files).
# STORY: as a benchmark operator, I iterate two rows of a 330 MB `cases.json` without
#   url4 holding four copies of it.
# INVARIANT: items are byte-identical to the pre-optimisation parser — number spellings,
#   nested float rendering, NaN/Infinity, unicode escaping, strip semantics.
"""

from __future__ import annotations

import gc
import json
import tracemalloc
from typing import Any

import pytest

from url4.core.errors import CollectionError
from url4.core.nodes import IterationDirectives
from url4.dag.nodes import MapNode
from url4.dag.nodes import iteration as iteration_module
from url4.dag.nodes._shared import FetchedText
from url4.dag.semantics import collection
from url4.dag.semantics.collection import parse_collection

# Expected values were produced by the parser at origin/main f76cacf85 (two-pass
# `json.loads`), so these pin byte-identity across the single-pass rewrite.
_ARRAY = (
    "[2.50, 1e5, -0, 12345678901234567890, 7, -1.0E-3, NaN, Infinity, -Infinity, true, "
    'false, null, "s\\u00e9", "x", {"a": 2.50, "b": [1.0, NaN, -0], "c": "\\u00e9"}, '
    "[1e2, 3], [], {}]"
)
_EXPECTED = [
    "2.50",
    "1e5",
    "-0",
    "12345678901234567890",
    "7",
    "-1.0E-3",
    "NaN",
    "Infinity",
    "-Infinity",
    "true",
    "false",
    "null",
    "sé",
    "x",
    '{"a": 2.5, "b": [1.0, NaN, 0], "c": "\\u00e9"}',
    "[100.0, 3]",
    "[]",
    "{}",
]


@pytest.mark.parametrize("media_type", ["application/json", None])
def test_json_array_items_are_byte_identical(media_type: str | None) -> None:
    assert parse_collection(_ARRAY, media_type) == _EXPECTED


@pytest.mark.parametrize("media_type", ["application/json", None])
def test_json_array_items_are_plain_str(media_type: str | None) -> None:
    # The spelled-number carriers must never leak out as items.
    assert all(type(item) is str for item in parse_collection(_ARRAY, media_type))


@pytest.mark.parametrize("media_type", ["application/json", None])
def test_json_array_is_parsed_exactly_once(
    monkeypatch: pytest.MonkeyPatch, media_type: str | None
) -> None:
    calls: list[int] = []
    real = json.loads

    def counting(text: str, **kwargs: Any) -> Any:
        calls.append(len(text))
        return real(text, **kwargs)

    monkeypatch.setattr(collection.json, "loads", counting)
    assert parse_collection(_ARRAY, media_type) == _EXPECTED
    assert len(calls) == 1


def test_sniffed_json_array_never_splits_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(_body: str) -> list[str]:
        raise AssertionError("_lines must not run for a JSON array body")

    monkeypatch.setattr(collection, "_lines", forbidden)
    assert parse_collection("\n[1, 2]\n") == ["1", "2"]


def test_sniff_falls_back_to_lines_when_not_a_json_array() -> None:
    # `[` that is not JSON still degrades to plain lines exactly as before.
    assert parse_collection("[a\nb]") == ["[a", "b]"]


@pytest.mark.parametrize("media_type", ["application/json", None])
def test_unicode_whitespace_padding_is_still_stripped(media_type: str | None) -> None:
    # str.strip() removes more than JSON whitespace; the no-copy path must not lose that.
    assert parse_collection("   [1, 2.50]\n ", media_type) == ["1", "2.50"]


def test_whitespace_only_body_is_empty() -> None:
    assert parse_collection(FetchedText(" \n\t ", "application/json")) == []


def test_declared_json_errors_are_unchanged() -> None:
    with pytest.raises(CollectionError, match="not valid JSON"):
        parse_collection("[1,", "application/json")
    with pytest.raises(CollectionError, match="non-array"):
        parse_collection('\n{"a": 1}\n', "application/json")


_WINDOW_CASES = [
    ('[1, 2.50, {"a": 1}, "d", null]', "application/json"),
    ('[1, 2.50, {"a": 1}, "d", null]', None),
    ('{"a": 1}\n2.50\n"x"\n[1]', "application/x-ndjson"),
    ("name,age\nalice,30\nbob,25\ncarol,41", "text/csv"),
    ("alpha\nbeta\ngamma\ndelta", "text/plain"),
    ("alpha\nbeta\ngamma\ndelta", None),
]
_WINDOWS = [(0, 2), (1, 3), (-2, 4), (3, 99), (5, 9), (2, 1), (0, 0)]


@pytest.mark.parametrize(("body", "media_type"), _WINDOW_CASES)
@pytest.mark.parametrize("window", _WINDOWS)
def test_window_equals_parse_then_slice(
    body: str, media_type: str | None, window: tuple[int, int]
) -> None:
    start, end = window
    expected = parse_collection(body, media_type)[start:end]
    assert parse_collection(body, media_type, window=window) == expected


def test_rows_outside_the_window_are_never_serialised(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    real = collection._item_to_str

    def spy(item: object) -> str:
        seen.append(item)
        return real(item)

    monkeypatch.setattr(collection, "_item_to_str", spy)
    body = json.dumps([{"i": i} for i in range(10)])
    assert parse_collection(body, "application/json", window=(2, 4)) == [
        '{"i": 2}',
        '{"i": 3}',
    ]
    assert seen == [{"i": 2}, {"i": 3}]


def test_map_node_hands_its_slice_to_the_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    real = iteration_module.parse_collection

    def spy(
        body: str, media_type: str | None = None, *, window: tuple[int, int] | None = None
    ) -> list[str]:
        calls.append(window)
        return real(body, media_type, window=window)

    monkeypatch.setattr(iteration_module, "parse_collection", spy)
    node = MapNode(body="$item", directives=IterationDirectives(slice=(1, 3)))
    body = FetchedText("[10, 20, 30, 40]", "application/json")
    assert node._items(body) == ["20", "30"]
    assert calls == [(1, 3)]


def test_map_node_slice_still_applies_to_inline_lists() -> None:
    node = MapNode(body="$item", directives=IterationDirectives(slice=(1, 3)))
    assert node._items(["a", "b", "c", "d"]) == ["b", "c"]


def _large_body(rows: int = 8, row_chars: int = 1_000_000) -> FetchedText:
    blob = "QUJD" * (row_chars // 4)
    data = [{"id": i, "score": 2.50, "image": blob} for i in range(rows)]
    return FetchedText(json.dumps(data) + "\n", "application/json")


def test_windowed_parse_of_large_body_stays_near_one_body_copy() -> None:
    # Before: strip copy + parse + second parse + every row re-serialised ≈ 4x body.
    body = _large_body()
    node = MapNode(body="$item", directives=IterationDirectives(slice=(0, 2)))
    gc.collect()
    tracemalloc.start()
    try:
        items = node._items(body)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(items) == 2
    assert json.loads(items[1])["id"] == 1
    assert peak < 1.5 * len(body), f"peak {peak} vs body {len(body)}"


def test_full_parse_of_large_body_does_not_hold_parsed_and_serialised_rows() -> None:
    # Without a window every row is materialised, but each parsed row is released as
    # it is serialised, so parsed data and output never coexist in full.
    body = _large_body()
    gc.collect()
    tracemalloc.start()
    try:
        items = parse_collection(body, body.media_type)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(items) == 8
    assert peak < 2.5 * len(body), f"peak {peak} vs body {len(body)}"
