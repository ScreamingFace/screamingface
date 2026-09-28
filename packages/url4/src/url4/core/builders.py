"""Python constructors for url4 expressions — the builder facade.

Builders lower directly to the frozen AST in :mod:`url4.core.nodes` (no parallel
representation) and normalize exactly the way the parser does, so Python-side
construction and text-side parsing can never disagree:

- a **string source** goes through the full descriptor grammar
  (:func:`url4.core.grammar.parse`): ``"article:0.9:https://x"`` builds a weighted
  Source, ``"(a)!'go'"`` a nested expression;
- a **string value** (the ``value`` argument of :func:`src`) goes through §5.2
  value detection (:func:`url4.core.grammar.parse_value`): a URL is a Url, ``@`` a
  SelfRef, a plain word a Text — never re-read as an attribution chain;
- a **mapping** becomes an inline ``{…}`` structured object (§5.3.11.3);
- :func:`src` with only a name yields :class:`~url4.core.nodes.Binding`, with no
  descriptor at all the bare value node — mirroring the parser (§4.3).

INVARIANT: every node a builder returns is accepted by
:func:`url4.core.render.render` (whose default ``check=True`` certifies the text
round-trip). Shapes the grammar cannot carry are rewritten when a faithful
equivalent exists — a reduce-over-iteration source becomes its explicit
``(iteration)!reducer`` group, a bare iteration source in an intent-bearing
group is shielded in its own attribution-neutral group — and rejected with a
clear error when it does not.

The two-axis annotation model (§4) is kept visible in :func:`src`'s signature:
attribution = ``name`` / ``weight`` / ``budgets`` (open key namespace);
execution = ``mode`` / ``t`` / ``retry`` / ``accept`` / ``required`` (tri-state
→ ``;required`` / ``;optional``) / ``expand`` (the spec's closed key set) plus
``annotations`` for extension keys.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

from url4.core._annotations import _VALID_ON_ERROR
from url4.core.grammar import _IDENT_RE, _STRUCT_KEY_RE, intent_atom, parse, parse_value
from url4.core.nodes import (
    Binding,
    Expression,
    IdentityRef,
    Iteration,
    IterationDirectives,
    Node,
    OnErrorPolicy,
    Params,
    RelUrl,
    SelfRef,
    Source,
    StructObject,
    Text,
    Url,
    VarRef,
)

# WHY: the renderer owns the canonical text forms; re-deriving quoting/number/
# intent/source formatting here would let builders and renderer drift.
from url4.core.render import _format_number, _quote, _render_intent, _render_source

SourceLike = str | Node | Mapping[str, object]
"""Anything accepted in a source position: url4 text, an AST node, or a mapping."""

ParamsLike = Sequence[tuple[str, object]] | Mapping[str, object]
"""Protocol/execution parameters: ordered pairs or a mapping; None values are flags."""


# --- leaf constructors ---------------------------------------------------------


def text(content: str) -> Text:
    """Inline text content / a natural-language prompt (spec §5.1)."""
    return Text(content)


def ref(name: str | int, *path: str | int) -> VarRef:
    """A ``$name`` / ``$N`` variable reference with an optional field path (§6.2)."""
    return VarRef(str(name), tuple(path))


def self_() -> SelfRef:
    """``@`` — the addressed node's own holdings (§5.6.1)."""
    return SelfRef()


def identity(name: str, collection: str | None = None) -> IdentityRef:
    """``@name[/collection]`` — a named principal's holdings (§5.6.2)."""
    return IdentityRef(name, collection)


def struct(mapping: Mapping[str, object]) -> StructObject:
    """An inline ``{key: value, …}`` structured object (§5.3.11.3).

    Strings quote; ints and floats stay bare tokens (RDS mode re-reads them as
    numbers, §5.3.11.3); nested mappings nest without a depth limit.
    """
    return StructObject(_struct_raw(mapping))


def _struct_raw(mapping: Mapping[str, object]) -> str:
    fields = ", ".join(
        f"{_struct_field_key(k)}: {_struct_field_value(v)}" for k, v in mapping.items()
    )
    return "{" + fields + "}"


