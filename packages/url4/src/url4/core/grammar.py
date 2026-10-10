"""Recursive-descent parser for url4 source expressions.

This module owns the low-level :func:`parse`. It parses a *source expression* —
the part to the left of a top-level ``!`` — into the typed AST in
:mod:`url4.core.nodes`. The top-level ``!intent`` split, the ``;`` expression-param
envelope, and the top-level ``src*(body)`` iteration split are handled one
level up in :mod:`url4.core.parser` / :mod:`url4.dag.compiler`.

Why recursive descent rather than a PEG: the spec's parsing rules are
procedural and *committing*. The §4.1.1.4 structured-value classifier commits
on its first entry and MUST NOT backtrack (a post-commitment violation is
``malformed_source``, not a reclassification); ``*`` is structural only in two
exact positions (§5.3.3); and canonical-form detection scans for ``q=(`` with
an explicit rewind rule (§5.2 rule 16). Ordered-choice PEG backtracking cannot
express commitment, so the spec's numbered rules are implemented directly —
one small function per rule — on top of the depth/quote-aware scanners in
:mod:`url4.core._scan`.

Layering: descriptor decoding (§4.3) wraps value detection (§5.2). A source
token is first split on depth-0 ``;`` (the execution chain), the head is
classified as a bare value / ``name=`` sugar / attribution chain, and the
trailing annotations are routed by the §8.1.2 boundary algorithm — expression
params onto :class:`~url4.core.nodes.RelExpr` / :class:`~url4.core.nodes.RemoteExpr` /
:class:`~url4.core.nodes.Expression`, everything else onto the
:class:`~url4.core.nodes.Source` wrapper.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from url4.core._annotations import (
    classify_boundary,
    extract_directives,
    fold_broadcast,
    split_annotation_pairs,
    validate_exec_annotations,
    validate_params,
)
from url4.core._call_head import (
    REMOTE_SCHEME,
    check_authority,
    check_data_path,
    check_expr_path,
    decode_query_params,
    find_expression_param,
    remote_path_offset,
)
from url4.core._lexical import (
    _BARE_VALUE_RE,
    _BUDGET_KEY_RE,
    _FIELD_SEG_RE,
    _IDENT_RE,
    _IDENTITY_RE,
    _INDEX_SEG_RE,
    _NUMBER_RE,
    _PATH_SEGMENT_RE,
    _SCHEME_RE,
    _VARREF_HEAD_RE,
    _unquote,
    reject_chained_intent,
)
from url4.core._lexical import _IDENTITY_NAME_RE as _IDENTITY_NAME_RE
from url4.core._scan import (
    balanced_body,
    balanced_braces,
    find_unquoted,
    iter_iteration_stars,
    one_paren_layer,
    skip_quoted,
    split_top_level,
)
from url4.core._struct_values import (
    _classify_weight_group,
    _parse_budget_value,
    _parse_weight_value,
)
from url4.core.descriptor_head import classify_head, first_colon, is_value_shaped
from url4.core.errors import ErrorCode, ParseError
from url4.core.nodes import (
    Binding,
    Expression,
    IdentityRef,
    Iteration,
    IterationDirectives,
    NamedJob,
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


def parse(text: str) -> Node:
    """Parse a url4 source expression into a typed AST node.

    Raises :class:`~url4.core.errors.ParseError` (code ``malformed_source``) if the
    text is not valid url4.
    """
    stripped = text.strip()
    if not stripped:
        raise ParseError("empty url4 expression")
    return _parse_source(stripped)


def parse_value(text: str) -> Node:
    """Classify ``text`` by the §5.2 value-detection rules alone (no descriptor).

    The value-position entry point for callers that already know the token is a
    data value — the builder facade uses it so a Python string is classified
    exactly as the grammar would classify it (a plain word is a bare token, a
    ``scheme://`` is a URI, …), never re-interpreted as an attribution chain.
    """
    stripped = text.strip()
    if not stripped:
        raise ParseError("empty url4 value")
    return _parse_value(stripped)


# --- source descriptors (§4.3) -------------------------------------------------


@dataclass
class _Descriptor:
    """The attribution chain decoded from a source token's head."""

    value: Node
    name: str | None = None
    kind: str = "="
    weight: float | dict | None = None
    budgets: list[tuple[str, str | dict]] = field(default_factory=list)


def _parse_source(token: str) -> Node:
    token = token.strip()
    if not token:
        raise ParseError("empty source")
    if token.startswith("*") and len(token) > 1:
        # §5.2 rule 9 — source-initial '*' is the expansion prefix; the
        # remainder undergoes full source parsing.
        return _mark_expand(_parse_source(token[1:]))
    parts = split_top_level(token, ";")
    if not parts[0]:
        raise ParseError(f"source has no value before ';' in {token!r}")
    tail = split_annotation_pairs(parts[1:])
    return _attach_tail(_parse_head(parts[0]), tail)


def _mark_expand(node: Node) -> Source:
    if isinstance(node, Source):
        return replace(node, expand=True)
    if isinstance(node, Binding):
        return Source(value=node.value, name=node.name, expand=True)
    return Source(value=node, expand=True)


def _parse_head(head: str) -> _Descriptor:
    """Decode the pre-``;`` part: bare value, ``src=`` value, ``name=`` sugar, or chain.

    The classification is :func:`~url4.core.descriptor_head.classify_head`,
    the one owner the DAG text path shares.
    """
    form, name, value = classify_head(head)
    if form == "chain":
        return _parse_attrib_chain(head)
    return _Descriptor(value=_parse_value(value), name=name, kind="=")


def _parse_attrib_chain(head: str) -> _Descriptor:
    """Walk ``:``-separated attribution segments up to the data binding."""
    d = _Descriptor(value=Text(""), kind=":")
    rest = head
    first = True
    while True:
        rest = rest.strip()
        if not rest:
            raise ParseError(f"empty data binding after ':' in descriptor {head!r} (spec §4.3)")
        if rest.startswith("src="):
            d.value = _parse_value(rest[4:])
            return d
        if rest.startswith("(") and d.weight is None:
            # '(' in the weight position: §4.1.1.4 first-entry classification.
            struct = _classify_weight_group(rest)
            if struct is None:
                d.value = _parse_value(rest)
                return d
            d.weight, rest = struct
            first = False
            continue
        if is_value_shaped(rest):
            d.value = _parse_value(rest)
            return d
        colon = first_colon(rest)
        if colon is None:
            raise ParseError(
                f"bare-token data binding requires 'src=' in descriptor {head!r} (spec §4.3)"
            )
        _classify_segment(rest[:colon].strip(), first, d, head)
        rest = rest[colon + 1 :]
        first = False


def _classify_segment(seg: str, first: bool, d: _Descriptor, head: str) -> None:
    """§4.3 segment classification: name (first only), weight, or budget."""
    key, eq, val = seg.partition("=")
    if first and _IDENT_RE.fullmatch(seg) and seg != "src":
        d.name = seg
    elif _NUMBER_RE.fullmatch(seg) and d.weight is None:
        d.weight = float(seg)
    elif key == "weight" and eq and d.weight is None:
        d.weight = _parse_weight_value(val)
    elif eq and _BUDGET_KEY_RE.fullmatch(key) and key not in ("src", "weight"):
        d.budgets.append((key, _parse_budget_value(val)))
    else:
        raise ParseError(f"cannot classify descriptor segment {seg!r} in {head!r}")


# --- execution-chain routing (§4.2, §8.1.2) --------------------------------------


def _attach_tail(d: _Descriptor, tail: Params) -> Node:
    """Route the ``;`` chain and wrap the descriptor per contract."""
    value = d.value
    if isinstance(value, (RelExpr, RemoteExpr, Expression)):
        expr_params, source_ann = classify_boundary(tail)
        # `expr-param = param-key "=" param-value`: the rule the envelope applies.
        validate_params(expr_params)
        value = _add_expr_params(value, expr_params)
    else:
        source_ann = tail
    # INVARIANT: validate the EXEC axis only, and only after the §8.1.2 boundary
    # has separated it from expression params — expression `param-key`s may carry
    # digits, exec-keys may not (`OME-504`).
    validate_exec_annotations(source_ann)
    source_ann, expand = _extract_expand(source_ann)
    if isinstance(value, Iteration):
        source_ann, directives = _fold_directives(value, source_ann)
        if directives is not None:
            value = replace(value, directives=directives)
    if d.weight is None and not d.budgets and not source_ann and not expand:
        if d.name is not None:
            return Binding(d.name, value, "=" if d.kind == "=" else ":")
        return value
    return Source(
        value=value,
        name=d.name,
        weight=d.weight,
        budgets=tuple(d.budgets),
        annotations=source_ann,
        expand=expand,
    )


def _add_expr_params(
    value: RelExpr | RemoteExpr | Expression, params: Params
) -> RelExpr | RemoteExpr | Expression:
    # B4: on a local expression ';broadcast' IS the '!*' flag (one owner,
    # `fold_broadcast`); a call keeps it as a param its node decodes.
    if isinstance(value, Expression):
        flag, params = fold_broadcast(params)
        value = replace(value, broadcast=True) if flag else value
    return value if not params else replace(value, params=value.params + params)


def _extract_expand(annotations: Params) -> tuple[Params, bool]:
    rest = tuple(pair for pair in annotations if pair[0] != "expand")
    return rest, len(rest) != len(annotations)


def _fold_directives(
    value: Iteration, annotations: Params
) -> tuple[Params, IterationDirectives | None]:
    rest, directives = extract_directives(annotations)
    return rest, directives if len(rest) != len(annotations) else None


# --- value detection (§5.2) -------------------------------------------------------


def _parse_value(token: str) -> Node:
    token = token.strip()
    if not token:
        raise ParseError("empty value")
    star = _find_iteration_star(token)
    if star is not None:
        return _parse_iteration(token, star)
    return _dispatch_value(token)


def _dispatch_value(token: str) -> Node:
    if token.startswith("url4://"):
        node: Node = _parse_remote(token)
    elif (handler := _VALUE_HANDLERS.get(token[0])) is not None:
        node = handler(token)
    else:
        node = _var_or_bare(token)
    return node


def _var_or_bare(token: str) -> Node:
    var = _try_varref(token) if token[0] == "$" else None
    return var if var is not None else _parse_bare(token)


def _parse_quoted_value(token: str) -> Text:
    return Text(_unquote(token))


def _find_iteration_star(token: str) -> int | None:
    """The depth-0 ``*(`` iteration operator's position, if present (§5.3.3).

    A source-initial ``*`` (the first non-space character) is the expansion
    prefix, not iteration — :func:`iter_iteration_stars` never yields it.
    """
    return next(iter_iteration_stars(token), None)


# --- iteration (§5.3) ---------------------------------------------------------------


def _parse_iteration(token: str, star: int) -> Iteration:
    body = balanced_body(token, star + 2)
    if body is None:
        raise ParseError(f"unclosed iteration body in {token!r}", position=star + 1)
    after = token[star + 2 + len(body) + 1 :]
    intent: str | None = None
    if after.startswith("!"):
        intent = after[1:].strip() or None
        reject_chained_intent(after[1:])
    elif after.strip():
        raise ParseError(f"unexpected text after iteration body: {after!r}")
    if intent is None:
        # INVARIANT: iteration-expr = collection-ref "*" expression — the
        # expression after "*" carries a mandatory intent (`OME-508`), so a
        # map-only `src*(body)` has no grammar form.
        raise ParseError(
            f"iteration {token!r} has no per-row intent — the expression after "
            "'*' must carry !intent (src*(body)!intent)",
            code=ErrorCode.MISSING_INTENT,
            position=star,
        )
    return Iteration(collection=_parse_collection(token[:star]), body=body.strip(), intent=intent)


def _parse_collection(token: str) -> Node:
    """Parse a collection-ref: a bare paren-collection is legal HERE only.

    ``paren-collection`` is its own production, disambiguated by the ``*(``
    lookahead — it never carries an intent, so it must not go through the
    strict local-expr path.
    """
    stripped = token.strip()
    if stripped.startswith("*"):
        # A collection-ref is a value, and a value never starts with '*' (the
        # expansion prefix marks a source): `n=*x*(b)!i` has no reading (§8 rule 5).
        raise ParseError(
            f"a collection cannot start with '*' in {token!r} — a collection is a value"
        )
    if (body := one_paren_layer(stripped)) is not None:
        return Expression(sources=_parse_group_sources(body))
    return _parse_value(token)


# --- local expressions (§5.2 rule 1) --------------------------------------------------


def _parse_local_expr(token: str) -> Expression:
    body = balanced_body(token, 1)
    if body is None:
        raise ParseError(f"unclosed '(' in {token!r}", position=0)
    after = token[len(body) + 2 :]
    sources = _parse_group_sources(body)
    if not after:
        # INVARIANT: local-expr = "(" source-list ")" intent-op intent — the
        # intent is not optional (`OME-508`). Intent-less parens are legal only
        # as a paren-collection (before "*", parsed by _parse_iteration) or via
        # parse_group_root, where an envelope holds the intent externally.
        raise ParseError(
            f"expression group {token!r} has no intent — a parenthesized source "
            "group must be followed by !intent (or !*intent)",
            code=ErrorCode.MISSING_INTENT,
        )
    if after.startswith("!*"):
        return Expression(sources=sources, intent=intent_atom(after[2:]), broadcast=True)
    if after.startswith("!"):
        return Expression(sources=sources, intent=intent_atom(after[1:]))
    raise ParseError(f"unexpected text after group: {after!r}")


def parse_group_root(text: str) -> Node:
    """Parse text whose intent, if any, is held EXTERNALLY by the caller.

    The envelope decoders split the top-level ``!intent`` off before the
    grammar ever sees the source side, and an iteration's paren-collection
    never carries one — both positions legally present a bare ``(…)`` here.
    Everything else routes through the strict :func:`parse`.
    """
    stripped = text.strip()
    if (body := one_paren_layer(stripped)) is not None:
        return Expression(sources=_parse_group_sources(body))
    return parse(stripped)


def _parse_group_sources(body: str) -> tuple[Node, ...]:
    if not body.strip():
        return ()
    return tuple(_parse_source(part) for part in split_top_level(body, ","))


# --- relative and remote expressions (§5.2 rules 2–3, §3.1.1) --------------------------


def _parse_relative(token: str) -> RelUrl | RelExpr:
    pos = find_unquoted(token, "?(")
    if pos is None:
        check_data_path(token)
        return RelUrl(token)
    if token[pos] == "(":
        return _parse_expr_sugar(token, pos)
    return _parse_expr_canonical(token, pos)


def _parse_expr_sugar(token: str, paren: int) -> RelExpr:
    """Sugar form ``/path(context)!intent`` (§3.1.1.1)."""
    body = balanced_body(token, paren + 1)
    if body is None:
        raise ParseError(f"unclosed '(' in {token!r}", position=paren)
    after = token[paren + 1 + len(body) + 1 :]
    check_expr_path(token[:paren], token)
    return RelExpr(
        path=token[:paren],
        context=body.strip() or None,
        intent=_parse_expr_intent(after, token),
    )


def _parse_expr_canonical(token: str, qmark: int) -> RelUrl | RelExpr:
    """Canonical form ``/path?[params&]q=(context)!intent`` (§5.2 rule 7a).

    ``?`` without a ``q=(`` parameter is the rewind rule (§8 parse rule 16):
    the whole token is a relative data URI with a query string.
    """
    qstart = find_expression_param(token, qmark)
    if qstart is None or token[qstart + 2 : qstart + 3] != "(":
        # §8 parse rule 16 rewind — this is a `relative-uri`, not an expression.
        check_data_path(token)
        return RelUrl(token)
    body_start = qstart + 2  # past "q="
    body = balanced_body(token, body_start + 1)
    if body is None:
        raise ParseError(f"unclosed '(' in {token!r}", position=body_start)
    after = token[body_start + 1 + len(body) + 1 :]
    check_expr_path(token[:qmark], token)
    return RelExpr(
        path=token[:qmark],
        context=body.strip() or None,
        intent=_parse_expr_intent(after, token),
        params=decode_query_params(token[qmark + 1 : qstart].rstrip("&")),
    )


def _parse_expr_intent(after: str, token: str) -> Node:
    """The mandatory ``!intent`` tail of a relative/remote expression.

    # INVARIANT: all four call productions carry ``intent-op intent`` — the
    # sugar forms name it directly, the canonical forms inherit it from the
    # ``expression`` after ``q=`` (`OME-508`). This is the one choke point both
    # ``_parse_expr_sugar`` and ``_parse_expr_canonical`` funnel through, so
    # they cannot drift. An intent-LESS ``/path`` or ``/path?a=1`` never
    # reaches here: it has no ``(`` context and no depth-0 ``q=(``, so it is a
    # ``relative-uri`` data fetch and returns earlier as a RelUrl.
    """
    if not after:
        raise ParseError(
            f"call {token!r} has no intent — a relative or remote expression must "
            "be followed by !intent (a path with no context is a data URI)",
            code=ErrorCode.MISSING_INTENT,
        )
    if after.startswith("!"):
        # AIDEV-NOTE: `intent-op` admits `!*` here too, but RelExpr/RemoteExpr
        # carry no broadcast flag — a `!*` tail keeps its existing reading (the
        # `*` lands in the intent text) rather than being silently dropped.
        # Representing a broadcast call needs a node field; out of `OME-508`.
        return intent_atom(after[1:])
    raise ParseError(f"unexpected text after expression body in {token!r}")


def _parse_remote(token: str) -> Node:
    slash = remote_path_offset(token)
    paren = find_unquoted(token, "(", len(REMOTE_SCHEME))
    if paren is not None and (slash is None or paren < slash):
        raise ParseError(f"remote expression requires a path: {token!r}")
    if slash is None:
        return Url(token)
    authority = token[len(REMOTE_SCHEME) : slash]
    check_authority(authority, token)
    inner = _parse_relative(token[slash:])
    if isinstance(inner, RelUrl):
        return Url(token)  # §5.2 rule 3.3 — bare remote reference
    return RemoteExpr(
        authority=authority,
        path=inner.path,
        context=inner.context,
        intent=inner.intent,
        params=inner.params,
    )


# --- leaf values (§5.2 rules 4–10) -------------------------------------------------


def _parse_struct_object(token: str) -> StructObject:
    end = _balanced_braces(token)
    if end is None:
        raise ParseError(f"unclosed '{{' in {token!r}", position=0)
    if token[end:].strip():
        raise ParseError(f"unexpected text after structured object in {token!r}", position=end)
    return StructObject(raw=token[:end])


def _balanced_braces(token: str) -> int | None:
    return balanced_braces(token, 0)


def _parse_reference(token: str) -> SelfRef | IdentityRef:
    """``@`` / ``@name[/collection]`` (§5.2 rule 7, §5.6.2)."""
    if token == "@":
        return SelfRef()
    m = _IDENTITY_RE.match(token)
    if m is None:
        raise ParseError(f"invalid reference {token!r} (spec §5.6.2)")
    rest = token[m.end() :]
    if not rest:
        return IdentityRef(m.group(1))
    if rest.startswith("/"):
        collection = rest[1:]
        segments = collection.split("/")
        if all(_PATH_SEGMENT_RE.fullmatch(seg) for seg in segments):
            return IdentityRef(m.group(1), collection)
    raise ParseError(f"invalid identity reference {token!r} (spec §5.6.2)")


def _try_varref(token: str) -> VarRef | None:
    """A standalone ``$name[.field][N]`` reference consuming the whole token.

    Partial consumption (e.g. ``$a b`` or ``$$x``) is not a structural
    reference — the token stays a bare value and the interpolation phase
    (spec §8.2) handles any embedded references at resolve time.
    """
    m = _VARREF_HEAD_RE.match(token)
    if m is None:
        return None
    path: list[str | int] = []
    i = m.end()
    while i < len(token):
        step = _varref_segment(token, i, path)
        if step is None:
            break
        i = step
    return VarRef(m.group(1), tuple(path)) if i == len(token) else None


def _varref_segment(token: str, i: int, path: list[str | int]) -> int | None:
    result: int | None = None
    if token[i] == ".":
        seg = _FIELD_SEG_RE.match(token, i + 1)
        if seg is not None:
            path.append(seg.group())
            result = seg.end()
    elif token[i] == "[":
        # '[' not followed by digits ends the path (§8 rule 17b).
        idx = _INDEX_SEG_RE.match(token, i + 1)
        if idx is not None:
            path.append(int(idx.group(1)))
            result = idx.end()
    return result


def _parse_bare(token: str) -> Text | Url:
    """Bare-value consumption (§5.2 rules 5/10): any-scheme URI or plain text.

    Balanced ``(…)`` runs are tolerated inside URIs (``/wiki/Fish_(animal)``),
    preserving the pre-0.2 tolerance; in plain text a paren is structural and
    must be quoted (spec §7.2).
    """
    is_uri = _SCHEME_RE.match(token) is not None
    i = 0
    while i < len(token):
        ch = token[i]
        if ch == "'":
            i = skip_quoted(token, i)
        elif ch == "(" and is_uri:
            body = balanced_body(token, i + 1)
            if body is None:
                raise ParseError(f"unclosed '(' in {token!r}", position=i)
            i += len(body) + 2
        elif ch in "()":
            raise ParseError(f"unexpected {ch!r} in bare value {token!r}", position=i)
        else:
            i += 1
    return Url(token) if is_uri else Text(token)


# Dispatch by value-initial character (§5.2); populated after the handlers so
# the names are bound. ``url4://`` is tested before this table (it starts with
# a plain letter).
_VALUE_HANDLERS: dict[str, Callable[[str], Node]] = {
    "(": _parse_local_expr,
    "/": _parse_relative,
    "'": _parse_quoted_value,
    "{": _parse_struct_object,
    "@": _parse_reference,
}


# Value heads that an intent may open with (`intent = value`, ABNF §6). Quoted
# text, `scheme://` and `/path` are handled BEFORE this set is consulted — see
# `intent_atom`.
#
# INVARIANT: `$` is deliberately ABSENT. A `$ref` intent must stay `Text`: the
# TextNode path substitutes it against the run scope (`_substitute`), which is
# what makes `(a=…, b='$a again')!$b` resolve. Lowering it as a VarRef instead
# yields the literal string `$b` — verified by
# `test_execution.py::test_later_source_sees_earlier_binding`. Text IS the
# correct realization of a variable-ref intent, not a degraded one.
_INTENT_VALUE_HEADS = frozenset("({@")


def intent_atom(intent: str) -> Node:
    """Classify a raw intent string into an AST node (§6).

    Quoted → :class:`~url4.core.nodes.Text` content (quotes are delimiters);
    ``/path`` → a :class:`~url4.core.nodes.RelExpr` when it parses as a relative
    expression (§5.2 rules 2.1/2.2), else a :class:`~url4.core.nodes.RelUrl` (a code
    pointer, url4 2.0); any ``scheme://…`` → :class:`~url4.core.nodes.Url`. Otherwise
    ``intent = value`` applies and the token runs through full value detection,
    so a nested expression, an iteration, a struct object or a self/identity ref
    keeps its structure. One `bare-value` token is a :class:`~url4.core.nodes.NamedJob`
    (url4 2.0, P3); anything else is natural-language :class:`~url4.core.nodes.Text`.

    # WHY value detection matters here: the DAG compiler dispatches lowering by
    # node type, so an intent flattened to `Text` is never compiled into a
    # subgraph — `(a,b)!(c,d)!agg` would hand the literal string `"(c,d)!agg"` to
    # the model as a prompt instead of evaluating it.
    """
    text = intent.strip()
    reject_chained_intent(text)
    if text.startswith("'"):
        node: Node = Text(_unquote(text))
    elif _SCHEME_RE.match(text) is not None:
        node = Url(text)
    elif text.startswith("/"):
        node = _relative_intent(text)
    else:
        node = _intent_value_or_text(text)
    return node


def _relative_intent(text: str) -> Node:
    """A ``/path`` intent: the source parser's own reading, so the two cannot disagree.

    # WHY the ParseError fallback: 1.5.1 accepted ANY ``/…`` intent as a RelUrl
    # (``!/reduce()``), and url4 2.0 changes no acceptance — an invalid code pointer is
    # refused when it is lowered (``url4.core.intent.parse_code_pointer``), not here.
    """
    try:
        node = _parse_relative(text)
    except ParseError:
        return RelUrl(text)
    return node if isinstance(node, RelExpr) else RelUrl(text)


def _intent_value_or_text(text: str) -> Node:
    """Full value detection for an intent token, else natural-language ``Text``.

    # WHY: an intent is natural language FIRST. A token that merely looks like a
    # value head (``{not a struct``) must stay prompt text rather than become a
    # parse error — widening intent classification may not narrow what an author
    # is allowed to say.
    """
    if text[:1] not in _INTENT_VALUE_HEADS and _find_iteration_star(text) is None:
        # url4 2.0 (P3, Q6): one `bare-value` token is a named job; a `$` ref stays Text
        # (see _INTENT_VALUE_HEADS); prose with a space stays a prompt (url4 leniency).
        bare = _BARE_VALUE_RE.fullmatch(text) and text[:1] != "$" and "://" not in text
        return NamedJob(text) if bare else Text(text)
    try:
        return _parse_value(text)
    except ParseError:
        return Text(text)


__all__ = ["intent_atom", "parse", "parse_value"]
