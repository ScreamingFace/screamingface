"""The default per-node lowerers: parse-tree atom → executable node.

Split out of :mod:`url4.dag._lowering`: one lowering function per built-in parse-tree
node type, the context-slot wiring of a call, the iteration and collection
lowering, the descriptor lowering, and the default registry that binds them.

Descriptor lowering (spec §4.3): a :class:`~url4.core.nodes.Source` wrapper
lowers its value, pushes the attribution label into the fan-out metadata, then
wraps outward — :class:`~url4.dag.nodes.ExpandNode` for ``;expand``/``*source``,
:class:`~url4.dag.nodes.GuardNode` for ``;optional``/``;t=``/``;retry=``. A
guarded subtree is lowered WITHOUT reference edges: the edges sit on the guard
itself and flow into the isolated sub-execution as a scope frame (the same
containment pattern as :class:`~url4.dag.nodes.LazyExprNode`), which keeps a
shared binding resolving exactly once in the outer graph.

The one-directional dependency: this module imports
:mod:`url4.dag._lowering_text`, :mod:`url4.dag._lowering_intent` and
:mod:`url4.dag._lowering_registry`, and none of them imports it back. The
registry is the extension point; see :mod:`url4.dag._lowering_registry`.
"""

from __future__ import annotations

from collections.abc import Callable

