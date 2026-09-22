"""Collection parsing (spec §5.3.7): fetched text → iterable string items.

An ENGINE-side runtime decoder, not a language (text ↔ AST) concern and not an
I/O-port concern. The ``*`` iteration (:class:`~url4.dag.nodes.MapNode`) and the
``;expand`` operator (:class:`~url4.dag.nodes.ExpandNode`) are the only
consumers, and both are engine nodes. The module is stdlib-only plus the error
hierarchy, so it is a leaf inside the engine: it imports no adapter and no
sibling engine module.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable

from url4.core.errors import CollectionError

# --- collection parsing (spec §5.3.7) -----------------------------------------


def parse_collection(body: str, media_type: str | None = None) -> list[str]:
    """Parse ``body`` into a list of string items (spec §5.3.7).

    With a declared ``media_type`` the matching strategy is applied strictly
    (an undeclarable body is the source's fault, not the parser's guess);
    without one the type is sniffed conservatively. Structured items (objects,
    CSV rows) are JSON-encoded so downstream callers can ``json.loads``
    individual fields.

    An empty body is an empty collection — iteration over it succeeds with
    zero elements (spec §5.3.9). A value that cannot be parsed into elements
    (a scalar, a JSON object, an HTML page) raises :class:`CollectionError`
    with code ``malformed_source``.
    """
    body = body.strip()
    if not body:
        return []
    if media_type is None:
        return _sniff(body)
    return _parse_declared(body, media_type)


def _parse_declared(body: str, media_type: str) -> list[str]:
    mime = media_type.split(";", 1)[0].strip().lower()
    parser = _DECLARED.get(mime)
    if parser is None:
        raise CollectionError(f"unsupported content type {mime!r} for collection parsing")
    return parser(body)


def _sniff(body: str) -> list[str]:
    """Best-effort typing for adapters that report no media type.

    Order matters: HTML (a soft-404 signature) and JSON objects fail fast;
    then the structured formats; then multi-line plain text degrades to lines.
    A single-line non-JSON-array body is a scalar, not a collection — sniffing
    refuses to iterate it (spec §5.3.9 non-iterable). Single-row NDJSON is
    indistinguishable from a scalar here; declare ``application/x-ndjson`` to
    iterate one.
    """
    if body[:512].lstrip().lower().startswith(("<!doctype html", "<html")):
        raise CollectionError(
            "collection source returned an HTML page, not a data file "
            "(JSON array, JSONL, or CSV expected) — the source is likely missing or misrouted"
        )
    _reject_json_object(body)
    lines = _lines(body)
    for attempt in (_try_json_array, _try_jsonl, _try_csv):
        items = attempt(body, lines)
        if items is not None:
            return items
    if len(lines) > 1:
        return lines
    raise CollectionError(
        f"collection source resolved to a scalar value, not an iterable collection: {body[:80]!r}"
    )


def _reject_json_object(body: str) -> None:
    if not body.startswith("{"):
        return
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return
    if isinstance(data, dict):
        raise CollectionError(
            "iteration over a JSON object is malformed — a collection must be a JSON "
            "array, JSONL, CSV, or line-delimited text (spec §5.3.7)"
        )


def _declared_json(body: str) -> list[str]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CollectionError(f"application/json collection is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise CollectionError(
            "iteration over non-array application/json is malformed "
            f"(got {type(data).__name__}; spec §5.3.7)"
        )
    return [_item_to_str(item) for item in data]


def _declared_ndjson(body: str) -> list[str]:
    items: list[str] = []
    for line in _lines(body):
        try:
            items.append(_item_to_str(json.loads(line)))
        except json.JSONDecodeError as exc:
            raise CollectionError(f"invalid NDJSON line: {line[:80]!r}") from exc
    return items


def _declared_csv(body: str, delimiter: str = ",") -> list[str]:
    # WHY: a declared table is trusted — no header heuristics, rows as JSON objects.
    try:
        rows = list(csv.DictReader(io.StringIO(body), delimiter=delimiter))
    except csv.Error as exc:
        raise CollectionError(f"invalid CSV collection: {exc}") from exc
    return [json.dumps(dict(row)) for row in rows]


def _declared_tsv(body: str) -> list[str]:
    return _declared_csv(body, delimiter="\t")


_DECLARED: dict[str, Callable[[str], list[str]]] = {
    "application/json": _declared_json,
    "application/x-ndjson": _declared_ndjson,
    "text/csv": _declared_csv,
    "text/tab-separated-values": _declared_tsv,
    "text/plain": lambda body: _lines(body),
}


def _lines(body: str) -> list[str]:
    return [line.strip() for line in body.split("\n") if line.strip()]


def _try_json_array(body: str, _lines_unused: list[str]) -> list[str] | None:
    if not body.startswith("["):
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    return [_item_to_str(item) for item in data] if isinstance(data, list) else None


def _try_jsonl(_body: str, lines: list[str]) -> list[str] | None:
    # >=2 lines: a single valid-JSON line is indistinguishable from a scalar
    # value, and a scalar must not silently iterate (spec §5.3.9).
    if len(lines) < 2:
        return None
    items: list[str] = []
    for line in lines:
        try:
            items.append(_item_to_str(json.loads(line)))
        except json.JSONDecodeError:
            return None
    return items


def _try_csv(body: str, lines: list[str]) -> list[str] | None:
    # Only accept a genuine rectangular table: a comma-bearing header with >=2
    # columns and every data row matching it exactly. Ragged prose that merely
    # contains commas (e.g. "What is 2, 3?\nName a color, please") is rejected and
    # falls through to the plain-lines fallback rather than being mangled.
    if len(lines) < 2 or "," not in lines[0] or not _looks_like_header(lines[0]):
        return None
    try:
        reader = csv.DictReader(io.StringIO(body))
        rows = list(reader)
    except csv.Error:
        return None
    fieldnames = reader.fieldnames or []
    # A real table: >=2 columns and every row rectangular (no missing/extra cells,
    # which DictReader signals via a None value or a None key).
    rectangular = len(fieldnames) >= 2 and all(
        None not in row and None not in row.values() for row in rows
    )
    return [json.dumps(dict(row)) for row in rows] if rows and rectangular else None


def _looks_like_header(line: str) -> bool:
    """True when ``line`` reads like column names, not comma-bearing prose.

    Even column counts alone don't separate a real 2-column table from two lines
    of prose that each happen to contain one comma (``What is your name, please?``
    → columns ``["What is your name", " please?"]``, which passes a naive
    rectangular check). Column *names* are short labels: non-empty and single
    token. A field carrying interior spaces or sentence punctuation marks the
    "header" as prose, so the collection falls through to the plain-lines
    fallback. Trade-off: a genuine table with multi-word headers
    (``first name,last name``) degrades to plain lines rather than being parsed —
    acceptable, since silent prose-mangling is the worse failure.
    """
    fields = [f.strip() for f in line.split(",")]
    return all(f and " " not in f and f[-1] not in "?!." for f in fields)


def _item_to_str(item: object) -> str:
    return item if isinstance(item, str) else json.dumps(item)


__all__ = ["parse_collection"]
