"""A6 [F3-6] — collection parsing keeps the row count and the row text (Spec B §5.3.7, D-4).

Owner decision D-4: a declared content type wins; sniffing runs only when no type is
declared, and the CSV sniff needs at least 3 lines and unique, non-empty headers.
A scalar element keeps its source spelling (``2.50`` stays ``2.50``).
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from url4.core.errors import CollectionError
from url4.dag.semantics.collection import parse_collection


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # Two comma-bearing lines are two text rows, not a one-row table.
        ("red,green\nblue,yellow", ["red,green", "blue,yellow"]),
        # A two-line body with a duplicate "header" is two text rows: no column is dropped.
        ("a,a\n1,2", ["a,a", "1,2"]),
        # Numbers keep their source spelling.
        ("2.50\n3.10", ["2.50", "3.10"]),
        ("1e3\n2", ["1e3", "2"]),
        ("[2.50, 1e3, 7]", ["2.50", "1e3", "7"]),
        ("[NaN, 1]", ["NaN", "1"]),
    ],
)
def test_sniffed_rows_keep_count_and_text(body, expected):
    assert parse_collection(body) == expected


def test_three_line_table_with_unique_headers_is_csv():
    # D-4 as written: >=3 lines and unique, non-empty headers make a table. The header
    # row is not checked beyond that, so a data-looking first line still becomes the header.
    rows = parse_collection("Paris,France\nTokyo,Japan\nLima,Peru")
    assert [json.loads(r) for r in rows] == [
        {"Paris": "Tokyo", "France": "Japan"},
        {"Paris": "Lima", "France": "Peru"},
    ]


def test_three_line_body_with_duplicate_headers_is_not_csv():
    assert parse_collection("a,a\n1,2\n3,4") == ["a,a", "1,2", "3,4"]


@pytest.mark.parametrize("media_type", ["text/csv", "text/tab-separated-values"])
def test_declared_table_with_duplicate_headers_is_refused(media_type):
    sep = "\t" if "tab" in media_type else ","
    body = f"a{sep}a\n1{sep}2"
    with pytest.raises(CollectionError, match="duplicate"):
        parse_collection(body, media_type)


@pytest.mark.parametrize(
    "media_type", ["application/jsonl", "application/x-ndjson", "application/ndjson"]
)
def test_declared_jsonl_is_ndjson(media_type):
    body = '{"a": 1}\n"x"\n2.50'
    assert parse_collection(body, media_type) == ['{"a": 1}', "x", "2.50"]


def test_declared_type_wins_over_the_sniff():
    # Declared text/plain: two comma lines stay two lines even with three of them.
    body = "a,b\n1,2\n3,4"
    assert parse_collection(body, "text/plain") == ["a,b", "1,2", "3,4"]


def test_json_number_and_string_elements_both_render_as_text():
    # The list[str] row contract carries text, not JSON types: 0 and "0" are both "0".
    # Pinned so a change to the row contract is a visible, reviewed decision.
    assert parse_collection("[0]") == ["0"]
    assert parse_collection('["0"]') == ["0"]


_PROSE_LINE = st.text(alphabet="abcxyz ,", min_size=1, max_size=12).filter(
    lambda s: s.strip() != "" and s.strip()[0] not in "[{<"
)


@given(st.lists(_PROSE_LINE, min_size=2, max_size=2))
def test_two_text_lines_give_two_rows(lines):
    # The audit's sniff law: N text lines give N items. With 2 lines the CSV sniff never
    # applies (D-4), so the row count and text survive.
    body = "\n".join(lines)
    assert parse_collection(body) == [line.strip() for line in lines]
