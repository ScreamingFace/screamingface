"""AST → canonical url4 text — the exact inverse of :func:`url4.build`.

INVARIANT: for every node this module renders, ``build(render(x)) == x`` when
``x`` is an :class:`~url4.core.nodes.Expression`/:class:`~url4.core.nodes.Iteration`
root, and ``build(render(x)) == Expression(sources=(x,))`` for any other node
(mirroring ``build()``'s envelope, which always returns one of those two
roots). ``render(check=True)`` (the default) re-parses its own output and
compares ASTs, so a value returned from this module is a *certified*
round-trip — wire text can never silently drift from the tree it encodes.

``render(check=False)`` is still faithful or loud (law L3s): the guards in
:mod:`url4.core._render_guards` refuse every shape that would re-parse as a
different tree, and re-run the top-level envelope split (string scanning
only), so an unchecked render never runs as another expression.

Values the grammar cannot carry raise :class:`~url4.core.errors.RenderError`
instead of degrading: a bare URI with a depth-0 ``, ; ! '`` or unbalanced
parens (quoting it would change the node type to Text, spec §7.2), a negative
weight, structured annotations deeper than two levels (§24.4.6), a nested
reduce-over-iteration (only the top-level envelope decodes that shape), and a
``Source`` around an expression-valued node whose leading annotations would be
re-scoped by the §8.1.2 boundary algorithm on reparse.

Canonical-form choices (each reparses to the identical AST):
- Text always renders quoted; ``weight=`` renders as the bare scalar;
  ``;expand`` renders as the ``*`` prefix; descriptor-empty Sources render in
  Binding form — all mirroring what the parser produces for those shapes.
- Relative/remote expressions render in sugar form without params and in
  canonical ``?…&q=`` form with params (spec §8.1.4).
- At top level, composite source nodes (Binding/Source/RelExpr/RemoteExpr)
  render BARE, as fragment roots. The former paren wrap was an intent-less
  group, which the grammar does not derive (`OME-508`); and ``build()`` no
  longer hoists a lone call's intent, so ``/p(c)!'i'`` round-trips as itself.
"""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite

from url4.core import _render_guards as guard
from url4.core._annotations import is_source_level_key

# WHY: the `path` production has one owner (core/_call_head) — re-declaring it
# here would let parse and render drift.
from url4.core._call_head import PATH_RE

# WHY: these regexes ARE the grammar's character classes; re-declaring them
# here would let the two modules drift. Private-name import is deliberate.
from url4.core._lexical import (
    _IDENT_RE,
    _IDENTITY_NAME_RE,
    _NUMBER_RE,
    _SCHEME_RE,
    _STRUCT_KEY_RE,
    _STRUCT_TOKEN_RE,
)
from url4.core._scan import balanced_body, find_top_level, skip_quoted
from url4.core.errors import ParseError, RenderError
from url4.core.nodes import (
    Binding,
    Expression,
    IdentityRef,
    Iteration,
    IterationDirectives,
    Node,
    Params,
    RelExpr,
    RelUrl,
    RemoteExpr,
    SelfRef,
    Source,
    StructObject,
    Text,
    Url,
    VarRef,
)

_DEFAULT_DIRECTIVES = IterationDirectives()
_EXPR_VALUED = (Expression, RelExpr, RemoteExpr)


def render(node: Node, *, check: bool = True) -> str:
    """Render ``node`` as canonical url4 text.

    With ``check=True`` (the default) the output is re-parsed and compared to
    ``node`` — a mismatch raises :class:`RenderError`, so a returned string is
    guaranteed to round-trip. With ``check=False`` the render guards still
    refuse every tree they know would re-parse differently; the residue is text
    that fails to parse at all (loud), which :func:`verify` can re-attribute.
    """
    # WHY no envelope guard under check=True: verify() re-parses the whole text,
    # which subsumes the string-level envelope re-split.
    text = _render_top(node, envelope=not check)
    if check:
        verify(node, text)
    return text


