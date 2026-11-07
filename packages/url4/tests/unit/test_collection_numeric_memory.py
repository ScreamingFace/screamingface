"""Number-heavy JSON collections must stay near one body copy (PR #1622 review round 1).

# FEATURE: url4 `src*(…)` iteration over large fetched collections (benchmark case files).
# STORY: as a benchmark operator, I iterate two rows of a large integer grid or float
#   matrix without url4 wrapping every nested number in a spelling carrier.
# INVARIANT: only TOP-LEVEL array elements keep their source spelling; nested numbers
#   are plain `int`/`float`, exactly as `json.loads` returns them.
"""

from __future__ import annotations

import gc
import json
import random
import tracemalloc

import pytest

from url4.core.errors import CollectionError
from url4.core.nodes import IterationDirectives
from url4.dag.nodes import MapNode
from url4.dag.nodes._shared import FetchedText
from url4.dag.semantics import collection
from url4.dag.semantics.collection import parse_collection


def _windowed_peak(body: FetchedText) -> tuple[list[str], int]:
    node = MapNode(body="$item", directives=IterationDirectives(slice=(0, 2)))
    gc.collect()
    tracemalloc.start()
    try:
        items = node._items(body)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return items, peak


def test_integer_grid_windowed_parse_stays_near_one_body_copy() -> None:
    # 0-9 ints are Python's cached small ints; a per-number carrier made this ~140x body.
    grid = [[(row + col) % 10 for col in range(2560)] for row in range(300)]
    body = FetchedText(json.dumps(grid) + "\n", "application/json")
    items, peak = _windowed_peak(body)
    assert [json.loads(item) for item in items] == grid[:2]
    assert peak < 1.5 * len(body), f"peak {peak} vs body {len(body)}"


def test_float_matrix_windowed_parse_stays_near_one_body_copy() -> None:
    rng = random.Random(0)
    matrix = [[round(rng.random(), 8) for _ in range(2000)] for _ in range(300)]
    body = FetchedText(json.dumps(matrix) + "\n", "application/json")
    items, peak = _windowed_peak(body)
    assert [json.loads(item) for item in items] == matrix[:2]
    assert peak < 1.5 * len(body), f"peak {peak} vs body {len(body)}"


def _numbers(value: object) -> list[object]:
    if isinstance(value, list):
        return [n for item in value for n in _numbers(item)]
    if isinstance(value, dict):
        return [n for item in value.values() for n in _numbers(item)]
    return [value] if isinstance(value, int | float) and not isinstance(value, bool) else []


@pytest.mark.parametrize("media_type", ["application/json", None])
def test_nested_numbers_are_parsed_plain(
    monkeypatch: pytest.MonkeyPatch, media_type: str | None
) -> None:
    seen: list[object] = []
    real = collection._item_to_str

    def spy(item: object) -> str:
        seen.append(item)
        return real(item)

    monkeypatch.setattr(collection, "_item_to_str", spy)
    body = '[{"a": 2.50, "b": [1e5, -0, 12345678901234567890, NaN, 7]}, [1.0, -1.0E-3, 3]]'
    assert parse_collection(body, media_type) == [
        '{"a": 2.5, "b": [100000.0, 0, 12345678901234567890, NaN, 7]}',
        "[1.0, -0.001, 3]",
    ]
    nested = _numbers(seen)
    assert len(nested) == 9
    assert all(type(n) in (int, float) for n in nested), [type(n) for n in nested]


_SPELLINGS = [
    "1.0",
    "1e5",
    "-0",
    "0",
    "-0.0",
    "12345678901234567890",
    "-12345678901234567890",
    "2.50",
    "-1.0E-3",
    "1E+2",
    "NaN",
    "Infinity",
    "-Infinity",
]


@pytest.mark.parametrize("media_type", ["application/json", None])
def test_top_level_number_spelling_is_still_exact(media_type: str | None) -> None:
    body = "[ " + " ,\n".join(_SPELLINGS) + " ]"
    items = parse_collection(body, media_type)
    assert items == _SPELLINGS
    assert all(type(item) is str for item in items)


@pytest.mark.parametrize("media_type", ["application/json", None])
@pytest.mark.parametrize("window", [(1, 4), (-3, 99), (0, 0)])
def test_top_level_number_spelling_survives_a_window(
    media_type: str | None, window: tuple[int, int]
) -> None:
    body = "[" + ",".join(_SPELLINGS) + "]"
    start, end = window
    assert parse_collection(body, media_type, window=window) == _SPELLINGS[start:end]


@pytest.mark.parametrize(
    "body",
    ["[1 2]", "[1,]", "[1] x", "[,1]", "[1, {]", "[", "[1, 2", '[1, "a]', "[1]]", "[] []"],
)
def test_malformed_declared_array_is_rejected_like_json_loads(body: str) -> None:
    with pytest.raises(json.JSONDecodeError):
        json.loads(body)
    with pytest.raises(CollectionError, match="not valid JSON"):
        parse_collection(body, "application/json")


@pytest.mark.parametrize("window", [None, (0, 1)])
def test_malformed_tail_fails_even_outside_the_window(window: tuple[int, int] | None) -> None:
    with pytest.raises(CollectionError, match="not valid JSON"):
        parse_collection("[1, 2, 3, {]", "application/json", window=window)


@pytest.mark.parametrize("body", ["[]", "[ ]", " [\n] ", "[[]]", '[""]', "[0]"])
def test_small_arrays_match_plain_parse(body: str) -> None:
    expected = [item if isinstance(item, str) else json.dumps(item) for item in json.loads(body)]
    assert parse_collection(body, "application/json") == expected
    assert parse_collection(body) == expected
