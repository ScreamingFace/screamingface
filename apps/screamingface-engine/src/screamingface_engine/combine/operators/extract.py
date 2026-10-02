"""Extract operators: one member text -> one raw value, or a status (OME-1289, E4a).

FEATURE: a member's free text becomes one candidate answer, deterministically.
STORY: as an author of a majority-vote Candidate, I choose how the answer is read from a reply.

Mental model: a reader with a ruler. ``last_number`` and ``boxed`` look only at a bounded stretch
of text (the last 128 characters ending at the last digit; 4096 characters after the last box), so
a hostile 1 MiB reply costs them the same as a short one. The other three make one linear pass
over the text at C speed (a strip, a ``json.loads`` or a ``rfind``).

regex reads only the last 1024 characters under a static backtracking ban. The two Inspect rules
follow the grader exactly: they are linear in the text but slower than the rest on adversarial
input (digit-free prose is a C-speed exit; a text of many ``1a`` words is about 1 s per MiB), and
the boxed step is linear (the upstream regex is quadratic).

INVARIANT: each extractor is pure and O(n); this module holds no mutable state.
WHY ASCII digits only: ``[0-9]``, never ``\\d``.
AIDEV-NOTE: the scan limits are v1 behavior pinned by the golden fixtures. A change is a new
``@version``, never an edit.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import cast

from screamingface_engine.combine.operators._inspect_vendor import (
    _find_last_substantive_line,
    _is_number,
    strip_numeric_punctuation,
)
from screamingface_engine.combine.operators._regex_ban import backtracking_shape
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


_REGEX_WINDOW = 1024  # characters; the scan reads text[-_REGEX_WINDOW:]
_REGEX_MAX_PATTERN = 256
_REGEX_ARGS = frozenset({"pattern", "group", "occurrence", "ignore_case"})


def _regex_flags(args: OpArgs) -> int:
    return re.IGNORECASE if args.get("ignore_case") else 0


def _check_regex_keys(args: OpArgs) -> None:
    if "pattern" not in args or not set(args) <= _REGEX_ARGS:
        raise SpecInvalid(
            "regex@1 needs a pattern and takes only pattern, group, occurrence and ignore_case"
        )


def _check_regex_values(args: OpArgs) -> None:
    pattern = args["pattern"]
    if not isinstance(pattern, str) or not 1 <= len(pattern) <= _REGEX_MAX_PATTERN:
        raise SpecInvalid(
            f"regex@1 pattern must be a string of 1 to {_REGEX_MAX_PATTERN} characters"
        )
    if not isinstance(args.get("ignore_case", False), bool):
        raise SpecInvalid("regex@1 ignore_case must be a boolean")
    if args.get("occurrence", "last") not in ("last", "first"):
        raise SpecInvalid("regex@1 occurrence must be last or first")


def _compile(args: OpArgs) -> re.Pattern[str]:
    try:
        return re.compile(str(args["pattern"]), _regex_flags(args))
    except (re.error, OverflowError):
        raise SpecInvalid("regex@1 pattern does not compile") from None


def _group_exists(group: object, compiled: re.Pattern[str]) -> bool:
    if isinstance(group, str):
        return group in compiled.groupindex
    return isinstance(group, int) and not isinstance(group, bool) and 0 <= group <= compiled.groups


def _check_regex_args(args: OpArgs) -> None:
    _check_regex_keys(args)
    _check_regex_values(args)
    compiled = _compile(args)
    shape = backtracking_shape(str(args["pattern"]))
    if shape is not None:
        raise SpecInvalid(f"regex@1 pattern has a banned backtracking shape: {shape}")
    if not _group_exists(args.get("group", 0), compiled):
        raise SpecInvalid("regex@1 group must name a group of the pattern")


def _last_match(compiled: re.Pattern[str], window: str) -> re.Match[str] | None:
    last = None
    for last in compiled.finditer(window):
        pass
    return last


def regex(text: str, args: OpArgs, /) -> StageResult:
    """The chosen group of the last (or first) match in the last 1024 characters."""
    compiled = _compile(args)  # re keeps its own cache of compiled patterns
    window = text[-_REGEX_WINDOW:]
    first = args.get("occurrence", "last") == "first"
    match = compiled.search(window) if first else _last_match(compiled, window)
    if match is None:
        return rejected("no_match")
    value = match.group(cast("str | int", args.get("group", 0)))
    return rejected("empty") if value is None else _found(value)


_ASCII_DIGIT = re.compile(r"[0-9]")
_BOX = "\\boxed{"


def _inspect_number_word(value: str) -> str | None:
    """The value side of inspect_ai match_str(location="end", numeric=True) (SP/inspect_ai/
    scorer/_common.py:49-73): strip, casefold, strip_numeric_punctuation, split on \\s+, then the
    LAST word that _is_number accepts. Returns the cleaned word (not normalized), or None."""
    cleaned = strip_numeric_punctuation(value.strip().casefold())
    # WHY sound: an ASCII word parses as a finite number only with an ASCII digit (float()
    # needs one; every other unicode_number_to_float path needs a non-ASCII character).
    if cleaned.isascii() and _ASCII_DIGIT.search(cleaned) is None:
        return None
    words = re.split(r"\s+", cleaned)
    words.reverse()
    return next((word for word in words if _is_number(word)), None)


def _unbox(line: str) -> str:
    """Linear, exact equivalent of remove_boxed_from_ans on ONE splitlines() line (no "\\n"):
    the greedy (.+) runs to the line's last "}", so the first box that ends before it is opened."""
    start, end = line.find(_BOX), line.rfind("}")
    if start < 0 or end < start + len(_BOX) + 1:
        return line
    return line[:start] + line[start + len(_BOX) : end] + line[end + 1 :]


def inspect_number(text: str, args: OpArgs, /) -> StageResult:
    """The last number word of the text, by inspect-ai's numeric ``match``."""
    word = _inspect_number_word(text)
    return rejected("empty") if word is None else _found(word)


def inspect_aime(text: str, args: OpArgs, /) -> StageResult:
    """The AIME answer: the last substantive line, boxed answer unwrapped, then the number rule."""
    if not text.strip().splitlines():
        return rejected("empty")
    word = _inspect_number_word(_unbox(_find_last_substantive_line(text)))
    return rejected("empty") if word is None else _found(word)


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
    OperatorDescriptor(
        "regex",
        1,
        "extract",
        "One regex group from the last 1024 characters.",
        regex,
        args_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "minLength": 1, "maxLength": 256},
                    "group": {"type": ("integer", "string")},
                    "occurrence": {"enum": ("last", "first")},
                    "ignore_case": {"type": "boolean"},
                },
                "required": ("pattern",),
                "additionalProperties": False,
            }
        ),
        check_args=_check_regex_args,
    ),
    OperatorDescriptor(
        "inspect_number",
        1,
        "extract",
        "The last number word, by inspect-ai 0.3.263 match(numeric=True).",
        inspect_number,
    ),
    OperatorDescriptor(
        "inspect_aime",
        1,
        "extract",
        "The AIME answer, by inspect-evals 0.20.0 aime_scorer.",
        inspect_aime,
    ),
    OperatorDescriptor("last_line", 1, "extract", "Last non-empty line.", last_line),
    OperatorDescriptor("whole", 1, "extract", "The whole text.", whole),
)

__all__ = ["OPERATORS"]