def verify(node: Node, text: str) -> None:
    """Raise :class:`RenderError` unless ``text`` reparses to exactly ``node``.

    What ``render(check=True)`` does, exposed so a caller that rendered with
    ``check=False`` can pay for the check only once something downstream has
    already failed — see :func:`url4.peer.client._evaluate_front_door`. Returns
    normally when the tree is faithful, leaving the blame with the run.
    """
    from url4.core.parser import build  # runtime-only: parser is a higher layer

    expected = node if isinstance(node, (Expression, Iteration)) else Expression(sources=(node,))
    try:
        actual = build(text)
    except ParseError as exc:
        raise RenderError(f"rendered text {text!r} does not reparse: {exc}") from exc
    if actual != expected:
        raise RenderError(
            f"rendered text {text!r} reparses to a different tree — "
            f"the grammar cannot faithfully carry {node!r}"
        )


def _render_top(node: Node, *, envelope: bool) -> str:
    """Render a root; ``envelope`` re-runs the top-level split as a guard."""
    if isinstance(node, Expression):
        result = _render_expression(node, top=True, envelope=envelope)
    elif isinstance(node, Iteration):
        result = _render_top_iteration(node, envelope=envelope)
    elif isinstance(node, (Binding, Source, RelExpr, RemoteExpr)):
        # WHY: a composite source renders as a bare fragment root — the old
        # paren wrap became an intent-less group, which the grammar rejects
        # (`OME-508`). Shapes whose fragment form the envelope would split (an
        # inline `!` or a hoistable tail) raise RenderError in the guard.
        result = _render_fragment(node)
        if envelope:
            guard.check_fragment_envelope(result)
    else:
        result = _render_value(node)
    return result


def _render_fragment(node: Binding | Source | RelExpr | RemoteExpr) -> str:
    # A bare call's intent is the text's tail: the top-level intent rule applies.
    if isinstance(node, RelExpr):
        return _render_relexpr(node, top=True)
    if isinstance(node, RemoteExpr):
        return _render_remoteexpr(node, top=True)
    return _render_source(node)


# --- expressions ---------------------------------------------------------------


def _render_expression(e: Expression, *, top: bool = False, envelope: bool = False) -> str:
    if e.intent is None and e.broadcast:
        raise RenderError("broadcast (!*) requires an intent")
    if e.intent is None:
        # INVARIANT: expression = "(" source-list ")" intent-op intent — an
        # intent-less Expression is an internal carrier (paren-collections,
        # envelope assembly) with no surface form outside collection position
        # (`OME-508`, rendered via _render_collection).
        raise RenderError(
            "an Expression without an intent has no surface form — a "
            "parenthesized source group must carry !intent (or !*intent)"
        )
    sources = "(" + ", ".join(_render_source(s) for s in e.sources) + ")"
    intent = _render_intent(e.intent, top=top)
    out = sources + ("!*" if e.broadcast else "!") + intent + _render_params(e.params, top=top)
    if envelope:
        guard.check_group_envelope(out, sources, intent, broadcast=e.broadcast, params=e.params)
    return out


def _render_params(params: Params, *, top: bool) -> str:
    return "".join(_render_param(key, value, top=top) for key, value in params)


def _render_param(key: str, value: str | None, *, top: bool) -> str:
    if key == "broadcast" or key.startswith(("iteration.", "foreach.")):
        # broadcast folds into the operator; iteration.* decodes into
        # directives (and is silently dropped from a non-iteration envelope).
        raise RenderError(
            f"param {key!r} is non-canonical on an Expression — "
            "use the broadcast flag / Iteration.directives"
        )
    if not top and is_source_level_key(key):
        raise RenderError(
            f"param {key!r} is exclusively source-level (§8.1.3) — on reparse it "
            "would leave the nested expression and become a source annotation"
        )
    guard.check_param(key, value)
    if value is None:
        return f";{key}"
    guard.check_no_structural(value, "param value", top=top)
    return f";{key}={value}"