def _struct_field_key(key: object) -> str:
    # WHY: the grammar's field-key class, not str.isalnum() — Unicode letters
    # would mint a struct the parser cannot faithfully reparse.
    if not isinstance(key, str) or not _STRUCT_KEY_RE.fullmatch(key):
        raise ValueError(f"invalid struct field key {key!r} (ALPHA/DIGIT/_ only, spec §8)")
    return key


def _struct_field_value(value: object) -> str:
    if isinstance(value, bool) or value is None:
        raise TypeError(f"struct field value {value!r} has no url4 form — use a string")
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, (int, float)):
        return _format_number(value)
    if isinstance(value, Mapping):
        return _struct_raw(value)
    raise TypeError(
        f"cannot carry {type(value).__name__} in a struct field — "
        "arrays and objects beyond mappings/scalars must be modeled as sources"
    )


# --- src(): the two-axis source descriptor ---------------------------------------


def src(
    value: SourceLike,
    *,
    name: str | None = None,
    weight: float | int | Mapping[str, object] | None = None,
    budgets: Mapping[str, object] | None = None,
    mode: str | None = None,
    t: float | int | None = None,
    retry: int | None = None,
    accept: str | None = None,
    required: bool | None = None,
    expand: bool = False,
    annotations: ParamsLike = (),
) -> Node:
    """Build a source descriptor (§4.3) around ``value``.

    Attribution axis: ``name``, ``weight`` (scalar or domain-conditional
    mapping, §4.1.1), ``budgets`` (open key namespace). Execution axis:
    ``mode``/``t``/``retry``/``accept``/``required``/``expand`` plus
    ``annotations`` for extension keys. ``required`` is tri-state (§10.1):
    ``True`` marks ``;required``, ``False`` marks ``;optional``, and the
    default ``None`` leaves the spec's default handling.

    Returns the parser-canonical node for the descriptor: a bare value node
    when no descriptor content is given, a :class:`Binding` for name-only, a
    :class:`Source` otherwise.
    """
    node = _coerce_value(value)
    _check_name(name)
    ann = _exec_annotations(mode, t, retry, accept, required, annotations)
    norm_weight = _norm_weight(weight)
    norm_budgets = _norm_budgets(budgets)
    if norm_weight is None and not norm_budgets and not ann and not expand:
        if name is not None:
            return Binding(name, node, "=")
        return node
    return Source(
        value=node,
        name=name,
        weight=norm_weight,
        budgets=norm_budgets,
        annotations=ann,
        expand=expand,
    )


def _check_name(name: str | None) -> None:
    if name is None:
        return
    if name == "src" or not _IDENT_RE.fullmatch(name):
        raise ValueError(f"invalid source name {name!r} ('src' is reserved, §4.3)")


def _exec_annotations(
    mode: str | None,
    t: float | int | None,
    retry: int | None,
    accept: str | None,
    required: bool | None,
    extra: ParamsLike,
) -> Params:
    typed = (
        ("mode", mode),
        ("t", None if t is None else _timeout_text(t)),
        ("retry", None if retry is None else _retry_text(retry)),
        ("accept", accept),
    )
    pairs: list[tuple[str, str | None]] = [(k, v) for k, v in typed if v is not None]
    if required is not None:
        pairs.append(("required" if required else "optional", None))
    return tuple(pairs) + _pairs(extra)


def _timeout_text(t: float | int) -> str:
    if t <= 0:
        raise ValueError(f"per-source timeout t={t!r} must be positive")
    return _format_number(t)


def _retry_text(retry: int) -> str:
    if retry < 0:
        raise ValueError(f"retry={retry!r} must be >= 0")
    return str(retry)


def _pairs(extra: ParamsLike) -> Params:
    items = extra.items() if isinstance(extra, Mapping) else extra
    return tuple((key, None if value is None else _param_text(value)) for key, value in items)


def _param_text(value: object) -> str:
    if isinstance(value, bool):
        raise TypeError("boolean has no url4 parameter form — flags use value None")
    if isinstance(value, (int, float)):
        return _format_number(value)
    if isinstance(value, str):
        return value
    raise TypeError(f"cannot carry {type(value).__name__} as a parameter value")


