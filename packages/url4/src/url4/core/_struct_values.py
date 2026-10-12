"""Structured annotation values (Spec B §4.1.1): weights and budgets in ``(…)``.

Split out of :mod:`url4.core.grammar` (module-size cap). The §4.1.1.4
first-entry classifier commits on the first entry and never backtracks; after
commitment, an entry that breaks the ``struct-pair`` production is
``malformed_source``. Structured weights are flat; structured budgets nest at
most scope → domain → scalar (§24.4.6).
"""

from __future__ import annotations

from url4.core._lexical import (
    _IDENT_RE,
    _NUMBER_RE,
    _SCALAR_BUDGET_RE,
    _STRUCT_KEY_RE,
    _STRUCT_TOKEN_RE,
    _unquote,
)
from url4.core._scan import balanced_body, skip_quoted, split_top_level
from url4.core.errors import ParseError


def _classify_weight_group(rest: str) -> tuple[dict, str] | None:
    """Classify ``(`` in the weight position; parse a structured weight on commit.

    Returns ``(weight_mapping, remainder_after_colon)`` when the group is a
    structured annotation, or ``None`` when it begins an expression source list
    (§4.1.1.4). A committed group whose later entries violate the struct-pair
    production raises ``malformed_source`` — commitment, not a heuristic.
    """
    body = balanced_body(rest, 1)
    if body is None:
        raise ParseError(f"unclosed '(' in {rest!r}")
    if not _commits_to_struct(body):
        return None
    # INVARIANT: structured-weight is FLAT. `struct-val` is terminal, so only
    # `structured-budget-value` may nest (and only two deep, §24.4.6). Passing
    # nested=True makes any inner "(" a malformed_source (`OME-504`).
    weight = _parse_struct_entries(body, nested=True)
    after = rest[len(body) + 2 :]
    if not after.startswith(":"):
        raise ParseError(f"structured weight must be followed by ':<data-binding>' in {rest!r}")
    return weight, after[1:]


def _commits_to_struct(body: str) -> bool:
    """§4.1.1.4 first-entry classification (True = structured annotation)."""
    entries = split_top_level(body, ",")
    if not entries or not entries[0]:
        return False
    first = entries[0]
    m = _IDENT_RE.match(first)
    if m is None or first[m.end() : m.end() + 1] != ":":
        return False  # rules 1–4, 6–7: quoted, nested, '/', '@', digit, other
    value = first[m.end() + 1 :].strip()
    if value.startswith("/"):
        result = False  # rules 5a/5b: URI scheme or relative path after ':'
    elif value.startswith("'"):
        result = all(_is_struct_pair(e) for e in entries)  # rule 5d: all-entries
    else:
        result = _is_simple_struct_value(value)  # rule 5c: commit
    return result


def _is_simple_struct_value(value: str) -> bool:
    if _NUMBER_RE.fullmatch(value) or _IDENT_RE.fullmatch(value):
        return True
    return value.startswith("(") and balanced_body(value, 1) == value[1:-1]


def _is_struct_pair(entry: str) -> bool:
    m = _STRUCT_KEY_RE.match(entry)
    if m is None or entry[m.end() : m.end() + 1] != ":":
        return False
    value = entry[m.end() + 1 :].strip()
    if value.startswith("'"):
        return skip_quoted(value, 0) == len(value) != 1
    return _is_simple_struct_value(value)


def _parse_struct_entries(body: str, *, nested: bool) -> dict:
    """Parse committed struct entries; violations are ``malformed_source``."""
    result: dict[str, object] = {}
    for entry in split_top_level(body, ","):
        m = _STRUCT_KEY_RE.match(entry)
        if m is None or entry[m.end() : m.end() + 1] != ":":
            raise ParseError(f"malformed structured annotation entry {entry!r} (spec §4.1.1.4)")
        result[m.group()] = _parse_struct_val(entry[m.end() + 1 :].strip(), nested=nested)
    if not result:
        raise ParseError("empty structured annotation value")
    return result


def _parse_struct_val(val: str, *, nested: bool) -> object:
    result: object
    if _NUMBER_RE.fullmatch(val):
        result = float(val) if "." in val else int(val)
    elif val.startswith("'"):
        result = _unquote(val)
    elif val.startswith("("):
        result = _parse_nested_struct_val(val, nested=nested)
    elif _STRUCT_TOKEN_RE.fullmatch(val):
        result = val
    else:
        raise ParseError(f"malformed structured annotation value {val!r} (spec §4.1.1.4)")
    return result


def _parse_nested_struct_val(val: str, *, nested: bool) -> dict:
    # WHY well-formedness is checked BEFORE the depth rule: `(b:1)x` is malformed
    # whatever the depth budget is, and reporting it as "nested too deep" would
    # send the reader looking for the wrong defect.
    inner = balanced_body(val, 1)
    if inner is None or len(inner) + 2 != len(val):
        raise ParseError(f"malformed structured annotation value {val!r}")
    if nested:
        # §24.4.6 — at most scope → domain → scalar. Also the flat-only rule for
        # structured-weight, which passes nested=True at the top level.
        raise ParseError(f"structured annotation nested too deep at {val!r}")
    return _parse_struct_entries(inner, nested=True)


def _parse_weight_value(val: str) -> float | dict:
    """The ``weight=`` reserved key: scalar or structured (§4.1.1.3)."""
    if _NUMBER_RE.fullmatch(val):
        return float(val)
    if val.startswith("("):
        inner = balanced_body(val, 1)
        if inner is not None and len(inner) + 2 == len(val):
            # flat only — see _classify_weight_group
            return _parse_struct_entries(inner, nested=True)
    raise ParseError(f"malformed weight value {val!r}")


def _parse_budget_value(val: str) -> str | dict:
    if val.startswith("("):
        inner = balanced_body(val, 1)
        if inner is not None and len(inner) + 2 == len(val):
            return _parse_struct_entries(inner, nested=False)
        raise ParseError(f"malformed structured budget value {val!r}")
    if not _SCALAR_BUDGET_RE.fullmatch(val):
        raise ParseError(f"malformed scalar budget value {val!r} (spec §4.1.1.3)")
    return val