def _render_intent(node: Node, *, top: bool = False) -> str:
    # INVARIANT: this must stay in lockstep with `grammar.intent_atom` —
    # anything intent_atom can PRODUCE, this must render back, or a parseable
    # expression becomes unrenderable and render() stops being parse()'s
    # inverse.
    if isinstance(node, Text):
        return _quote(node.value)
    if isinstance(node, (Url, RelUrl)):
        # A top-level absolute-URL intent is the text's tail: Spec B §8
        # `bare-value`. Elsewhere, and for a `/path` code pointer (whose
        # balanced parens, `/reduce()`, are legal), a depth-0 `!` or `,` would
        # split the intent, a `;` would split off params, and an unbalanced `(`
        # would swallow what follows.
        if top and isinstance(node, Url):
            guard.check_tail_uri(node.value)
        else:
            guard.scan_uri(node.value, allow_parens=True, forbid="',;!")
        return node.value
    if isinstance(node, VarRef):
        # INVARIANT: `intent_atom` does not produce a VarRef (see its
        # `_INTENT_VALUE_HEADS`), so rendering one would emit `$a`, which reparses
        # as Text — render would stop being parse's inverse. Reject it instead.
        raise RenderError(
            "VarRef cannot be an intent — a `$ref` in intent position is text that "
            "resolves by substitution, so rendering one would not reparse to itself"
        )
    # The widened value forms (nested expression, iteration, struct object,
    # self/identity ref) share the value renderers.
    text = _render_value(node)
    guard.check_structured_intent(node, text)
    return text


# --- source descriptors -----------------------------------------------------------


def _render_source(node: Node) -> str:
    if isinstance(node, Binding):
        return _render_binding(node)
    if isinstance(node, Source):
        return _render_descriptor(node)
    value, tail = _source_value_and_tail(node)
    return value + tail


def _render_binding(node: Binding) -> str:
    guard.check_binding_name(node.name)
    value, tail = _source_value_and_tail(node.value)
    if node.kind == "=":
        return f"{node.name}={value}{tail}"
    return f"{node.name}:{_data_binding(value)}{tail}"


def _render_descriptor(node: Source) -> str:
    value, tail = _source_value_and_tail(node.value)
    if _is_descriptor_empty(node):
        raise RenderError(
            "a Source with no weight/budgets/annotations/expand has no descriptor "
            "form — the grammar parses that shape as Binding; construct one instead"
        )
    if node.budgets and node.name is None and node.weight is None:
        # 'tokens=…' at the head of a token is captured by the name=value sugar
        # test before descriptor parsing ever runs — parser-unreachable shape.
        raise RenderError(
            "an unnamed, weightless Source with budgets is ambiguous with the "
            "name=value sugar form — give the source a name or a weight"
        )
    if isinstance(node.weight, dict) and node.name is None:
        # A token-initial '(' is value-shaped (§4.3) and parses as an expression
        # before the §4.1.1.4 weight-position classifier ever runs.
        raise RenderError(
            "an unnamed structured weight would sit token-initial and reparse as "
            "an expression source list — give the source a name (spec §4.1.1.2)"
        )
    _guard_annotation_boundary(node)
    guard.check_annotations(node.annotations, node.value)
    chain = _descriptor_chain(node)
    chain.append(_data_binding(value, after_colon=bool(chain)))
    out = ":".join(chain) + tail + _render_annotations(node.annotations)
    return ("*" + out) if node.expand else out


def _is_descriptor_empty(node: Source) -> bool:
    return node.weight is None and not node.budgets and not node.annotations and not node.expand


def _descriptor_chain(node: Source) -> list[str]:
    chain: list[str] = []
    if node.name is not None:
        if node.name == "src" or not _IDENT_RE.fullmatch(node.name):
            raise RenderError(f"invalid source name {node.name!r}")
        chain.append(node.name)
    if node.weight is not None:
        chain.append(_render_weight(node.weight))
    for key, value in node.budgets:
        if key in ("src", "weight") or not _IDENT_RE.fullmatch(key):
            raise RenderError(f"invalid budget key {key!r}")
        chain.append(f"{key}={_render_budget_value(value)}")
    return chain