def _norm_weight(weight: float | int | Mapping[str, object] | None) -> float | dict | None:
    if weight is None:
        return None
    if isinstance(weight, Mapping):
        return dict(weight)
    if weight < 0:
        raise ValueError(f"weight {weight!r} must be >= 0 (§4.1)")
    return float(weight)


def _norm_budgets(budgets: Mapping[str, object] | None) -> tuple[tuple[str, str | dict], ...]:
    if not budgets:
        return ()
    out: list[tuple[str, str | dict]] = []
    for key, value in budgets.items():
        if key in ("weight", "src"):
            raise ValueError(f"budget key {key!r} is reserved (§4.1.1.3)")
        out.append((key, dict(value) if isinstance(value, Mapping) else _param_text(value)))
    return tuple(out)


# --- value / source coercion ---------------------------------------------------------


def _coerce_value(value: SourceLike) -> Node:
    """A data value per §5.2 value detection — never a descriptor chain."""
    node = _to_node(value, parse_value)
    if isinstance(node, (Binding, Source)):
        raise TypeError(
            f"{type(node).__name__} is a source descriptor, not a value — pass the "
            "inner value and the descriptor kwargs separately"
        )
    return _rewrite_reducer_iteration(node)


def _coerce_source(value: SourceLike) -> Node:
    """A full source: descriptors allowed (string form runs the whole grammar)."""
    node = _to_node(value, parse)
    if isinstance(node, (Binding, Source)) and isinstance(node.value, Iteration):
        rewritten = _rewrite_reducer_iteration(node.value)
        if rewritten is not node.value:
            node = replace(node, value=rewritten)
        return node
    return _rewrite_reducer_iteration(node)


def _to_node(value: SourceLike, parse_text) -> Node:
    if isinstance(value, str):
        return parse_text(value)
    if isinstance(value, Mapping):
        return struct(value)
    if isinstance(value, Node):  # Node is a closed union — isinstance works on it
        return value
    raise TypeError(f"cannot build a url4 source from {type(value).__name__}")


def _rewrite_reducer_iteration(node: Node) -> Node:
    """``(iteration)!reducer`` is the value-position spelling of a reducer (§5.3)."""
    if isinstance(node, Iteration) and node.reducer is not None:
        return Expression(sources=(replace(node, reducer=None),), intent=intent_atom(node.reducer))
    return node


# --- expr() and friends -----------------------------------------------------------------


def expr(
    *sources: SourceLike,
    intent: str | Node | None = None,
    broadcast: bool = False,
    params: ParamsLike | None = None,
) -> Expression:
    """The composite ``(sources)!intent`` unit (§2) — everything else is sugar."""
    if intent is None:
        # INVARIANT: expression = "(" source-list ")" intent-op intent — the
        # intent is not optional (`OME-508`), so the builder rejects what the
        # grammar rejects. Iteration collections are built via iterate().
        raise ValueError("expr() requires an intent — the grammar's expression always carries one")
    return Expression(
        sources=tuple(_coerce_source(s) for s in sources),
        intent=_intent_node(intent),
        broadcast=broadcast,
        params=_pairs(params or ()),
    )


def _intent_node(intent: str | Node) -> Node:
    if isinstance(intent, str):
        return intent_atom(intent)
    if isinstance(intent, (Text, Url, RelUrl)):
        return intent
    raise TypeError(
        f"{type(intent).__name__} cannot be an intent — the grammar's intent forms "
        "are text (prompt) and URIs (code pointers), §6"
    )


def broadcast(
    *sources: SourceLike,
    intent: str | Node,
    params: ParamsLike | None = None,
) -> Expression:
    """``(sources)!*intent`` — apply the intent per source (§6.1)."""
    return expr(*sources, intent=intent, broadcast=True, params=params)


def reduce(
    *calls: SourceLike,
    intent: str | Node,
    params: ParamsLike | None = None,
) -> Expression:
    """``(call1, call2, …)!intent`` — fan-out/reduce sugar over :func:`expr`."""
    if not calls:
        raise ValueError("reduce() needs at least one call to reduce over")
    return expr(*calls, intent=intent, params=params)


