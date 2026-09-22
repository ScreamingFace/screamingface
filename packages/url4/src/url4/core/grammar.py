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

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from url4.core._annotations import (
    classify_boundary,
    extract_directives,
    split_annotation_pairs,
    validate_exec_annotations,
    validate_param,
)
from url4.core._scan import (
    balanced_body,
    balanced_braces,
    find_unquoted,
    iter_iteration_stars,
    iter_top_level,
    one_paren_layer,
    skip_quoted,
    split_query_segments,
    split_top_level,
)
from url4.core.errors import ErrorCode, ParseError
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

# INVARIANT: the ABNF's ALPHA is ASCII. Python's `\w` is Unicode-aware by
# default, so every identifier pattern here compiles with re.ASCII — otherwise
# `$café` / `@bób` / `articleé=…` parse as identifiers the grammar does not
# admit (`OME-504`).
_IDENT_RE = re.compile(r"[A-Za-z_]\w*", re.ASCII)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?", re.ASCII)
_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://")
# identity-name = name-part / 1*DIGIT — a digit-led name followed by letters
# (`@9lives`) is NEITHER alternative and must not parse.
_IDENTITY_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+", re.ASCII)
_IDENTITY_RE = re.compile(rf"@({_IDENTITY_NAME_RE.pattern})", re.ASCII)
_VARREF_HEAD_RE = re.compile(r"\$([A-Za-z_]\w*|\d+)", re.ASCII)
_FIELD_SEG_RE = re.compile(r"[A-Za-z_]\w*", re.ASCII)
# path-segment (§ identity-collection) — the ABNF's explicit character class.
_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9\-_.~:@!$&+=]+", re.ASCII)
# INVARIANT: budget-key = 1*( ALPHA / "_" ) — digits are deliberately excluded.
_BUDGET_KEY_RE = re.compile(r"[A-Za-z_]+", re.ASCII)
# scalar-budget-value = 1*( ALPHA / DIGIT / "." / "-" / "_" )
_SCALAR_BUDGET_RE = re.compile(r"[A-Za-z0-9.\-_]+", re.ASCII)
_INDEX_SEG_RE = re.compile(r"(0|[1-9]\d*)\]")
_STRUCT_KEY_RE = re.compile(r"[A-Za-z0-9_]+")
_STRUCT_TOKEN_RE = re.compile(r"[A-Za-z0-9_.\-]+")

# §8 `path = segment *( "/" segment )`, `segment = *( ALPHA / DIGIT / "-" /
# "_" / "." / "~" )` — the NARROW charset, for expression-bearing paths
# (relative-expr / remote-expr).
# WHY: `render._check_path` reads this same pattern — keeps parse and render
# from drifting (`OME-507`).
_PATH_RE = re.compile(r"(?:/[A-Za-z0-9\-_.~]*)+", re.ASCII)

# `relative-uri`'s `path-segment` — the WIDE charset.
# WHY: it admits "$", which is what makes a variable-bearing data reference like
# `/data/$topic` legal. A data path is a DIFFERENT production from an expression
# path; narrowing it to match would break those references.
_DATA_PATH_RE = re.compile(r"(?:/[A-Za-z0-9\-_.~:@!$&+=]+)+", re.ASCII)

# `port = 1*DIGIT`.
# WHY: `host = hostname / IPv4address` is deliberately NOT validated — the grammar
# defines neither `hostname` nor `IPv4address`, so a charset here would assert a
# rule the spec does not state.
_PORT_RE = re.compile(r"[0-9]+", re.ASCII)


def _check_expr_path(path: str, token: str) -> None:
    """Validate an expression-bearing path against `path` / `segment`."""
    if not _PATH_RE.fullmatch(path):
        raise ParseError(
            f"invalid expression path {path!r} in {token!r} — a path segment takes "
            "ALPHA / DIGIT / '-' / '_' / '.' / '~'",
        )