from url4.core.errors import ParseError
from url4.core.nodes import (
    Binding,
    Expression,
    IdentityRef,
    Iteration,
    Node,
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
from url4.core.parser import split_top_level_commas

from url4.dag._lowering_intent import (  # isort: skip
    _body_ref_edges,
    _intent_from_ast,
    _refs_of_ast,
    _reduce_node,
    _refuse_row_intent,
    _slot_identity,
)
from url4.dag._lowering_registry import LoweringRegistry  # isort: skip
from url4.dag._lowering_text import _slot_from_text  # isort: skip
from url4.dag._wiring import (  # isort: skip
    Edges,
    _compile_group,
    _inline_collection,
    _quorum_of,
    _ref_edges,
    _Slot,
    _slot_specs,
)
from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import (  # isort: skip
    BindingNode,
    CollectNode,
    ExpandNode,
    GuardNode,
    HoldingsNode,
    MapNode,
    RelUrlNode,
    RemoteFetchNode,
    SlotSpec,
    StructNode,
    TextNode,
    WebFetchNode,
)


def _lower_text(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, Text)
    return TextNode(node.value, deps=dict(edges))


def _lower_url(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, Url)
    return WebFetchNode(node.value)


def _lower_relurl(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, RelUrl)
    # WHY: a bare relative URI may embed dot-path refs (/data/$topic, spec §8.2.3),
    # so its sibling-binding edges must reach the node's scope frame — the same
    # deps every other substituting leaf (_lower_text/_lower_struct) carries.
    return RelUrlNode(node.value, deps=dict(edges))


def _lower_binding(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, Binding)
    return BindingNode(node.name, node.kind, deps={"value": registry.lower(node.value, edges)})


def _lower_rel_expr(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, RelExpr)
    deps: dict[str, DagNode] = {}
    if node.intent is not None:
        # The call's OWN intent is lowered as a plain leaf; quotes were already
        # stripped by the grammar (quotes are delimiters, spec §5.1).
        deps["intent"] = registry.lower(node.intent, edges)
    deps.update(edges)
    ctx_slots = _wire_context_slots(node.context, deps, edges, registry)
    return RelUrlNode(
        node.path,
        context=node.context,
        is_expr=True,
        params=node.params,
        ctx_slots=ctx_slots,
        deps=deps,
    )


def _lower_remote_expr(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, RemoteExpr)
    deps: dict[str, DagNode] = {}
    if node.intent is not None:
        deps["intent"] = registry.lower(node.intent, edges)
    deps.update(edges)
    # No context slots here (`OME-535`): the remote q= is an EXPRESSION the
    # remote node evaluates; only RELATIVE calls resolve context caller-side.
    return RemoteFetchNode(
        node.authority,
        node.path,
        context=node.context,
        params=node.params,
        deps=deps,
    )


def _wire_context_slots(
    context: str | None,
    deps: dict[str, DagNode],
    edges: Edges,
    registry: LoweringRegistry,
) -> tuple[SlotSpec, ...] | None:
    """Lower a call's context source-list into ``ctx:i`` deps (`OME-535`).

    ABNF: the call parens carry a ``source-list`` the CALLER resolves before
    dispatch. A context that fails to parse as one (prose like ``run: 1``,
    unbalanced quotes) returns ``None`` — the raw-text fallback keeps prompt
    text working verbatim. Resolution is strictly caller-side: the packed
    result ships as opaque data, never re-resolved by the receiving node.
    """
    slots = _context_slots(context, registry)
    if slots is None:
        return None
    for i, built in enumerate(_build_ctx_nodes(slots, edges)):
        deps[f"ctx:{i}"] = built
    return _slot_specs(slots)


def _context_slots(context: str | None, registry: LoweringRegistry) -> list[_Slot] | None:
    # INVARIANT (spec §5.6.3.1/.2): a holdings ref ("@") in a call's context is
    # scoped to the RECEIVING route and travels in the q= payload verbatim —
    # never resolved caller-side. The "@" check is deliberately conservative:
    # an email-ish literal merely falls back to the raw-text path, which is
    # the pre-`OME-535` behavior — safe, just unresolved.
    if context is None or not context.strip() or "@" in context:
        return None
    try:
        segments = [seg.strip() for seg in split_top_level_commas(context)]
        return [_slot_from_text(seg, registry) for seg in segments if seg] or None
    except ParseError:
        # WHY fallback, not error: the ABNF's source-list is the canonical
        # reading, but a call's parens have carried free prose since v1 —
        # an unparseable context is prose by construction and ships verbatim.
        return None


def _build_ctx_nodes(slots: list[_Slot], outer: Edges) -> list[DagNode]:
    """Build context-slot nodes with OUTER bindings visible (`OME-535`).

    Mirrors :func:`_build_slots`' two-phase visibility, seeded with the
    enclosing group's edges so ``/ep(data: $a)`` sees a sibling ``a=…``
    binding. Context slots register no positional entries — ``$N`` inside a
    call context keeps referring to the OUTER group's positions.
    """
    by_name = {k.partition(":")[2]: n for k, n in outer.items() if k.startswith("bind:")}
    by_pos = {int(k.partition(":")[2]): n for k, n in outer.items() if k.startswith("pos:")}
    built: list[DagNode | None] = [None] * len(slots)
    for i, slot in enumerate(slots):
        if slot.name is None:
            continue
        node = slot.make(_ref_edges(slot.refs, by_name, by_pos))
        built[i], by_name[slot.name] = node, node
    for i, slot in enumerate(slots):
        if slot.name is None:
            built[i] = slot.make(_ref_edges(slot.refs, by_name, by_pos))
    return [node for node in built if node is not None]


def _lower_self_ref(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, SelfRef)
    return HoldingsNode()


def _lower_identity_ref(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, IdentityRef)
    return HoldingsNode(identity=node.name, collection=node.collection)


def _lower_var_ref(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, VarRef)
    # A standalone reference re-renders to its surface text: the substitution
    # machinery (with its field-path traversal) already resolves it at the leaf.
    return TextNode(_render_ref(node), deps=dict(edges))


def _render_ref(node: VarRef) -> str:
    segments = "".join(f"[{s}]" if isinstance(s, int) else f".{s}" for s in node.path)
    return f"${node.name}{segments}"


def _lower_struct(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, StructObject)
    return StructNode(node.raw, deps=dict(edges))


def _lower_expression(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, Expression)
    slots = [_slot_from_ast(source, registry) for source in node.sources]
    intent = _intent_from_ast(node.intent, registry)
    # An Expression is always a parenthesised group (bare relative expressions
    # parse to RelExpr and lower via _lower_rel_expr), so it is a list source.
    return _compile_group(
        slots, intent, node.broadcast, from_list=True, quorum=_quorum_of(node.params)
    )


def _lower_iteration(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, Iteration)
    _refuse_row_intent(node.intent)
    collection = _lower_collection(node.collection, edges, registry)
    map_node = MapNode(
        body=node.body,
        intent=node.intent,
        directives=node.directives,
        # WHY the body's references become EDGES: the body is re-parsed per row at resolve time,
        # so the compiler cannot see its `$name`s by walking the AST — it must read them out of
        # the text. Without these edges the enclosing group's bindings never reach the spawned
        # row, and a reference the grammar admits (§6.2 — `item-ref` reserves the NAME `$item`
        # inside a body, it does not close the scope) substituted VERBATIM instead. Silently:
        # the leaf received the literal `$ans`.
        deps={"collection": collection, **_body_ref_edges(node.body, node.intent, edges)},
    )
    if node.reducer is not None:
        return _reduce_node(node.reducer, map_node)
    return CollectNode(deps={"rows": map_node})


def _lower_collection(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    """Lower an iteration's collection source (spec §5.3.7 / §5.3.11).

    A bare parenthesized group ``(e1, …)`` — an :class:`~url4.core.nodes.Expression`
    with no top-level intent — is an *inline* collection: its authored elements
    are lowered as a real ordered list (:class:`~url4.dag.nodes.InlineCollectionNode`),
    not gathered-to-text and re-sniffed, so one-element inline collections
    iterate (§5.3.11). Everything else (a fetched URI / relative-expression /
    holdings ref, or a *processed* group ``(a, b)!x`` whose merged result may
    itself be a collection body) resolves to text the :class:`MapNode` parses by
    content type (§5.3.7). Enclosing sibling bindings remain available in collection
    position, so ``$gate*(body)`` resolves the same way as a sibling reference in a body.
    """
    if isinstance(node, Expression) and node.intent is None and not node.broadcast:
        slots = [_slot_from_ast(source, registry) for source in node.sources]
        return _inline_collection(slots)
    return registry.lower(node, edges)


def _lower_source(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    """Lower a two-axis descriptor (spec §4.3): label, expand, then guard.

    A guarded subtree is lowered without edges — the guard carries them and
    hands the resolved values to the isolated sub-execution as a scope frame
    (see the module docstring). Everything else keeps edges on the value.
    """
    assert isinstance(node, Source)
    ann = dict(node.annotations)
    guard = _guard_options(ann, node)
    inner = registry.lower(node.value, {} if guard is not None else edges)
    _push_label(inner, node, ann)
    if node.expand:
        inner = ExpandNode(deps={"inner": inner})
    if guard is not None:
        optional, timeout, retries = guard
        inner = GuardNode(
            inner, optional=optional, timeout=timeout, retries=retries, deps=dict(edges)
        )
    return inner


def _guard_options(
    ann: dict[str, str | None], node: Source
) -> tuple[bool, float | None, int] | None:
    """Decode ``;optional`` / ``;t=`` / ``;retry=`` — None when no guard is needed."""
    optional = "optional" in ann
    timeout = _annotation_number(ann.get("t"), "t", float, node)
    retries = _annotation_number(ann.get("retry"), "retry", int, node) or 0
    if not optional and timeout is None and retries == 0:
        return None
    return optional, timeout, retries


def _annotation_number(raw: str | None, key: str, cast: Callable, node: Source):
    if raw is None:
        return None
    try:
        return cast(raw)
    except ValueError:
        raise ParseError(f"invalid ;{key}={raw!r} on source {node.name or node.value!r}") from None


def _push_label(inner: DagNode, node: Source, ann: dict[str, str | None]) -> None:
    """Attach the descriptor's attribution label / ``;accept=`` to the fetch node."""
    if isinstance(inner, RelUrlNode) and inner.is_expr:
        inner.name = node.name
        inner.weight = _scalar_weight(node.weight)
    if isinstance(inner, (RelUrlNode, WebFetchNode)) and "accept" in ann:
        inner.accept = ann["accept"]


def _scalar_weight(weight: float | dict | None) -> float | None:
    """A structured weight's fan-out label scalar: ``_default`` or none (§4.1.1.8)."""
    if isinstance(weight, dict):
        default = weight.get("_default")
        return float(default) if isinstance(default, (int, float)) else None
    return weight


def default_registry() -> LoweringRegistry:
    """A fresh registry with the built-in lowerings; ``copy()`` to customize."""
    return LoweringRegistry(
        {
            Text: _lower_text,
            Url: _lower_url,
            RelUrl: _lower_relurl,
            Binding: _lower_binding,
            RelExpr: _lower_rel_expr,
            RemoteExpr: _lower_remote_expr,
            SelfRef: _lower_self_ref,
            IdentityRef: _lower_identity_ref,
            VarRef: _lower_var_ref,
            StructObject: _lower_struct,
            Source: _lower_source,
            Expression: _lower_expression,
            Iteration: _lower_iteration,
        }
    )


def _slot_from_ast(source: Node, registry: LoweringRegistry) -> _Slot:
    name, instrumental = _slot_identity(source)
    return _Slot(
        name,
        frozenset(_refs_of_ast(source)),
        lambda edges: registry.lower(source, edges),
        instrumental=instrumental,
    )
