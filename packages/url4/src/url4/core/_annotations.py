"""Shared ``;``-chain decoding: annotation pairs, iteration directives, and the
§8.1.2 expression/source boundary.

Both the grammar (:mod:`url4.core.grammar`, for ``;`` tails on individual sources)
and the envelope decoders (:mod:`url4.core.parser`, for top-level trailing params)
need the same three pieces of logic; this dependency-free leaf holds the single
definition so the two layers cannot drift:

- :func:`split_annotation_pairs` — ``;key[=value]`` chain → ordered pairs.
- :func:`extract_directives` — pull ``iteration.*`` keys (and their deprecated
  ``foreach.*`` spellings) out of a pair list into
  :class:`~url4.core.nodes.IterationDirectives`, validating values.
- :func:`classify_boundary` — the §8.1.2 desugaring algorithm: expression-level
  params are consumed greedily until the first *exclusively source-level* key;
  everything from that key on is a source-level execution annotation.
"""

from __future__ import annotations

import re
import warnings
from typing import cast, get_args

from url4.core._scan import skip_quoted
from url4.core.errors import ParseError
from url4.core.nodes import IterationDirectives, OnErrorPolicy, Params

# §8.1.3 — keys that can ONLY be source-level execution annotations; the first
# one encountered in a sugar-form ``;`` chain triggers the boundary. ``coord.*``
# and ``iteration.*`` prefixes are matched separately.
EXCLUSIVE_SOURCE_KEYS = frozenset(
    {"mode", "retry", "required", "optional", "accept", "expand", "coord"}
)

# The one definition of the accepted policy set is OnErrorPolicy's Literal in
# core.nodes; this validator derives from it so the wire grammar and the
# dataclass cannot drift apart.
_VALID_ON_ERROR = get_args(OnErrorPolicy)


def split_annotation_pairs(parts: list[str]) -> Params:
    """Decode raw ``key[=value]`` segments into ordered pairs (flags → None)."""
    pairs: list[tuple[str, str | None]] = []
    for part in parts:
        key, eq, value = part.strip().partition("=")
        pairs.append((key.strip(), value.strip() if eq else None))
    return tuple(pairs)


# --- exec-chain character classes (§4.2) ------------------------------------------
#
# INVARIANT: these enforce the ABNF's `exec-key` / `exec-value` productions on the
# EXECUTION axis only. They are applied from `grammar._attach_tail`, where the
# §8.1.2 boundary has already separated expression params from source
# annotations — applying them at split time would wrongly reject legal
# expression-level `param-key`s (which, unlike exec-keys, may contain digits).

# exec-key = 1*( ALPHA / "_" / "." ) — the extensible form. No digits.
_EXEC_KEY_RE = re.compile(r"[A-Za-z_.]+", re.ASCII)

# `param-key = 1*( ALPHA / DIGIT / "." / "_" )` — note NO "-", unlike
# `param-value`. Dots namespace a key (coord.rounds, iteration.slice).
_PARAM_KEY_RE = re.compile(r"[A-Za-z0-9._]+", re.ASCII)
# `param-value = 1*( ALPHA / DIGIT / "." / "-" / "_" / "," / ":" / "/" )` —
# ":" and "/" are admitted so URI-shaped values (cb=https://host/p) and typed
# values (iteration.slice=1:3, accept=application/json) fit without quoting.
_PARAM_VALUE_RE = re.compile(r"[A-Za-z0-9.\-_,:/]+", re.ASCII)

# WHY: `nested-param-value = param-value / processor-value`, and a processor-value
# may be a whole expression body — which can never satisfy param-value. These
# keys are expression-bearing, so their values are validated by their own
# owner (`url4.dag.processor` for §27.3, the expression parser for `q`) rather
# than by the charset here. Naming them keeps that carve-out in one place.
EXPRESSION_BEARING_KEYS = frozenset({"q", "processor"})

# exec-value. ":" and "/" are included so the typed forms this engine supports
# parse: `;iteration.slice=1:3` and `;accept=application/json`.
_EXEC_VALUE_RE = re.compile(r"[A-Za-z0-9.\-_,:/]+", re.ASCII)

# coord-key is a CLOSED enum in the ABNF (`coord-param`), unlike the open-ended
# `iteration.*` family. The more specific production wins over the extensible
# `exec-key` fallback for a `coord.`-prefixed key.
_COORD_KEYS = frozenset(
    {"coord.rounds", "coord.max_turns", "coord.convergence", "coord.turn_timeout"}
)


def validate_exec_annotations(pairs: Params) -> None:
    """Enforce the exec-chain character classes; raise ``malformed_source``."""
    for key, value in pairs:
        if not _EXEC_KEY_RE.fullmatch(key):
            raise ParseError(
                f"invalid execution-annotation key {key!r} — exec-key admits only "
                "letters, '_' and '.' (spec §4.2)"
            )
        if key.startswith("coord.") and key not in _COORD_KEYS:
            raise ParseError(
                f"unknown coordination key {key!r} — coord-key is a closed set: "
                f"{sorted(_COORD_KEYS)}"
            )
        if value is not None and not _EXEC_VALUE_RE.fullmatch(value):
            raise ParseError(
                f"invalid execution-annotation value {value!r} for {key!r} (spec §4.2)"
            )