def _guard_annotation_boundary(node: Source) -> None:
    """Reject annotation orders the §8.1.2 boundary algorithm would re-scope.

    When the data binding is an expression, a reparse routes leading ``;`` keys
    to the *expression's* params until the first exclusively-source-level key.
    """
    if not isinstance(node.value, _EXPR_VALUED):
        return
    boundary = False
    for key, _ in node.annotations:
        boundary = boundary or is_source_level_key(key)
        if not boundary:
            raise RenderError(
                f"annotation {key!r} on an expression-valued source precedes any "
                "exclusively source-level key — reparse would re-scope it to the "
                "expression (spec §8.1.2); reorder annotations (e.g. mode= first)"
            )


def _render_annotations(annotations: Params) -> str:
    parts: list[str] = []
    for key, value in annotations:
        if value is None:
            parts.append(f";{key}")
        else:
            guard.check_no_structural(value, "annotation value", top=False)
            parts.append(f";{key}={value}")
    return "".join(parts)


def _source_value_and_tail(value: Node) -> tuple[str, str]:
    """A source-position value plus its ``;iteration.*`` tail (spec §5.3.6).

    Iteration directives live on the source token's ``;`` chain, from where the
    parser folds them back into the Iteration node — every source-level caller
    (bare source, Binding, Source) must emit them.
    """
    if isinstance(value, Iteration):
        _check_value_iteration(value)
        return _render_iteration_core(value), _render_directives(value.directives)
    return _render_value(value), ""


def _data_binding(value_text: str, *, after_colon: bool = True) -> str:
    """The attribution chain's final segment; ``src=`` when not value-shaped.

    After a ``:`` a value starting ``//`` also takes ``src=``: ``name:`` plus
    ``//…`` forms ``name://…``, which the parser reads as one bare URI.
    """
    double_slash = after_colon and value_text.startswith("//")
    return (
        value_text
        if _is_value_shaped_text(value_text) and not double_slash
        else f"src={value_text}"
    )


def _is_value_shaped_text(text: str) -> bool:
    if text[0] in "'(/@{$":
        return True
    colon = find_top_level(text, ":")
    return colon is not None and text[colon : colon + 3] == "://"


# --- values ----------------------------------------------------------------------------


def _render_value(node: Node) -> str:
    renderer = _VALUE_RENDERERS.get(type(node))
    if renderer is None:
        if isinstance(node, (Binding, Source)):
            raise RenderError(f"{type(node).__name__} is not valid in a value position")
        raise TypeError(f"cannot render {type(node).__name__}")
    return renderer(node)


def _quote(content: str) -> str:
    return "'" + content.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _render_url(node: Url) -> str:
    if _SCHEME_RE.match(node.value) is None:
        raise RenderError(f"Url value {node.value!r} has no scheme:// prefix")
    guard.scan_uri(node.value, allow_parens=True, forbid="',;!")
    return node.value


def _render_relurl(node: RelUrl) -> str:
    if not node.value.startswith("/"):
        raise RenderError(f"RelUrl value {node.value!r} must start with '/'")
    # WHY: any '(' would reparse as a sugar-form RelExpr; ',;!' split at depth
    # 0. Quoting is no escape hatch — it would change the node type to Text.
    guard.scan_uri(node.value, allow_parens=False, forbid="',;!()")
    return node.value


def _render_varref(node: VarRef) -> str:
    guard.check_varref_name(node.name)
    out = f"${node.name}"
    for seg in node.path:
        if isinstance(seg, int):
            out += f"[{seg}]" if seg >= 0 else _raise_seg(seg)
        else:
            out += f".{seg}" if _IDENT_RE.fullmatch(seg) else _raise_seg(seg)
    return out


def _raise_seg(seg: object) -> str:
    raise RenderError(f"invalid field-path segment {seg!r}")


def _render_identity(node: IdentityRef) -> str:
    if not _IDENTITY_NAME_RE.fullmatch(node.name):
        raise RenderError(f"invalid identity name {node.name!r}")
    if node.collection is None:
        return f"@{node.name}"
    guard.check_identity_collection(node.collection)
    return f"@{node.name}/{node.collection}"


def _render_struct_object(node: StructObject) -> str:
    if not node.raw.startswith("{") or _braces_end(node.raw) != len(node.raw):
        raise RenderError(f"StructObject raw text {node.raw!r} is not one balanced {{…}} group")
    return node.raw


