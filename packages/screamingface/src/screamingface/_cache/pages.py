"""Read one community-cache page, line by line (spec decision 12).

A page is NDJSON: a header line (`schema`, `revisions`, and `remaining` when the caller sent
`count=true`), one line per row, and a trailer line carrying only `next`. The reader never holds
the page: rows are handed on in batches as they arrive, so a page of the heaviest model (~235 MB
of rows) costs one batch of memory.

INVARIANT: the header is handed on before any row, so a revision mismatch refuses the page before
anything is written locally.
WHY rows of a cut page are still handed on: every row is an independent, valid cache entry and
loading is idempotent, so they are harmless; only the cursor must not advance past a page that
did not end with its trailer.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

PAGE_SCHEMA: Final = "screamingface.cache-page.v1"
BATCH_ROWS: Final = 500


@dataclass(frozen=True, slots=True)
class PageHeader:
    revisions: Mapping[str, str]
    remaining: int | None


class CutPage(Exception):
    """The page ended without its trailer: it was cut off in transit. Worth retrying."""


class MalformedPage(Exception):
    """The page is not a community-cache page this client can read. Not worth retrying."""


def walk_page(
    lines: Iterable[str],
    *,
    on_header: Callable[[PageHeader], None],
    on_rows: Callable[[list[dict[str, Any]]], None],
    batch_rows: int = BATCH_ROWS,
) -> str | None:
    """Read one page; return its `next` cursor (None after the last page)."""
    stream = (line for line in lines if line.strip())
    first = next(stream, None)
    if first is None:
        raise CutPage("the page ended before its header")
    on_header(_header(_object(first)))
    batch: list[dict[str, Any]] = []
    for line in stream:
        value = _object(line)
        if set(value) == {"next"}:
            _flush(batch, on_rows)
            if next(stream, None) is not None:
                raise MalformedPage("a line followed the page trailer")
            return _cursor(value["next"])
        batch.append(value)
        if len(batch) >= batch_rows:
            _flush(batch, on_rows)
    _flush(batch, on_rows)
    raise CutPage("the page ended before its trailer")


def _flush(batch: list[dict[str, Any]], on_rows: Callable[[list[dict[str, Any]]], None]) -> None:
    if batch:
        on_rows(list(batch))
        batch.clear()


def _object(line: str) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except ValueError as exc:
        raise MalformedPage("a page line is not JSON") from exc
    if not isinstance(value, dict):
        raise MalformedPage("a page line is not a JSON object")
    return value


def _header(value: dict[str, Any]) -> PageHeader:
    if value.get("schema") != PAGE_SCHEMA:
        raise MalformedPage(f"not a {PAGE_SCHEMA} page")
    revisions = value.get("revisions")
    if not isinstance(revisions, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in revisions.items()
    ):
        raise MalformedPage("the page header carries no revisions")
    remaining = value.get("remaining")
    if remaining is not None and (not isinstance(remaining, int) or isinstance(remaining, bool)):
        raise MalformedPage("the page header's remaining count is not an integer")
    return PageHeader(revisions=revisions, remaining=remaining)


def _cursor(value: object) -> str | None:
    if value is None or (isinstance(value, str) and value):
        return value
    raise MalformedPage("the page trailer's next cursor is not a string")


__all__ = ["BATCH_ROWS", "PAGE_SCHEMA", "CutPage", "MalformedPage", "PageHeader", "walk_page"]
