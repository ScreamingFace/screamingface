"""Extract operators: one member text -> one raw value, or a status (OME-1289, E4a).

FEATURE: a member's free text becomes one candidate answer, deterministically.
STORY: as an author of a majority-vote Candidate, I choose how the answer is read from a reply.

Mental model: a reader with a ruler. ``last_number`` and ``boxed`` look only at a bounded stretch
of text (the last 128 characters ending at the last digit; 4096 characters after the last box), so
a hostile 1 MiB reply costs them the same as a short one. The other three make one linear pass
over the text at C speed (a strip, a ``json.loads`` or a ``rfind``).

INVARIANT: each extractor is pure and O(n); this module holds no mutable state.
WHY ASCII digits only: ``[0-9]``, never ``\\d``.
AIDEV-NOTE: the scan limits are v1 behavior pinned by the golden fixtures. A change is a new
``@version``, never an edit.
"""

from __future__ import annotations

import re
from types import MappingProxyType

from screamingface_engine.combine.ports import (
    FIELD_PATH,
    OpArgs,
    OperatorDescriptor,
    SpecInvalid,
    StageResult,
    accepted,
    canonical_json,
    decode_json_reply,
    rejected,
    walk_field_path,
)

_DIGITS = "0123456789"
_LAST_NUMBER_WINDOW = 128
# WHY the whole comma run: grouping is judged by numeric@1, so `1,00,000` is one token (and not
# 000) and `1,23` stays `1,23` (not_numeric) instead of silently reading as 23.
_NUMBER = re.compile(r"[-\u2212]?[0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?")
_BOX_OPEN = "\\boxed{"
_BOX_SCAN_CHARS = 4096
_BOX_MAX_DEPTH = 8


def _found(value: str) -> StageResult:
    """A raw value that is blank after ``strip()`` is ``empty``; otherwise it is kept as is."""
    return accepted(value) if value.strip() else rejected("empty")


def last_number(text: str, args: OpArgs, /) -> StageResult:
    """Last number token: sign, thousands separators and decimals; read from a 128-char window."""
    end = max(text.rfind(digit) for digit in _DIGITS)
    if end < 0:
        return rejected("empty")
    window = text[max(0, end - (_LAST_NUMBER_WINDOW - 1)) : end + 1]
    last = None
    for last in _NUMBER.finditer(window):
        pass
    return rejected("empty") if last is None else _found(last.group(0))


def _box_content(body: str) -> str | None:
    """The text up to the brace that closes the box, or None (unclosed, or deeper than 8)."""
    depth = 1
    for offset, char in enumerate(body):
        depth += (char == "{") - (char == "}")
        if depth > _BOX_MAX_DEPTH:
            return None
        if depth == 0:
            return body[:offset]
    return None


def boxed(text: str, args: OpArgs, /) -> StageResult:
    """Content of the last ``\\boxed{}``; at most 4096 chars scanned and 8 braces deep."""
    start = text.rfind(_BOX_OPEN)
    if start < 0:
        return rejected("empty")
    begin = start + len(_BOX_OPEN)
    content = _box_content(text[begin : begin + _BOX_SCAN_CHARS])
    return rejected("empty") if content is None else _found(content)


def _check_json_field_args(args: OpArgs) -> None:
    path = args.get("path")
    if set(args) != {"path"} or not isinstance(path, str) or FIELD_PATH.fullmatch(path) is None:
        raise SpecInvalid('json_field@1 takes exactly {"path": <field path>}')


def _field_text(value: object) -> StageResult:
    if value is None or isinstance(value, str):
        return _found(value or "")
    try:
        return accepted(canonical_json(value))
    except ValueError:
        # a JSON number too big for a float (1e999) decodes to inf, which has no canonical form
        return rejected("not_json")


def json_field(text: str, args: OpArgs, /) -> StageResult:
    """One JSON field, read by a url4 field path (``a.b[0]``)."""
    try:
        decoded = decode_json_reply(text)
    except ValueError:
        return rejected("not_json")
    found, value = walk_field_path(decoded, str(args["path"]))
    return _field_text(value) if found else rejected("field_missing")


def last_line(text: str, args: OpArgs, /) -> StageResult:
    """Last non-empty line; v1 line breaks are only ``\\n`` and ``\\r``."""
    stripped = text.rstrip()
    if not stripped:
        return rejected("empty")
    start = max(stripped.rfind("\n"), stripped.rfind("\r"))
    return _found(stripped[start + 1 :].strip())


def whole(text: str, args: OpArgs, /) -> StageResult:
    """The whole text, kept as it is."""
    return _found(text)


OPERATORS: tuple[OperatorDescriptor, ...] = (
    OperatorDescriptor("last_number", 1, "extract", "Last number token.", last_number),
    OperatorDescriptor("boxed", 1, "extract", "Content of the last \\boxed{}.", boxed),
    OperatorDescriptor(
        "json_field",
        1,
        "extract",
        "One JSON field, read by a url4 field path.",
        json_field,
        # AIDEV-NOTE: the top level is read-only; the nested "properties" stays a plain dict because
        # ports.catalog_entry deep-copies the schema and a mappingproxy cannot be deep-copied.
        args_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ("path",),
                "additionalProperties": False,
            }
        ),
        check_args=_check_json_field_args,
    ),
    OperatorDescriptor("last_line", 1, "extract", "Last non-empty line.", last_line),
    OperatorDescriptor("whole", 1, "extract", "The whole text.", whole),
)

__all__ = ["OPERATORS"]
