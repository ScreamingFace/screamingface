"""Scalar and structured annotation values for the renderer (weights, budgets, quoting).

Split out of :mod:`url4.core.render` (module-size cap, ``OME-1539``); the renderer and the
builder facade import these. Every function is the inverse of a grammar production.
"""

from __future__ import annotations

from math import isfinite

from url4.core import _render_guards as guard
from url4.core._lexical import _NUMBER_RE, _STRUCT_KEY_RE, _STRUCT_TOKEN_RE
from url4.core.errors import RenderError


def quote(content: str) -> str:
    return "'" + content.replace("\\", "\\\\").replace("'", "\\'") + "'"


def render_weight(weight: float | dict) -> str:
    if isinstance(weight, dict):
        return render_struct_annotation(weight, nested=False)
    return format_number(weight)


def render_budget_value(value: str | dict | int | float) -> str:
    if isinstance(value, dict):
        return render_struct_annotation(value, nested=False)
    if isinstance(value, (int, float)):
        return format_number(value)
    guard.check_token(value, "budget value", extra_allowed="._-")
    return value


def render_struct_annotation(entries: dict, *, nested: bool) -> str:
    if not entries:
        raise RenderError("structured annotation value cannot be empty")
    return (
        "("
        + ",".join(f"{_struct_key(k)}:{_struct_val(v, nested=nested)}" for k, v in entries.items())
        + ")"
    )


def _struct_key(key: object) -> str:
    if not isinstance(key, str) or not _STRUCT_KEY_RE.fullmatch(key):
        raise RenderError(f"invalid structured annotation key {key!r}")
    return key


def _struct_val(value: object, *, nested: bool) -> str:
    if isinstance(value, dict):
        if nested:
            # §24.4.6 — at most scope → domain → scalar.
            raise RenderError("structured annotation nested deeper than two levels")
        result = render_struct_annotation(value, nested=True)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        result = format_number(value)
    elif isinstance(value, str):
        # a number-shaped string must quote — bare it would reparse as float
        bare_ok = _STRUCT_TOKEN_RE.fullmatch(value) and not _NUMBER_RE.fullmatch(value)
        result = value if bare_ok else quote(value)
    else:
        raise RenderError(f"invalid structured annotation value {value!r}")
    return result


def format_number(value: float | int) -> str:
    if isinstance(value, bool) or value < 0 or not isfinite(value):
        raise RenderError(f"number {value!r} is outside the grammar's unsigned decimal form")
    if isinstance(value, int):
        return str(value)
    text = repr(value)
    if not _NUMBER_RE.fullmatch(text):
        text = f"{value:.12f}".rstrip("0").rstrip(".") or "0"
    if not _NUMBER_RE.fullmatch(text) or float(text) != value:
        raise RenderError(f"number {value!r} cannot be written as an unsigned decimal")
    return text


__all__ = ["format_number", "quote", "render_budget_value", "render_weight"]
