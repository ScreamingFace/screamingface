"""Reading one community-cache page (epic OME-1311, spec decision 12).

FEATURE: community cache, available to a local engine (epic OME-1311).

Pinned here: the header is read and handed on before any row; rows are handed on in batches, so
no page is held whole; the trailer's cursor is returned, and `None` after the last page; a page
without its trailer is a cut page (worth retrying) whose rows were still handed on; and anything
that is not a community-cache page is malformed (not worth retrying).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from screamingface._cache.pages import (
    PAGE_SCHEMA,
    CutPage,
    MalformedPage,
    PageHeader,
    walk_page,
)

_REVISIONS = {"parameter_contract": "p1", "openrouter_adapter": "o1"}


def _header(**extra: object) -> str:
    return json.dumps({"schema": PAGE_SCHEMA, "revisions": _REVISIONS, **extra})


def _row(key: str) -> str:
    return json.dumps({"key_hash": key.ljust(64, "0"), "response_json": "{}"})


def _walk(lines: list[str], batch_rows: int = 2) -> tuple[list[object], str | None]:
    seen: list[object] = []
    cursor = walk_page(
        lines, on_header=seen.append, on_rows=lambda rows: seen.append(rows), batch_rows=batch_rows
    )
    return seen, cursor


def test_a_page_hands_on_its_header_then_rows_in_batches_and_returns_next() -> None:
    lines = [_header(remaining=5), _row("a"), _row("b"), _row("c"), '{"next": "cur-1"}']

    seen, cursor = _walk(lines, batch_rows=2)

    assert seen[0] == PageHeader(revisions=_REVISIONS, remaining=5)
    batches = [list(batch) for batch in seen[1:] if isinstance(batch, list)]
    assert [[r["key_hash"][0] for r in batch] for batch in batches] == [["a", "b"], ["c"]]
    assert cursor == "cur-1"


def test_a_batch_also_ends_at_its_byte_bound() -> None:
    # WHY (PR #1433 review): 500 rows of large responses would hold far more than one batch's
    # worth of memory; the byte bound keeps a batch small whatever its rows weigh.
    lines = [_header(), _row("a"), _row("b"), _row("c"), '{"next": null}']
    seen: list[object] = []

    walk_page(
        lines,
        on_header=seen.append,
        on_rows=lambda rows: seen.append(rows),
        batch_rows=500,
        batch_bytes=len(_row("a")) * 2,
    )

    batches = [batch for batch in seen[1:] if isinstance(batch, list)]
    assert [len(batch) for batch in batches] == [2, 1]


def test_the_last_page_returns_none_and_remaining_is_optional() -> None:
    seen, cursor = _walk([_header(), _row("a"), '{"next": null}', ""])

    assert seen[0] == PageHeader(revisions=_REVISIONS, remaining=None)
    assert cursor is None


def test_an_empty_page_has_a_header_and_a_trailer_and_no_rows() -> None:
    seen, cursor = _walk([_header(), '{"next": null}'])

    assert len(seen) == 1
    assert cursor is None


def test_the_header_is_handed_on_before_any_row_is_read() -> None:
    # INVARIANT: a revision mismatch refuses the page before anything is written.
    def refuse(_header: PageHeader) -> None:
        raise RuntimeError("revision mismatch")

    loaded: list[Any] = []
    with pytest.raises(RuntimeError):
        walk_page([_header(), _row("a"), '{"next": null}'], on_header=refuse, on_rows=loaded.append)

    assert loaded == []


@pytest.mark.parametrize(
    "lines",
    [
        [],
        [_header()],
        [_header(), _row("a"), _row("b")],
    ],
)
def test_a_page_without_its_trailer_is_cut(lines: list[str]) -> None:
    loaded: list[Any] = []

    with pytest.raises(CutPage):
        walk_page(lines, on_header=lambda _h: None, on_rows=loaded.extend)

    # WHY the rows still arrive: they are valid entries and loading them twice adds nothing.
    assert len(loaded) == max(0, len(lines) - 1)


@pytest.mark.parametrize(
    "lines",
    [
        ["not json"],
        ["[1, 2]"],
        [json.dumps({"schema": "something-else.v1", "revisions": {}})],
        [json.dumps({"schema": PAGE_SCHEMA})],
        [json.dumps({"schema": PAGE_SCHEMA, "revisions": {"p": 1}})],
        [_header(remaining="many")],
        [_header(remaining=True)],
        [_header(), "not json"],
        [_header(), '{"next": 5}'],
        [_header(), '{"next": ""}'],
        [_header(), '{"next": null}', _row("a")],
    ],
)
def test_anything_but_a_community_cache_page_is_malformed(lines: list[str]) -> None:
    with pytest.raises(MalformedPage):
        walk_page(lines, on_header=lambda _h: None, on_rows=lambda _r: None)


# --- PR #1446 review round 3 ----------------------------------------------------------------------


def test_a_line_after_the_trailer_refuses_the_page_before_its_last_batch_is_handed_on() -> None:
    # INVARIANT: a page whose framing is wrong hands on none of its unflushed rows.
    loaded: list[Any] = []

    with pytest.raises(MalformedPage):
        walk_page(
            [_header(), _row("a"), '{"next": null}', _row("b")],
            on_header=lambda _h: None,
            on_rows=loaded.extend,
        )

    assert loaded == []


def test_the_byte_bound_counts_utf8_bytes_not_characters() -> None:
    # WHY: a row of emoji is four bytes a character; counted in characters, a batch would hold
    # several times its byte bound.
    row = json.dumps({"key_hash": "a", "response_json": "\U0001f600" * 10}, ensure_ascii=False)
    assert len(row.encode()) > len(row)
    seen: list[object] = []

    walk_page(
        [_header(), row, row, row, '{"next": null}'],
        on_header=seen.append,
        on_rows=lambda rows: seen.append(rows),
        batch_rows=500,
        batch_bytes=len(row.encode()) * 2 - 1,
    )

    assert [len(batch) for batch in seen[1:] if isinstance(batch, list)] == [2, 1]