def _braces_end(text: str) -> int | None:
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            i = skip_quoted(text, i)
            continue
        depth += 1 if ch == "{" else -1 if ch == "}" else 0
        if depth == 0:
            return i + 1
        i += 1
    return None


# --- relative / remote expressions ------------------------------------------------------


def _render_relexpr(node: RelExpr, *, top: bool = False) -> str:
    return _render_target_expr("", node.path, node, top=top)


def _render_remoteexpr(node: RemoteExpr, *, top: bool = False) -> str:
    if not node.authority or any(ch in node.authority for ch in "/?('"):
        raise RenderError(f"invalid remote authority {node.authority!r}")
    return _render_target_expr(f"url4://{node.authority}", node.path, node, top=top)


def _render_target_expr(
    prefix: str, path: str, node: RelExpr | RemoteExpr, *, top: bool = False
) -> str:
    if node.intent is None:
        # INVARIANT: every call production carries `intent-op intent`
        # (`OME-508`) — an intent-less RelExpr/RemoteExpr has no surface form.
        # A path with no context is a RelUrl (`relative-uri`), a different node.
        raise RenderError(
            f"call {path!r} has no intent — a relative or remote expression must "
            "carry !intent; for a plain data fetch use RelUrl instead"
        )
    _check_path(path)
    context = _checked_context(node.context)
    intent = "!" + _render_intent(node.intent, top=top)
    if not node.params:
        return f"{prefix}{path}({context}){intent}"
    query = "&".join(_render_query_param(k, v) for k, v in node.params)
    return f"{prefix}{path}?{query}&q=({context}){intent}"


def _check_path(path: str) -> None:
    # §8 `path = segment *( "/" segment )`. Reads the GRAMMAR's pattern rather
    # than re-deriving the charset — the parse side enforces the same one, so
    # anything that parses re-renders (`OME-507` closed that asymmetry).
    if not PATH_RE.fullmatch(path):
        raise RenderError(f"invalid expression path {path!r}")


def _checked_context(context: str | None) -> str:
    if context is None:
        return ""
    if balanced_body(f"({context})", 1) != context or context != context.strip():
        raise RenderError(f"context {context!r} is unbalanced or unstripped")
    return context


def _render_query_param(key: str, value: str | None) -> str:
    guard.check_param(key, value)
    if value is None:
        return key
    # WHY: no comma exemption here — a rel/remote token always ends up inside
    # a comma-split source list (top-level renders wrap it in parens too).
    guard.check_no_structural(value, "query param value", top=False, forbid_extra="&")
    return f"{key}={value}"


# --- iteration ---------------------------------------------------------------------------


def _render_top_iteration(node: Iteration, *, envelope: bool) -> str:
    collection = _render_collection(node.collection)
    inner = _join_iteration(node, collection, top=True) + _render_directives(node.directives)
    out = inner if node.reducer is None else _render_reduce(node, inner, node.reducer)
    if envelope:
        guard.check_iteration_envelope(out, node, collection)
    return out


def _render_reduce(node: Iteration, inner: str, reducer: str) -> str:
    if isinstance(node.collection, (Source, Binding)):
        # The reduce-over-iteration decode rejects descriptored collections
        # (§5.3.10 — the descriptor attributes the iteration in the enclosing
        # expression), so this shape has no faithful text form.
        raise RenderError("reduce-over-iteration cannot carry a descriptored collection")
    guard.check_raw_tail(reducer, "reducer", top=True)
    return f"({inner})!{reducer}"


def _render_iteration_core(node: Iteration) -> str:
    collection = _render_collection(node.collection)
    if collection.startswith("'"):
        # Only the top-level envelope reads a quoted collection back; a nested one is
        # `unexpected text after quoted value` (found by test_roundtrip_laws).
        raise RenderError(f"a nested iteration cannot take the quoted collection {collection}")
    return _join_iteration(node, collection, top=False)


