"""Pure helpers for the fan-out/reduce and collection strategies.

These functions carry no I/O and no dependency on the execution layer — they
format reducer input and perform the string-level ``$``-substitutions. The
executable nodes in :mod:`url4.dag` compose them with the
:class:`~url4.io.layer.IOLayer` port.

Variable substitution
----------------------
- ``$name`` / ``$N`` — replaced from the :class:`~url4.core.context.Context`
  (:func:`substitute_env_vars`). Unknown names are left verbatim.
- ``$item`` — replaced per collection row (:func:`substitute_item`).
- Field paths (spec §5.3.4 / §6.2 / §8.2): every reference accepts nested dot
  segments and ``[N]`` index segments (``$data.author.name``,
  ``$item.tags[0]``, ``$1.reviews[0].text``). Traversal is left-to-right over
  the JSON-decoded referenced value. Error handling is mode-dependent
  (spec §5.3.4.1): the lenient/LLM default substitutes ``""`` for a missing
  field, type error, or out-of-bounds index; ``strict=True`` (RDS mode) raises
  :class:`~url4.core.errors.ScopeError` with code ``malformed_source``.
- ``$$`` → literal ``$``. Handled once, in :func:`substitute_env_vars`; the
  ``(?<!\\$)`` lookbehind in :func:`substitute_item` keeps ``$$item`` from being
  captured as ``$item`` before the escape collapses.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from url4.core.context import Context
from url4.core.errors import ErrorCode, ScopeError

# One field-path grammar everywhere (spec §8 field-path production): dot
# segments and non-negative, no-leading-zero index segments.
# INVARIANT: every pattern below compiles with re.ASCII — the ABNF's ALPHA is
# ASCII, and Python's `\w` would otherwise admit Unicode identifiers that the
# parser (also ASCII-anchored) never produces, desynchronising the two
# (`OME-504`).
_PATH = r"(?:\.[a-zA-Z_]\w*|\[(?:0|[1-9]\d*)\])"

# $$ (escape) | $name (letter-led binding) or $N (1-based positional slot),
# each with an optional field path.
_ENV_VAR_RE = re.compile(rf"\$\$|\$([a-zA-Z_]\w*|[0-9]+)({_PATH}*)", re.ASCII)
# $name only, no path — the fan-out reducer instruction's reference form.
_NAME_ONLY_RE = re.compile(r"\$\$|\$([a-zA-Z_]\w*)", re.ASCII)
# $item with a non-empty field path ($item.f, $item[0], $item.a[1].b …).
_ITEM_PATH_RE = re.compile(rf"(?<!\$)\$item({_PATH}+)", re.ASCII)
# Bare $item: not a longer identifier ($items) nor the head of a field path.
_ITEM_BARE_RE = re.compile(rf"(?<!\$)\$item(?!\w)(?!{_PATH})", re.ASCII)
_SEGMENT_RE = re.compile(r"\.([a-zA-Z_]\w*)|\[(\d+)\]", re.ASCII)


@dataclass
class FanoutResponse:
    """One fan-out response paired with its source name/weight (from the call node)."""

    text: str
    name: str | None = None
    weight: float | None = None


# --- field-path traversal (spec §5.3.4) ----------------------------------------

_MISSING = object()  # lenient-mode sentinel: substitute "" for the reference


def _path_segments(path_text: str) -> list[str | int]:
    """Decode ``.field`` / ``[N]`` segments from a matched path suffix."""
    return [
        m.group(1) if m.group(1) is not None else int(m.group(2))
        for m in _SEGMENT_RE.finditer(path_text)
    ]


def _step(value: object, seg: str | int) -> object:
    """One traversal step, or ``_MISSING`` on any §5.3.4.1 error condition."""
    if isinstance(seg, str):
        found = value.get(seg, _MISSING) if isinstance(value, dict) else _MISSING
    else:
        found = value[seg] if isinstance(value, list) and seg < len(value) else _MISSING
    return found


def resolve_field_path(value_text: str, path_text: str, *, strict: bool, ref: str) -> str:
    """Traverse ``path_text`` into the JSON-decoded ``value_text`` (spec §5.3.4.1).

    A value that does not decode as JSON is a scalar — any segment on it is a
    type error. All error conditions share one rule: lenient mode substitutes
    ``""``; strict mode raises :class:`ScopeError` (code ``malformed_source``)
    naming the failing segment.
    """
    if not path_text:
        return value_text
    try:
        value: object = json.loads(value_text)
    except (json.JSONDecodeError, TypeError):
        value = value_text  # scalar: field/index access on it is a type error
    for seg in _path_segments(path_text):
        value = _step(value, seg)
        if value is _MISSING:
            return _fail_segment(seg, path_text, strict=strict, ref=ref)
    return value if isinstance(value, str) else json.dumps(value)


def _fail_segment(seg: str | int, path_text: str, *, strict: bool, ref: str) -> str:
    if not strict:
        return ""
    seg_text = f".{seg}" if isinstance(seg, str) else f"[{seg}]"
    raise ScopeError(
        f"field path '{ref}{path_text}' failed at segment '{seg_text}' "
        "(missing field, wrong type, or index out of bounds; spec §5.3.4.1)",
        code=ErrorCode.MALFORMED_SOURCE,
    )


# --- JSON-blob escaping ----------------------------------------------------------


def _json_blob_spans(text: str) -> list[tuple[int, int]]:
    """Spans of every top-level ``{...}`` blob, nesting included.

    A brace-depth scan rather than a regex, so a value landing inside a *deeply*
    nested JSON object (``{"a": {"b": {"c": "$x"}}}``) is still recognised as
    in-blob and escaped — a bounded regex only balances a fixed nesting depth.

    Braces that appear **inside a JSON string literal**
    (``{"k": "a{b $x"}``) are skipped, so a ``{`` in a string value can't inflate
    the depth count and leave a real blob unrecognised — which would skip escaping
    and insert a value raw, breaking the reducer's later ``json.loads``. A ``"``
    is honored as a string delimiter only when its closing ``"`` exists
    (``\"`` escapes respected); an unterminated ``"`` in non-JSON text is treated
    as an ordinary character so trailing braces still count, preserving the
    prior behavior for malformed input.
    """
    # A template with no brace has no blob, and the scan below is O(len(text))
    # Python-level work on every substitution — every node resolve, every map
    # row. Brace-free prompts are the common case, so check before scanning.
    if "{" not in text:
        return []
    spans: list[tuple[int, int]] = []
    depth = 0
    start = -1
    for i, ch in _non_string_chars(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                spans.append((start, i + 1))
    return spans


def _non_string_chars(text: str):
    """Yield ``(index, char)`` for every char not inside a terminated JSON string.

    A ``"`` whose closing ``"`` exists (``\\`` and ``\"`` escapes honored) is
    skipped wholesale, so a ``{``/``}`` inside a JSON string value can't perturb a
    brace-depth scan. An unterminated ``"`` in non-JSON text is yielded as an
    ordinary char, so braces after it still count — preserving the prior behavior
    for malformed input (no behavior change where there's no real string).
    """
    i = 0
    n = len(text)
    while i < n:
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            if j < n:
                i = j + 1
                continue
        yield i, text[i]
        i += 1


def _in_json_blob(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in spans)


def _escape_for_json_string(s: str) -> str:
    return json.dumps(s)[1:-1]


def _escape_for_json(value: str, pos: int, blob_spans: list[tuple[int, int]]) -> str:
    """Escape ``value`` for a JSON string only when ``pos`` falls inside a blob."""
    return _escape_for_json_string(value) if _in_json_blob(pos, blob_spans) else value


# --- fan-out reduce formatting ------------------------------------------------------


def build_reducer_input(responses: list[FanoutResponse], instruction: str) -> str:
    """Format N fan-out responses + the reducer instruction as labeled sections.

    Unlabeled by default (``[Response 1]``, …); when names/weights are present
    they head each section (``claude (weight=0.6):``) so the reducer can weight
    and reference responses individually.
    """
    has_labels = any(r.name is not None for r in responses)
    parts: list[str] = []
    for i, entry in enumerate(responses, 1):
        parts.append(_response_header(entry, i, has_labels))
        parts.append(entry.text.strip())
        parts.append("")
    parts.append("[Instruction]")
    parts.append(instruction)
    return "\n".join(parts)


def _response_header(entry: FanoutResponse, index: int, has_labels: bool) -> str:
    if not (has_labels and entry.name):
        return f"[Response {index}]"
    if entry.weight is not None:
        return f"{entry.name} (weight={entry.weight:g}):"
    return f"{entry.name}:"


def substitute_response_vars(instruction: str, entries: list[FanoutResponse]) -> str:
    """Replace ``$name`` in ``instruction`` with each named response's text.

    A single regex pass (mirroring :func:`substitute_env_vars`) so a name that is
    a prefix of another (``$claude`` vs ``$claude2``) can't corrupt the longer
    reference, and values landing inside a ``{...}`` JSON blob are escaped.
    Response texts are opaque prose, so field paths are not interpreted here —
    a ``.suffix`` after a name stays literal text.
    """
    if not instruction or "$" not in instruction:
        return instruction
    by_name = {e.name: e.text.strip() for e in entries if e.name is not None}
    if not by_name:
        return instruction
    blob_spans = _json_blob_spans(instruction)

    def _replace(m: re.Match) -> str:
        name = m.group(1)
        if name is None or name not in by_name:  # "$$" or unknown name → verbatim
            return m.group(0)
        return _escape_for_json(by_name[name], m.start(), blob_spans)

    return _NAME_ONLY_RE.sub(_replace, instruction)


# --- reference discovery + substitution -----------------------------------------------


def find_references(text: str) -> set[str]:
    """Return the ``$name`` / ``$N`` base names referenced in ``text``.

    Field-path suffixes are stripped (``$data.tags[0]`` → ``data``) — the DAG
    compiler derives dependency edges from base names; traversal happens at
    substitution time. ``$$`` escapes, ``$item`` (owned by
    :func:`substitute_item`), and ``$current`` (bound per broadcast merge) are
    not references.
    """
    if "$" not in text:
        return set()
    return {
        m.group(1)
        for m in _ENV_VAR_RE.finditer(text)
        if m.group(1) and m.group(1) not in ("item", "current")
    }


def substitute_env_vars(text: str, context: Context | None, *, strict: bool = False) -> str:
    """Replace ``$name[.path]`` from ``context`` and collapse ``$$`` → ``$``.

    ``$item`` is left untouched (owned by :func:`substitute_item`). Unknown names
    are left verbatim so the model sees them as literal text. A value landing
    inside a ``{...}`` blob is JSON-escaped so it can't break a later json.loads.
    Field paths traverse per :func:`resolve_field_path` under ``strict``.
    """
    if not text or "$" not in text:
        return text
    blob_spans = _json_blob_spans(text)

    def _replace(m: re.Match) -> str:
        name = m.group(1)
        if name is None:  # matched "$$"
            return "$"
        value = _lookup_or_none(name, context)
        if value is None:
            return m.group(0)
        resolved = resolve_field_path(value, m.group(2), strict=strict, ref=f"${name}")
        return _escape_for_json(resolved, m.start(), blob_spans)

    return _ENV_VAR_RE.sub(_replace, text)


def _lookup_or_none(name: str, context: Context | None) -> str | None:
    """Return the stringified binding for ``name``, or None if unresolved/reserved."""
    if name == "item" or context is None:
        return None
    try:
        value = context.lookup(name)
    except ScopeError:
        return None
    return value if isinstance(value, str) else str(value)


def substitute_item(template: str, item_json: str, *, strict: bool = False) -> str:
    """Replace ``$item`` / ``$item.path`` in ``template`` with row values.

    ``$item`` → the full row; a field path traverses the JSON-decoded row per
    :func:`resolve_field_path` (lenient ``""`` by default, ``strict=True``
    raises — spec §5.3.4.1).
    """
    if "$item" not in template:  # skip the regex scan + per-row JSON parse
        return template
    blob_spans = _json_blob_spans(template)

    def _path_replacer(match: re.Match) -> str:
        value = resolve_field_path(item_json, match.group(1), strict=strict, ref="$item")
        return _escape_for_json(value, match.start(), blob_spans)

    result = _ITEM_PATH_RE.sub(_path_replacer, template)
    if "$item" not in result:
        return result
    # Bare $item substitutes the whole row; it needs the same in-blob escaping as
    # a path reference, and its blob spans are recomputed on `result` because path
    # substitution above shifted positions. Callable replacement keeps backslash
    # sequences in the data from being re-processed as regex escapes.
    result_spans = _json_blob_spans(result)
    return _ITEM_BARE_RE.sub(lambda m: _escape_for_json(item_json, m.start(), result_spans), result)


__all__ = [
    "FanoutResponse",
    "build_reducer_input",
    "find_references",
    "resolve_field_path",
    "substitute_env_vars",
    "substitute_item",
    "substitute_response_vars",
]
