"""Where user-scope config values travel (D1). Two envelopes, ONE payload.

A caller who fetched `/.well-known/url4-config/<mount>` knows which items are theirs to
set. This is how they send them.

The payload is the same either way: a flat map of dotted item path to value, exactly the
paths the served schema names.

* **WebSocket** — a ``config`` member on the attach frame. JSON, so types arrive native.
* **HTTP** — one ``URL4-Config-<dotted.path>`` header per item.

Both are valid and neither is preferred; a client uses whichever its transport gives it.
They converge here, so `scope.enforce` runs once over one shape and cannot disagree with
itself between transports.

WHY one header per item rather than one JSON header: `.` and `_` are both legal in an HTTP
field name (RFC 9110 `token`), so the dotted path survives verbatim — no flattening, so
`parameters.top_p` and a hypothetical `parameters.top.p` stay distinct. The cost is that a
header value is always a string, which `coerce` undoes using the schema the caller was
already served.

# AIDEV-NOTE: deployment hazard — nginx drops headers containing underscores unless
# `underscores_in_headers on`. That silently loses `parameters.top_p` rather than
# rejecting it, and the request then runs on the default. A node behind nginx must set
# that directive; `missing_underscored` exists so an operator can detect the case.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from url4.discovery.scope import resolve_item

HEADER_PREFIX = "url4-config-"
"""Lower-cased, because ASGI hands header names down-cased and HTTP names are
case-insensitive. The wire spelling is `URL4-Config-<path>`."""

ATTACH_CONFIG_KEY = "config"
"""The attach frame member. Named `config` to match what the schema is called."""


class CarrierError(ValueError):
    """A config payload that cannot be read at all — malformed, not merely invalid."""


def from_attach_frame(frame: Mapping[str, Any]) -> dict[str, Any]:
    """Read the ``config`` member of a WebSocket attach frame.

    Absent is the ordinary case and means "no user values", not an error: most requests
    take the defaults.
    """
    config = frame.get(ATTACH_CONFIG_KEY)
    if config is None:
        return {}
    if not isinstance(config, Mapping):
        raise CarrierError(
            f"attach frame {ATTACH_CONFIG_KEY!r} must be an object of "
            f"item-path to value, got {type(config).__name__}"
        )
    return {str(k): v for k, v in config.items()}


def from_headers(headers: Iterable[tuple[bytes, bytes]]) -> dict[str, str]:
    """Collect ``URL4-Config-*`` headers into the same flat map.

    Values stay strings here — typing them needs the schema, which this layer does not
    have. `coerce` is the next step.
    """
    values: dict[str, str] = {}
    for raw_name, raw_value in headers:
        name = raw_name.decode("latin-1").lower()
        if not name.startswith(HEADER_PREFIX):
            continue
        path = name[len(HEADER_PREFIX) :]
        if not path:
            raise CarrierError("a bare 'URL4-Config-' header names no item")
        values[path] = raw_value.decode("latin-1").strip()
    return values


def coerce(
    values: Mapping[str, str], schema: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Type the string values a header carrier produced, using the served schema.

    Returns ``(typed, unparseable)``. A value that does NOT parse as its declared type is
    left as the original string and its path is reported, so `scope.enforce` reports it as
    a type mismatch naming the declared type — one error vocabulary, whichever carrier the
    caller used.

    An item the schema does not know is passed through untouched; `enforce` is what
    refuses it, and doing it here as well would make the same mistake two errors.
    """
    typed: dict[str, Any] = {}
    unparseable: list[str] = []
    for path, text in values.items():
        item = resolve_item(schema, path)
        declared = item.get("type") if item is not None else None
        if declared is None:
            typed[path] = text
            continue
        parsed, ok = _parse(text, declared)
        typed[path] = parsed if ok else text
        if not ok:
            unparseable.append(path)
    return typed, unparseable


def _parse(text: str, declared: Any) -> tuple[Any, bool]:
    """Read one header value at its declared JSON type."""
    if isinstance(declared, list):
        # A union: the first member that parses wins, which keeps `["string", "null"]`
        # from turning every value into a string before `null` is ever tried.
        for one in declared:
            parsed, ok = _parse(text, one)
            if ok:
                return parsed, True
        return text, False
    parser = _PARSERS.get(str(declared))
    return parser(text) if parser is not None else (text, False)


def _as_bool(text: str) -> tuple[Any, bool]:
    # Only the JSON spellings. Accepting "yes"/"1" would make the header carrier lenient
    # where the attach frame is strict, and the two must agree.
    lowered = text.lower()
    return (lowered == "true", True) if lowered in ("true", "false") else (text, False)


def _as_number(text: str, *, integral: bool) -> tuple[Any, bool]:
    try:
        value = int(text) if integral else float(text)
    except ValueError:
        return text, False
    return value, True


def _as_json(text: str) -> tuple[Any, bool]:
    try:
        return json.loads(text), True
    except (TypeError, ValueError):
        return text, False


_PARSERS: dict[str, Any] = {
    "string": lambda text: (text, True),
    "boolean": _as_bool,
    "integer": lambda text: _as_number(text, integral=True),
    "number": lambda text: _as_number(text, integral=False),
    "null": lambda text: (None, True) if text == "null" else (text, False),
    # An object or array in a header is JSON. Rare, but a structured leaf is a real item
    # shape, so the carrier must not be the reason it cannot be set.
    "object": _as_json,
    "array": _as_json,
}


def missing_underscored(values: Mapping[str, Any], schema: Mapping[str, Any]) -> list[str]:
    """User-scope item paths containing `_` that the caller did NOT send.

    An operational aid, not a check. nginx silently DROPS headers whose names contain an
    underscore unless `underscores_in_headers on`, so `parameters.top_p` vanishes and the
    request quietly runs on the default. This cannot distinguish "dropped" from "not
    sent" — nothing can, the header is simply gone — so it is only ever a hint to log
    when a request looks like it lost something.
    """
    return sorted(
        path
        for path in _user_item_paths(schema)
        if "_" in path.rsplit(".", 1)[-1] and path not in values
    )


def _user_item_paths(schema: Mapping[str, Any], prefix: str = "") -> list[str]:
    """Every `user`-scope item path in the schema, dotted."""
    found: list[str] = []
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return found
    for name, child in properties.items():
        if not isinstance(child, Mapping):
            continue
        path = f"{prefix}.{name}" if prefix else str(name)
        scope = child.get("x-scope")
        if scope is None:
            found.extend(_user_item_paths(child, path))
        elif scope == "user":
            found.append(path)
    return found


__all__ = [
    "ATTACH_CONFIG_KEY",
    "HEADER_PREFIX",
    "CarrierError",
    "coerce",
    "from_attach_frame",
    "from_headers",
    "missing_underscored",
]
