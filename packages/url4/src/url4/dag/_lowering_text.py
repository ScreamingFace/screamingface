"""The text (string) path of the lowering: surface text → lazy executable nodes.

Split out of :mod:`url4.dag._lowering`. Only the top-level structure is decoded
eagerly — the intent/params/iteration envelope, reusing the depth/quote-aware
scanners from :mod:`url4.core.parser`, in :func:`~url4.core.parser.build`'s exact
order, which is what preserves its pinned quirks — plus a per-segment
classification. A group-shaped segment defers its inner text into a
:class:`~url4.dag.nodes.LazyExprNode` thunk, compiled only when executed.

This module imports :mod:`url4.dag._lowering_intent` and
:mod:`url4.dag._lowering_registry`, and never :mod:`url4.dag._lowering_nodes`, which
imports it. The dependency is one-directional, so no cycle exists.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from url4.core.errors import ErrorCode, ParseError
from url4.core.grammar import parse as grammar_parse
from url4.core.nodes import Params
from url4.core.parser import (
    IterationEnvelope,
    balanced_body,
    decode_envelope,
    split_top_level_commas,
    strip_one_paren_layer,
)
from url4.dag.semantics.ensemble import find_references

from url4.dag._lowering_intent import (  # isort: skip
    _intent_from_raw,
    _reduce_node,
    _refuse_row_intent,
    _slot_identity,
)
from url4.dag._lowering_registry import LoweringRegistry  # isort: skip
from url4.dag._wiring import (  # isort: skip
    Edges,
    _compile_group,
    _inline_collection,
    _quorum_of,
    _Slot,
)
from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import (  # isort: skip
    BindingNode,
    CollectNode,
    LazyExprNode,
    MapNode,
    TextNode,
)

# ``name=(…`` / ``name:(…`` — a binding whose RHS is a group, which stays lazy
# on the text path (the grammar would eagerly parse the nested group).
_GROUP_BINDING_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)([=:])\(")


def _reject_bare_group(segment: str) -> None:
    """WHY: reject an intent-less ``(…)`` in source position EAGERLY (`OME-508`).

    Lazy deferral would postpone the error to spawn time — and the spawn
    boundary compiles permissively (the engine's own wrappers legally arrive
    intent-less), so a user's bare group would silently execute instead of
    failing as the grammar demands. Iteration collections never pass through
    here (``_collection_dag`` owns that legal position).
    """
    if strip_one_paren_layer(segment) is not None:
        raise ParseError(
            f"expression group {segment!r} has no intent — a parenthesized "
            "source group must be followed by !intent (or !*intent)",
            code=ErrorCode.MISSING_INTENT,
        )


def _is_lazy_group(segment: str) -> bool:
    """True for ``(…)`` and ``(…)!tail`` shapes, which defer to a thunk."""
    if strip_one_paren_layer(segment) is not None:
        return True
    if not segment.startswith("("):
        return False
    body = balanced_body(segment, 1)
    return body is not None and segment[len(body) + 2 :].startswith("!")


def _slot_from_text(segment: str, registry: LoweringRegistry) -> _Slot:
    refs = frozenset(find_references(segment))
    group_binding = _GROUP_BINDING_RE.match(segment)
    if group_binding is not None:
        rhs = segment[len(group_binding.group(1)) + 1 :]
        # Only a group-shaped RHS defers; ``name:(k:v):data`` is a structured
        # weight (§4.1.1.4) and must reach the grammar's classifier instead.
        if _is_lazy_group(rhs):
            _reject_bare_group(rhs)
            name, kind = group_binding.group(1), group_binding.group(2)
            # ABNF (`OME-534`): a deferred name=(group) binding CONTRIBUTES like
            # any named source — only weight 0.0 marks a source instrumental,
            # and the binding forms carry no weight.
            return _Slot(name, refs, _make_binding_thunk(name, kind, rhs))
    if _is_lazy_group(segment):
        _reject_bare_group(segment)
        return _Slot(None, refs, lambda edges: LazyExprNode(segment, deps=dict(edges)))
    ast = grammar_parse(segment)
    name, instrumental = _slot_identity(ast)
    return _Slot(name, refs, lambda edges: registry.lower(ast, edges), instrumental=instrumental)


def _make_binding_thunk(name: str, kind: str, rhs: str) -> Callable[[Edges], DagNode]:
    def make(edges: Edges) -> DagNode:
        return BindingNode(name, kind, deps={"value": LazyExprNode(rhs, deps=dict(edges))})

    return make


def _collection_dag(collection: str, registry: LoweringRegistry) -> DagNode:
    if not collection:
        return TextNode("")
    inner = strip_one_paren_layer(collection)
    if inner is not None:
        # WHY: a bare parenthesized group ``(e1, …)`` is an inline collection (§5.3.11):
        # its authored elements form a real ordered list rather than a joined
        # blob re-sniffed as a §5.3.7 body. This is the twin of _lower_collection
        # on the AST path (a bare group parses to an intent-less Expression).
        # A *processed* group ``(a, b)!x`` is NOT one paren layer (the ``!x``
        # tail leaves strip_one_paren_layer None), so it stays a lazy thunk.
        slots = [_slot_from_text(segment, registry) for segment in split_top_level_commas(inner)]
        return _inline_collection(slots)
    # A group-with-intent (``(a, b)!x``) defers to a thunk; any other source
    # (a fetched URI / relative-expression / holdings ref) resolves eagerly and
    # its body is parsed by content type at iteration time (§5.3.7).
    return (
        LazyExprNode(collection)
        if _is_lazy_group(collection)
        else registry.lower(grammar_parse(collection), {})
    )


def _map_from_text(
    collection: str, body: str, intent: str | None, directives, registry: LoweringRegistry
) -> MapNode:
    _refuse_row_intent(intent)
    return MapNode(
        body=body,
        intent=intent,
        directives=directives,
        deps={"collection": _collection_dag(collection, registry)},
    )


def _compile_group_text(
    source_expr: str,
    raw_intent: str | None,
    broadcast: bool,
    registry: LoweringRegistry,
    params: Params = (),
) -> DagNode:
    inner = strip_one_paren_layer(source_expr)
    from_list = inner is not None  # a parenthesised (a, b, …) group vs a bare source
    if from_list:
        segments = split_top_level_commas(inner)
    else:
        segments = [source_expr] if source_expr.strip() else []
    slots = [_slot_from_text(segment, registry) for segment in segments]
    return _compile_group(
        slots,
        _intent_from_raw(raw_intent, registry),
        broadcast,
        from_list=from_list,
        quorum=_quorum_of(params),
    )


def _compile_text(text: str, registry: LoweringRegistry, *, bare_root_ok: bool = False) -> DagNode:
    """Lower the decoded surface envelope — the lazy twin of :func:`url4.core.parser.build`.

    Both consume the same :func:`~url4.core.parser.decode_envelope`, so the two paths
    cannot diverge; they differ only in what each terminal produces (a lazy DAG
    here, an eager AST in ``build``).

    AIDEV-NOTE: F2 / complexity-audit — "cannot diverge" is a claim about *results*
    (what a run resolves to), not about *graph shape*. A nested group such as
    ``(a, (b, c)!x)!go`` becomes a :class:`~url4.dag.nodes.LazyExprNode` thunk
    here (compiled only when the executor reaches it) but is fully expanded
    up front on the parse-tree path (:func:`_lower_expression` /
    :func:`_lower_top_level`, which see an already-built AST with nothing left
    to defer). ``test_bare_relexpr_text_path_matches_ast_path`` pins result
    parity for the shapes it covers; it is not evidence the two paths build the
    same graph. Extending that test to a nested-group shape should assert on
    the resolved string, not on ``compile_expression(...).sink`` structure.
    """
    env = decode_envelope(text, require_intent=not bare_root_ok)
    if isinstance(env, IterationEnvelope):
        map_node = _map_from_text(env.collection, env.body, env.intent, env.directives, registry)
        if env.reducer is not None:
            return _reduce_node(env.reducer, map_node)
        return CollectNode(deps={"rows": map_node})
    return _compile_group_text(env.source_expr, env.intent, env.broadcast, registry, env.params)