def validate_param(key: str, value: str | None) -> None:
    """Validate one protocol parameter against `param-key` / `param-value`.

    The single owner of that rule: the wire splitter, the nested query params
    of a rel/remote expression, and the `;` expression chain all call this, so
    a node cannot accept over HTTP what it refuses in text (`OME-507`).

    Two shapes the grammar does not define are ACCEPTED EXTENSIONS and are
    checked on the key alone (owner decision, `OME-507`):

    * a valueless flag (``?stream``, ``;stream``) — ``value`` is ``None``, or
      ``""`` from the decoders that spell a flag that way;
    * a fully QUOTED value (``?note='a&b'``) — the only way to carry ``&``,
      ``(`` or a space in a param, since `param-value` has no quoting form.

    Callers that can tell a flag from a present-but-empty value (the wire
    splitter knows, from the ``=``) reject the empty one before calling.
    """
    if not _PARAM_KEY_RE.fullmatch(key):
        raise ParseError(
            f"invalid param key {key!r} — `param-key` takes ALPHA / DIGIT / '.' / '_'",
        )
    if not value or key in EXPRESSION_BEARING_KEYS or _is_quoted(value):
        return
    if not _PARAM_VALUE_RE.fullmatch(value):
        raise ParseError(
            f"invalid param value {value!r} for {key!r} — `param-value` takes "
            "ALPHA / DIGIT / '.' / '-' / '_' / ',' / ':' / '/'",
        )


def _is_quoted(value: str) -> bool:
    """True when ``value`` is one complete ``'…'`` run (the quoted extension)."""
    return len(value) >= 2 and value.startswith("'") and skip_quoted(value, 0) == len(value)


def validate_params(params: Params) -> None:
    """Validate every pair in a decoded parameter list."""
    for key, value in params:
        validate_param(key, value)


def is_source_level_key(key: str) -> bool:
    """True for keys that are exclusively source-level (§8.1.3 boundary set)."""
    return key in EXCLUSIVE_SOURCE_KEYS or key.startswith(("coord.", "iteration.", "foreach."))


def classify_boundary(pairs: Params) -> tuple[Params, Params]:
    """Split a sugar-form ``;`` chain into (expression params, source annotations).

    §8.1.2/§8.1.3: params are expression-level until the first exclusively
    source-level key; that key and everything after it are source-level. Dual
    keys (``t``, ``ct_mismatch``, ``budget_mode``, ``broadcast``) classify by
    which side of the boundary they fall on.
    """
    expr_params: list[tuple[str, str | None]] = []
    source_ann: list[tuple[str, str | None]] = []
    boundary = False
    for key, value in pairs:
        boundary = boundary or is_source_level_key(key)
        (source_ann if boundary else expr_params).append((key, value))
    return tuple(expr_params), tuple(source_ann)


def extract_directives(pairs: Params) -> tuple[Params, IterationDirectives]:
    """Pull ``iteration.*`` / deprecated ``foreach.*`` keys out of ``pairs``.

    Returns the remaining pairs plus the decoded directives. Unknown
    ``iteration.<key>`` names are ignored (forward compatibility), matching the
    pre-0.2 tolerance for unknown ``foreach.*`` keys.
    """
    rest: list[tuple[str, str | None]] = []
    fields: dict[str, object] = {}
    for key, value in pairs:
        name = _directive_name(key)
        if name is None:
            rest.append((key, value))
        elif name in ("concurrency", "on_error", "slice", "fmt_result"):
            fields[name] = _parse_directive(name, value or "")
    return tuple(rest), IterationDirectives(**fields)  # type: ignore[arg-type]


def _directive_name(key: str) -> str | None:
    """The directive field for ``key``, or None; warns on deprecated spellings."""
    if key.startswith("iteration."):
        return key[len("iteration.") :]
    if key.startswith("foreach."):
        warnings.warn(
            f"';{key}=' is deprecated; use ';iteration.{key[8:]}='",
            DeprecationWarning,
            stacklevel=4,
        )
        return key[len("foreach.") :]
    return None


def _parse_directive(name: str, value: str) -> object:
    parser = {"concurrency": _parse_concurrency, "on_error": _parse_on_error}.get(name)
    if parser is None:
        return _parse_slice(value) if name == "slice" else value.strip()  # fmt_result
    return parser(value)


def _parse_on_error(value: str) -> OnErrorPolicy:
    result = value.strip()
    if result == "abort":
        warnings.warn(
            "iteration.on_error=abort is deprecated; use =fail",
            DeprecationWarning,
            stacklevel=5,
        )
        return "fail"
    if result not in _VALID_ON_ERROR:
        raise ParseError(
            f"invalid iteration.on_error={result!r}; expected one of {', '.join(_VALID_ON_ERROR)}"
        )
    # The membership check above IS the runtime proof; the type system cannot
    # see it, so this cast only records what was established.
    return cast(OnErrorPolicy, result)


def _parse_concurrency(value: str) -> int:
    """A ``iteration.concurrency`` value; must be a positive int (unbounded is
    expressed by omitting the directive)."""
    try:
        n = int(value)
    except ValueError:
        raise ParseError(
            f"invalid iteration.concurrency={value.strip()!r}; expected a positive integer"
        ) from None
    if n < 1:
        raise ParseError(f"invalid iteration.concurrency={n}; must be >= 1")
    return n


def _parse_slice(value: str) -> tuple[int, int]:
    """A ``iteration.slice`` value: the half-open ``start:end`` element range."""
    start_text, sep, end_text = value.partition(":")
    try:
        if not sep:
            raise ValueError
        start, end = int(start_text), int(end_text)
    except ValueError:
        raise ParseError(
            f"invalid iteration.slice={value.strip()!r}; expected 'start:end' integers"
        ) from None
    if start < 0 or end < start:
        raise ParseError(f"invalid iteration.slice={value.strip()!r}; need 0 <= start <= end")
    return start, end


__all__ = [
    "EXPRESSION_BEARING_KEYS",
    "validate_param",
    "validate_params",
    "EXCLUSIVE_SOURCE_KEYS",
    "classify_boundary",
    "extract_directives",
    "is_source_level_key",
    "split_annotation_pairs",
]