def _check_data_path(token: str) -> None:
    """Validate a `relative-uri` path against `path-segment` (query-tail aside)."""
    path = token.partition("?")[0]
    if not _DATA_PATH_RE.fullmatch(path):
        raise ParseError(
            f"invalid data path {path!r} in {token!r}",
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
    """Decode the pre-``;`` part: bare value, ``name=`` sugar, or attrib chain.

    The sugar test runs before the bare-value test so ``article=https://x``
    binds ``article`` (§4.5) — the ``://`` inside the *value* must not promote
    the whole token to a bare URI.
    """
    if head.startswith("src="):
        result = _Descriptor(value=_parse_value(head[4:]))
    elif (sugar := _match_sugar(head)) is not None:
        result = _Descriptor(value=_parse_value(sugar[1]), name=sugar[0], kind="=")
    # The top-level colon scan is shared: _is_value_shaped needs it, and its
    # absence is itself the "no descriptor chain" test. Scanning once keeps
    # _parse_head linear in the token rather than walking it twice.
    elif (colon := _first_colon(head)) is None or _is_value_shaped(head, colon):
        result = _Descriptor(value=_parse_value(head))
    else:
        result = _parse_attrib_chain(head)
    return result


def _is_value_shaped(text: str, colon: int | None = None) -> bool:
    """§4.3 disambiguation — a token that is a bare data value, no descriptor.

    ``colon`` is the precomputed top-level colon index, for callers that already
    scanned for it; omitted, it is computed here.
    """
    if text[0] in "'(/@{$":
        return True
    if colon is None:
        colon = _first_colon(text)
    return colon is not None and text[colon : colon + 3] == "://"


def _first_colon(text: str) -> int | None:
    for i, ch in iter_top_level(text):
        if ch == ":":
            return i
    return None


def _match_sugar(head: str) -> tuple[str, str] | None:
    """``name=value`` with no ``:`` before the ``=`` (§4.3 sugar form)."""
    m = _IDENT_RE.match(head)
    if m is None or head[m.end() : m.end() + 1] != "=" or len(head) == m.end() + 1:
        return None
    return m.group(), head[m.end() + 1 :]


def _parse_attrib_chain(head: str) -> _Descriptor:
    """Walk ``:``-separated attribution segments up to the data binding."""
    d = _Descriptor(value=Text(""), kind=":")
    rest = head
    first = True
    while True:
        rest = rest.strip()
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
        if _is_value_shaped(rest):
            d.value = _parse_value(rest)
            return d
        colon = _first_colon(rest)
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


# --- structured annotation values (§4.1.1) --------------------------------------


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


# --- execution-chain routing (§4.2, §8.1.2) --------------------------------------


def _attach_tail(d: _Descriptor, tail: Params) -> Node:
    """Route the ``;`` chain and wrap the descriptor per contract."""
    value = d.value
    if isinstance(value, (RelExpr, RemoteExpr, Expression)):
        expr_params, source_ann = classify_boundary(tail)
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

    Source-initial ``*`` (position 0) is the expansion prefix, not iteration —
    it is consumed in :func:`_parse_source` before value detection begins.
    """
    return next(iter_iteration_stars(token, skip_leading=True), None)


# --- iteration (§5.3) ---------------------------------------------------------------


def _parse_iteration(token: str, star: int) -> Iteration:
    body = balanced_body(token, star + 2)
    if body is None:
        raise ParseError(f"unclosed iteration body in {token!r}", position=star + 1)
    after = token[star + 2 + len(body) + 1 :]
    intent: str | None = None
    if after.startswith("!"):
        intent = after[1:].strip() or None
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
        _check_data_path(token)
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
    _check_expr_path(token[:paren], token)
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
    qstart = _find_expression_param(token, qmark)
    if qstart is None or token[qstart + 2 : qstart + 3] != "(":
        # §8 parse rule 16 rewind — this is a `relative-uri`, not an expression.
        _check_data_path(token)
        return RelUrl(token)
    body_start = qstart + 2  # past "q="
    body = balanced_body(token, body_start + 1)
    if body is None:
        raise ParseError(f"unclosed '(' in {token!r}", position=body_start)
    after = token[body_start + 1 + len(body) + 1 :]
    _check_expr_path(token[:qmark], token)
    return RelExpr(
        path=token[:qmark],
        context=body.strip() or None,
        intent=_parse_expr_intent(after, token),
        params=_decode_query_params(token[qmark + 1 : qstart].rstrip("&")),
    )


def _find_expression_param(token: str, qmark: int) -> int | None:
    """The offset of ``q=(`` as a query parameter after ``qmark``, or None.

    # INVARIANT: ``&`` separates query parameters only at depth 0 outside
    # quotes — the same rule :func:`url4.wire.subrequest.extract_expression_params`
    # applies on the wire. A quote-only scan mistook an ``&`` nested inside a
    # parenthesized expression-bearing value (``processor=(/x?a=1&b=2&q=(y)!z)``)
    # for a parameter boundary and locked onto the INNER ``q=(`` (`OME-501`).
    """
    start = qmark + 1
    if token[start : start + 3] == "q=(":
        return start
    rest = token[start:]
    for i, ch in iter_top_level(rest):
        if ch == "&":
            candidate = start + i + 1
            if token[candidate : candidate + 3] == "q=(":
                return candidate
    return None


def _decode_query_params(params_text: str) -> Params:
    # INVARIANT: same depth-0 rule as _find_expression_param — a nested ``&``
    # belongs to its enclosing value, not to this parameter list.
    if not params_text:
        return ()
    pairs: list[tuple[str, str | None]] = []
    for segment in split_query_segments(params_text):
        if segment:
            key, eq, value = segment.partition("=")
            decoded = value if eq else None
            validate_param(key, decoded)
            pairs.append((key, decoded))
    return tuple(pairs)


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


def _check_authority(authority: str, token: str) -> None:
    """Validate `authority = host [ ":" port ]` — the PORT only (see `_PORT_RE`)."""
    host, sep, port = authority.partition(":")
    if sep and not _PORT_RE.fullmatch(port):
        raise ParseError(
            f"invalid port {port!r} in {token!r} — `port = 1*DIGIT`",
        )
    if not host:
        raise ParseError(f"remote expression has no host: {token!r}")


def _parse_remote(token: str) -> Node:
    rest = token[len("url4://") :]
    slash = rest.find("/")
    paren = find_unquoted(rest, "(")
    if paren is not None and (slash == -1 or paren < slash):
        raise ParseError(f"remote expression requires a path: {token!r}")
    if slash == -1:
        return Url(token)
    _check_authority(rest[:slash], token)
    inner = _parse_relative(rest[slash:])
    if isinstance(inner, RelUrl):
        return Url(token)  # §5.2 rule 3.3 — bare remote reference
    return RemoteExpr(
        authority=rest[:slash],
        path=inner.path,
        context=inner.context,
        intent=inner.intent,
        params=inner.params,
    )


# --- leaf values (§5.2 rules 4–10) -------------------------------------------------


def _unquote(token: str) -> str:
    """Decode a fully-quoted ``'…'`` token to its content (``\\'``/``\\\\``)."""
    end = skip_quoted(token, 0)
    if end == 1:
        raise ParseError(f"unterminated quote in {token!r}", position=0)
    if end != len(token):
        raise ParseError(f"unexpected text after quoted value in {token!r}", position=end)
    return _unescape(token[1:-1])


def _unescape(content: str) -> str:
    """Decode a quoted body: the ``\\'`` and ``\\\\`` escapes, no raw control chars.

    # INVARIANT: exactly two escapes are defined. A backslash before anything
    # else is rejected, as is a raw control character (< %x20, or DEL) — httpx
    # rejects those in a URL anyway.
    """
    out: list[str] = []
    i = 0
    while i < len(content):
        char = content[i]
        if char == "\\":
            nxt = content[i + 1] if i + 1 < len(content) else ""
            if nxt not in ("\\", "'"):
                raise ParseError(
                    f"undefined escape {'\\' + nxt!r} in quoted text — the grammar "
                    r"defines only \' and \\"
                )
            out.append(nxt)
            i += 2
            continue
        if char < " " or char == "\x7f":
            raise ParseError(f"raw control character {char!r} in quoted text (spec quoted-char)")
        out.append(char)
        i += 1
    return "".join(out)


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
    ``/path`` → :class:`~url4.core.nodes.RelUrl` (the fan-out reducer route form,
    ``!/reduce()``); any ``scheme://…`` → :class:`~url4.core.nodes.Url`. Otherwise
    ``intent = value`` applies and the token runs through full value detection,
    so a nested expression, an iteration, a struct object or a self/identity ref
    keeps its structure. Anything else is natural-language
    :class:`~url4.core.nodes.Text`.

    # WHY value detection matters here: the DAG compiler dispatches lowering by
    # node type, so an intent flattened to `Text` is never compiled into a
    # subgraph — `(a,b)!(c,d)!agg` would hand the literal string `"(c,d)!agg"` to
    # the model as a prompt instead of evaluating it.
    """
    text = intent.strip()
    if text.startswith("'"):
        node: Node = Text(_unquote(text))
    elif _SCHEME_RE.match(text) is not None:
        node = Url(text)
    elif text.startswith("/"):
        node = RelUrl(text)
    else:
        node = _intent_value_or_text(text)
    return node


def _intent_value_or_text(text: str) -> Node:
    """Full value detection for an intent token, else natural-language ``Text``.

    # WHY: an intent is natural language FIRST. A token that merely looks like a
    # value head (``{not a struct``) must stay prompt text rather than become a
    # parse error — widening intent classification may not narrow what an author
    # is allowed to say.
    """
    if text[:1] not in _INTENT_VALUE_HEADS and _find_iteration_star(text) is None:
        return Text(text)
    try:
        return _parse_value(text)
    except ParseError:
        return Text(text)


__all__ = ["intent_atom", "parse", "parse_value"]