def _join_iteration(node: Iteration, collection: str, *, top: bool) -> str:
    if isinstance(node.collection, Iteration):
        raise RenderError("an iteration cannot be another iteration's collection")
    if balanced_body(f"({node.body})", 1) != node.body:
        raise RenderError(f"iteration body {node.body!r} is unbalanced")
    if node.intent is None:
        # INVARIANT: iteration-expr takes a full expression after "*" — the
        # per-row intent is mandatory (`OME-508`), so a map-only Iteration has
        # no surface form.
        raise RenderError(
            "an Iteration without a per-row intent has no surface form — the "
            "expression after '*' must carry !intent (src*(body)!intent)"
        )
    guard.check_raw_tail(node.intent, "iteration intent", top=top)
    return f"{collection}*({node.body})!{node.intent}"


def _render_collection(node: Node) -> str:
    """Render a collection-ref — the one position where a bare paren group is
    legal (``paren-collection`` is its own intent-less production)."""
    if isinstance(node, Expression) and node.intent is None:
        if node.broadcast or node.params:
            raise RenderError(
                "a paren-collection carries no broadcast flag or params — those "
                "belong to an intent-bearing expression"
            )
        return "(" + ", ".join(_render_source(s) for s in node.sources) + ")"
    return _render_source(node)


def _check_value_iteration(node: Iteration) -> None:
    if node.reducer is not None:
        raise RenderError(
            "reduce-over-iteration is a top-level envelope shape — nested, wrap it as "
            "Expression(sources=(iteration,), intent=reducer) instead"
        )
    if isinstance(node.collection, (Source, Binding)):
        raise RenderError(
            "a descriptored collection reparses as Source(value=Iteration) in a value "
            "position — put the descriptor on the source instead"
        )


def _render_value_iteration(node: Iteration) -> str:
    _check_value_iteration(node)
    if node.directives != _DEFAULT_DIRECTIVES:
        raise RenderError(
            "iteration directives are carried on the source's ';' chain — this "
            "iteration sits in a non-source value position and cannot emit them"
        )
    return _render_iteration_core(node)


def _render_directives(d: IterationDirectives) -> str:
    parts: list[str] = []
    if d.concurrency is not None:
        parts.append(f";iteration.concurrency={d.concurrency}")
    if d.on_error != _DEFAULT_DIRECTIVES.on_error:
        parts.append(f";iteration.on_error={d.on_error}")
    if d.slice is not None:
        parts.append(f";iteration.slice={d.slice[0]}:{d.slice[1]}")
    if d.fmt_result is not None:
        guard.check_token(d.fmt_result, "iteration.fmt_result", extra_allowed="._-")
        parts.append(f";iteration.fmt_result={d.fmt_result}")
    return "".join(parts)


# --- structured annotation values (weights / budgets) -------------------------------------


def _render_weight(weight: float | dict) -> str:
    if isinstance(weight, dict):
        return _render_struct_annotation(weight, nested=False)
    return _format_number(weight)


def _render_budget_value(value: str | dict | int | float) -> str:
    if isinstance(value, dict):
        return _render_struct_annotation(value, nested=False)
    if isinstance(value, (int, float)):
        return _format_number(value)
    guard.check_token(value, "budget value", extra_allowed="._-")
    return value


def _render_struct_annotation(entries: dict, *, nested: bool) -> str:
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
        result = _render_struct_annotation(value, nested=True)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        result = _format_number(value)
    elif isinstance(value, str):
        # a number-shaped string must quote — bare it would reparse as float
        bare_ok = _STRUCT_TOKEN_RE.fullmatch(value) and not _NUMBER_RE.fullmatch(value)
        result = value if bare_ok else _quote(value)
    else:
        raise RenderError(f"invalid structured annotation value {value!r}")
    return result


def _format_number(value: float | int) -> str:
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


_VALUE_RENDERERS: dict[type, Callable] = {
    Text: lambda n: _quote(n.value),
    Url: _render_url,
    RelUrl: _render_relurl,
    VarRef: _render_varref,
    SelfRef: lambda _n: "@",
    IdentityRef: _render_identity,
    StructObject: _render_struct_object,
    Expression: _render_expression,
    RelExpr: _render_relexpr,
    RemoteExpr: _render_remoteexpr,
    Iteration: _render_value_iteration,
}

__all__ = ["render", "verify"]