# --- iterate() ------------------------------------------------------------------------------


def iterate(
    collection: SourceLike | list[SourceLike] | tuple[SourceLike, ...],
    body: str | Node | list[SourceLike] | tuple[SourceLike, ...] = "",
    *,
    intent: str | Node | None = None,
    reduce: str | Node | None = None,
    concurrency: int | None = None,
    on_error: str | None = None,
    slice: tuple[int, int] | None = None,
    fmt_result: str | None = None,
) -> Iteration:
    """``collection*(body)!intent`` — evaluate ``body`` once per element (§5.3).

    ``collection``: url4 text, an AST node, or a Python sequence (an inline
    parenthesized collection, §5.3.11). ``body``: raw template text or sources
    (may reference ``$item``). ``intent`` reduces per row; ``reduce`` across
    rows. Directive kwargs map to ``;iteration.*`` (§5.3.6).
    """
    if intent is None:
        # INVARIANT: iteration-expr takes a full expression after "*", whose
        # intent is mandatory (`OME-508`) — map-only iteration has no grammar
        # form, with or without a cross-row reducer.
        raise ValueError(
            "iterate() requires an intent — the expression after '*' always "
            "carries one (src*(body)!intent)"
        )
    return Iteration(
        collection=_coerce_collection(collection),
        body=_body_text(body),
        intent=_template_text(intent),
        reducer=_template_text(reduce),
        directives=_directives(concurrency, on_error, slice, fmt_result),
    )


def _coerce_collection(
    collection: SourceLike | list[SourceLike] | tuple[SourceLike, ...],
) -> Node:
    if isinstance(collection, (list, tuple)):
        return Expression(sources=tuple(_coerce_value(el) for el in collection))
    return _coerce_source(collection)


def _body_text(body: str | Node | list[SourceLike] | tuple[SourceLike, ...]) -> str:
    if isinstance(body, str):
        return body
    if isinstance(body, (list, tuple)):
        return ", ".join(_render_source(_coerce_source(el)) for el in body)
    return _render_source(_coerce_source(body))


def _template_text(value: str | Node | None) -> str | None:
    """Canonicalize a per-row intent / cross-row reducer template (§5.3).

    Strings classify exactly like a parsed intent (§6): plain prose quotes,
    ``/path`` and ``scheme://`` code pointers stay verbatim.
    """
    if value is None:
        return None
    return _render_intent(_intent_node(value))


def _directives(
    concurrency: int | None,
    on_error: str | None,
    slice: tuple[int, int] | None,
    fmt_result: str | None,
) -> IterationDirectives:
    if concurrency is not None and concurrency < 1:
        raise ValueError(f"iteration.concurrency={concurrency!r} must be >= 1")
    if on_error is not None and on_error not in _VALID_ON_ERROR:
        raise ValueError(
            f"iteration.on_error={on_error!r}; expected one of {', '.join(_VALID_ON_ERROR)}"
        )
    if slice is not None and not (0 <= slice[0] <= slice[1]):
        raise ValueError(f"iteration.slice={slice!r} needs 0 <= start <= end")
    return IterationDirectives(
        concurrency=concurrency,
        # The membership check above is the runtime proof; the cast records it
        # for the type system, which cannot see through the `in` test.
        on_error=cast(OnErrorPolicy, on_error) if on_error is not None else "collect",
        slice=slice,
        fmt_result=fmt_result,
    )


# --- expand() ---------------------------------------------------------------------------------


def expand(source: SourceLike) -> Source:
    """Mark a source for expansion — ``*source`` / ``;expand`` (§5.3.12)."""
    node = _coerce_source(source)
    if isinstance(node, Source):
        return replace(node, expand=True)
    if isinstance(node, Binding):
        # mirrors the grammar's expansion of a name-only descriptor (§5.2 r9)
        return Source(value=node.value, name=node.name, expand=True)
    return Source(value=node, expand=True)


__all__ = [
    "ParamsLike",
    "SourceLike",
    "broadcast",
    "expand",
    "expr",
    "identity",
    "iterate",
    "reduce",
    "ref",
    "self_",
    "src",
    "struct",
    "text",
]
