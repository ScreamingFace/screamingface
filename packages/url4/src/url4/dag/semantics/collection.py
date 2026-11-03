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
import re
from collections.abc import Callable, Iterator, Sequence
from typing import Any, cast

from url4.core.errors import CollectionError

# An iteration's half-open element range (``;iteration.slice``), Python slice semantics.
Window = tuple[int, int]

# The characters JSON itself treats as insignificant whitespace (RFC 8259 §2).
_JSON_WS = frozenset(" \t\n\r")

# --- collection parsing (spec §5.3.7) -----------------------------------------


def parse_collection(
    body: str, media_type: str | None = None, *, window: Window | None = None
) -> list[str]:
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

    ``window`` is the caller's ``(start, end)`` element range, applied with Python
    slice semantics — the result equals ``parse_collection(...)[start:end]``, but
    rows outside the range are never re-serialised. The whole body is still parsed,
    so a malformed element anywhere fails exactly as it would without a window.
    """
    # FEATURE: memory-lean iteration over large fetched collections (330 MB case files).
    # WHY: a large body must not be copied — `str.strip()` on a `FetchedText` (a str
    # subclass) ALWAYS returns a full copy — so the strip bounds are computed, and
    # the stripped text is materialised only by the parsers that need it.
    text = _Text(body)
    if text.lo == text.hi:
        return []
    if media_type is None:
        return _sniff(text, window)
    return _parse_declared(text, media_type, window)


class _Text:
    """A body plus its ``str.strip()`` bounds; the stripped copy is made on demand."""

    def __init__(self, raw: str) -> None:
        self.raw = raw
        lo, hi = 0, len(raw)
        while lo < hi and raw[lo].isspace():
            lo += 1
        while hi > lo and raw[hi - 1].isspace():
            hi -= 1
        self.lo, self.hi = lo, hi
        self._stripped: str | None = None

    @property
    def first(self) -> str:
        return self.raw[self.lo]

    def head(self, n: int) -> str:
        return self.raw[self.lo : min(self.lo + n, self.hi)]

    def stripped(self) -> str:
        if self._stripped is None:
            self._stripped = self.raw[self.lo : self.hi]
        return self._stripped

    def for_json(self) -> str:
        # INVARIANT: same JSON value as `json.loads(body.strip())`. JSON ignores its own
        # whitespace at the ends, so only padding JSON would reject (NBSP, U+2028, …)
        # forces the stripped copy.
        raw = self.raw
        ends = raw[: self.lo] + raw[self.hi :]
        return raw if all(ch in _JSON_WS for ch in ends) else self.stripped()


def _parse_declared(text: _Text, media_type: str, window: Window | None) -> list[str]:
    mime = media_type.split(";", 1)[0].strip().lower()
    if mime == "application/json":
        return _declared_json(text, window)
    parser = _DECLARED.get(mime)
    if parser is None:
        raise CollectionError(f"unsupported content type {mime!r} for collection parsing")
    return _windowed(parser(text.stripped()), window)


def _windowed(items: list[str], window: Window | None) -> list[str]:
    return items if window is None else items[window[0] : window[1]]


def _sniff(text: _Text, window: Window | None) -> list[str]:
    """Best-effort typing for adapters that report no media type.

    Order matters: HTML (a soft-404 signature) and JSON objects fail fast;
    then the structured formats; then multi-line plain text degrades to lines.
    A single-line non-JSON-array body is a scalar, not a collection — sniffing
    refuses to iterate it (spec §5.3.9 non-iterable). Single-row NDJSON is
    indistinguishable from a scalar here; declare ``application/x-ndjson`` to
    iterate one.
    """
    if text.head(512).lstrip().lower().startswith(("<!doctype html", "<html")):
        raise CollectionError(
            "collection source returned an HTML page, not a data file "
            "(JSON array, JSONL, or CSV expected) — the source is likely missing or misrouted"
        )
    _reject_json_object(text)
    # WHY the JSON array goes first and alone: it needs no line split, and splitting a
    # one-line 330 MB array into `_lines` only to discard it copied the whole body.
    array = _try_json_array(text, window)
    if array is not None:
        return array
    body = text.stripped()
    lines = _lines(body)
    for attempt in (_try_jsonl, _try_csv):
        items = attempt(body, lines)
        if items is not None:
            return _windowed(items, window)
    if len(lines) > 1:
        return _windowed(lines, window)
    scalar = text.head(80)
    raise CollectionError(
        f"collection source resolved to a scalar value, not an iterable collection: {scalar!r}"
    )


def _reject_json_object(text: _Text) -> None:
    if text.first != "{":
        return
    try:
        data = json.loads(text.for_json())
    except json.JSONDecodeError:
        return
    if isinstance(data, dict):
        raise CollectionError(
            "iteration over a JSON object is malformed — a collection must be a JSON "
            "array, JSONL, CSV, or line-delimited text (spec §5.3.7)"
        )


def _declared_json(text: _Text, window: Window | None) -> list[str]:
    try:
        data = _loads_items(text.for_json(), window)
    except json.JSONDecodeError as exc:
        raise CollectionError(f"application/json collection is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise CollectionError(
            "iteration over non-array application/json is malformed "
            f"(got {type(data).__name__}; spec §5.3.7)"
        )
    return data


def _declared_ndjson(body: str) -> list[str]:
    items: list[str] = []
    for line in _lines(body):
        try:
            items.append(_line_item(line))
        except json.JSONDecodeError as exc:
            raise CollectionError(f"invalid NDJSON line: {line[:80]!r}") from exc
    return items


def _declared_csv(body: str, delimiter: str = ",") -> list[str]:
    # WHY: a declared table is trusted — no header heuristics, rows as JSON objects —
    # except that a repeated header would silently drop a column, so it is refused.
    try:
        reader = csv.DictReader(io.StringIO(body), delimiter=delimiter)
        rows = list(reader)
    except csv.Error as exc:
        raise CollectionError(f"invalid CSV collection: {exc}") from exc
    if not _unique(reader.fieldnames or []):
        raise CollectionError(f"CSV collection has duplicate headers: {reader.fieldnames!r}")
    return [json.dumps(dict(row)) for row in rows]


def _declared_tsv(body: str) -> list[str]:
    return _declared_csv(body, delimiter="\t")


# `application/json` is dispatched in `_parse_declared` (it parses the unstripped body).
_DECLARED: dict[str, Callable[[str], list[str]]] = {
    "application/x-ndjson": _declared_ndjson,
    "application/ndjson": _declared_ndjson,
    "application/jsonl": _declared_ndjson,
    "text/csv": _declared_csv,
    "text/tab-separated-values": _declared_tsv,
    "text/plain": lambda body: _lines(body),
}


def _lines(body: str) -> list[str]:
    return [line.strip() for line in body.split("\n") if line.strip()]


def _try_json_array(text: _Text, window: Window | None) -> list[str] | None:
    if text.first != "[":
        return None
    try:
        data = _loads_items(text.for_json(), window)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _try_jsonl(_body: str, lines: list[str]) -> list[str] | None:
    # >=2 lines: a single valid-JSON line is indistinguishable from a scalar
    # value, and a scalar must not silently iterate (spec §5.3.9).
    if len(lines) < 2:
        return None
    items: list[str] = []
    for line in lines:
        try:
            items.append(_line_item(line))
        except json.JSONDecodeError:
            return None
    return items


def _try_csv(body: str, lines: list[str]) -> list[str] | None:
    # Only accept a genuine rectangular table (D-4): at least 3 lines, a header of
    # >=2 unique, label-like columns, and every data row matching it exactly. Two
    # comma-bearing lines stay two text rows ("red,green\nblue,yellow"), and ragged
    # prose that merely contains commas falls through to the plain-lines fallback.
    if len(lines) < 3 or not _looks_like_header(lines[0]):
        return None
    try:
        reader = csv.DictReader(io.StringIO(body))
        rows = list(reader)
    except csv.Error:
        return None
    fieldnames = reader.fieldnames or []
    # A real table: >=2 unique columns and every row rectangular (no missing/extra
    # cells, which DictReader signals via a None value or a None key).
    rectangular = (
        len(fieldnames) >= 2
        and _unique(fieldnames)
        and all(None not in row and None not in row.values() for row in rows)
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


def _unique(fieldnames: Sequence[str]) -> bool:
    return len(set(fieldnames)) == len(fieldnames)


# JSON insignificant whitespace (same set as `_JSON_WS`); `*` matches at any position.
_WS_RUN = re.compile(r"[ \t\n\r]*")


def _skip_ws(s: str, idx: int) -> int:
    """The index of the first non-JSON-whitespace character at or after ``idx``."""
    return cast("re.Match[str]", _WS_RUN.match(s, idx)).end()


class _ItemsDecoder(json.JSONDecoder):
    """``json.loads(..., cls=_ItemsDecoder)``: a top-level array comes back as item TEXT.

    # WHY: a top-level number must keep its source spelling (``2.50``), which plain
    # ``json.loads`` loses. Decoding the array element by element gives each element's
    # source span, so its spelling is a slice of the body — in the same single pass, and
    # nested numbers stay the plain ``int``/``float`` the stdlib scanner returns (a
    # per-number carrier made a 2 MiB 0-9 integer grid peak at ~140x its size).
    # INVARIANT: peak ≈ body + ONE parsed element + the kept rows' text: each element is
    # serialised (or, outside the window, dropped) as soon as it is decoded.
    A body that is not an array decodes exactly as ``json.loads`` would.
    """

    def __init__(self, *, window: Window | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._window = window

    def decode(self, s: str, _w: Callable[..., Any] = _WS_RUN.match) -> Any:
        idx = _skip_ws(s, 0)
        if not s.startswith("[", idx):
            return super().decode(s, _w)
        return _element_texts(s, self._elements(s, idx + 1), self._window)

    def _elements(self, s: str, idx: int) -> Iterator[tuple[Any, int, int]]:
        """Each top-level element with its source span; then the array must end the body."""
        idx = _skip_ws(s, idx)
        if s.startswith("]", idx):
            idx += 1
        else:
            while True:
                value, end = self.raw_decode(s, idx)
                yield value, idx, end
                idx = _skip_ws(s, end)
                if s.startswith("]", idx):
                    idx += 1
                    break
                if not s.startswith(",", idx):
                    raise json.JSONDecodeError("Expecting ',' delimiter", s, idx)
                idx = _skip_ws(s, idx + 1)
        end = _skip_ws(s, idx)
        if end != len(s):
            raise json.JSONDecodeError("Extra data", s, end)


def _element_texts(
    s: str, elements: Iterator[tuple[Any, int, int]], window: Window | None
) -> list[str]:
    """The kept elements as text, each serialised (or dropped) as soon as it is decoded."""
    if window is not None and min(window) < 0:
        # A negative bound needs the length: the elements stay parsed until the end.
        held = list(elements)[window[0] : window[1]]
        return [_element_text(value, s, lo, hi) for value, lo, hi in held]
    keep = None if window is None else range(*window)
    return [
        _element_text(value, s, lo, hi)
        for i, (value, lo, hi) in enumerate(elements)
        if keep is None or i in keep
    ]


def _element_text(value: Any, source: str, start: int, end: int) -> str:
    """A top-level element as text; a number is its exact source span (``2.50``)."""
    return source[start:end] if _is_number(value) else _item_to_str(value)


def _loads_items(text: str, window: Window | None) -> Any:
    """``json.loads`` once; a top-level array comes back as its windowed item texts."""
    return json.loads(text, cls=_ItemsDecoder, window=window)


def _line_item(line: str) -> str:
    """One JSONL value as text; a number keeps its source spelling. Raises on bad JSON."""
    item = json.loads(line)
    return line if _is_number(item) else _item_to_str(item)


def _is_number(item: object) -> bool:
    return isinstance(item, int | float) and not isinstance(item, bool)


def _item_to_str(item: object) -> str:
    return item if isinstance(item, str) else json.dumps(item)


__all__ = ["parse_collection"]
