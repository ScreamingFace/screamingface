"""Compile url4 surface text (or a parse tree) into an executable node graph.

Hybrid laziness: only the *top-level* structure is decoded eagerly — the
intent/params/iteration envelope (reusing the depth/quote-aware scanners from
:mod:`url4.core.parser`, in :func:`~url4.core.parser.build`'s exact order, which is what
preserves its pinned quirks) plus a per-segment classification. Non-group
segments are parsed with the recursive-descent grammar and lowered to typed
nodes; a group-shaped segment defers its inner text into a
:class:`~url4.dag.nodes.LazyExprNode` thunk, compiled only when executed.

Reference edges (``$name`` / ``$N``) are derived per segment and mirror the
reference engine's two-phase list resolution:

- a *named slot* (a binding OR a named source) sees only named slots declared
  **earlier** (left-to-right);
- an *unnamed* source sees **every** sibling named slot, later ones included;
- ``$N`` resolves from a source only when slot ``N`` is named;
- the intent depends on **all** slots (values by position and name), so it
  resolves after the full source gather;
- unknown references get no edge and stay verbatim.

Named slots therefore never depend on unnamed sources and named→named edges
are strictly left-to-right, so compiled graphs are cycle-free by construction.

Descriptor lowering (spec §4.3): a :class:`~url4.core.nodes.Source` wrapper lowers
its value, pushes the attribution label into the fan-out metadata, then wraps
outward — :class:`~url4.dag.nodes.ExpandNode` for ``;expand``/``*source``,
:class:`~url4.dag.nodes.GuardNode` for ``;optional``/``;t=``/``;retry=``. A
guarded subtree is lowered WITHOUT reference edges: the edges sit on the guard
itself and flow into the isolated sub-execution as a scope frame (the same
containment pattern as :class:`~url4.dag.nodes.LazyExprNode`), which keeps a
shared binding resolving exactly once in the outer graph.

Extensibility: :class:`LoweringRegistry` maps parse-tree node types to lowering
functions (Registry / Abstract Factory) — replace how any surface form lowers
without touching this module.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace

from url4.core.ensemble import find_references
from url4.core.errors import ErrorCode, ParseError
from url4.core.grammar import parse as grammar_parse
from url4.core.nodes import (
    Binding,
    Expression,
    IdentityRef,
    Iteration,
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
from url4.core.nodes import walk as ast_walk
from url4.core.parser import (
    IterationEnvelope,
    balanced_body,
    decode_envelope,
    intent_atom,
    split_intent,
    split_top_level_commas,
    strip_one_paren_layer,
)

from url4.dag.node import DagNode, node_children  # isort: skip
from url4.dag.nodes import (  # isort: skip
    BarrierNode,
    BindingNode,
    BroadcastCollectNode,
    CollectNode,
    ExpandNode,
    FanoutReduceNode,
    GatherNode,
    GuardNode,
    HoldingsNode,
    InlineCollectionNode,
    LazyExprNode,
    MapNode,
    MergeNode,
    ProcessNode,
    ReduceNode,
    RelUrlNode,
    RemoteFetchNode,
    SlotSpec,
    StructNode,
    TextNode,
    WebFetchNode,
)

Edges = Mapping[str, DagNode]
Lowerer = Callable[[Node, Edges, "LoweringRegistry"], DagNode]

# ``name=(…`` / ``name:(…`` — a binding whose RHS is a group, which stays lazy
# on the text path (the grammar would eagerly parse the nested group).
_GROUP_BINDING_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)([=:])\(")


class LoweringRegistry:
    """Maps parse-tree node types to lowering functions (Open/Closed extension)."""

    def __init__(self, lowerers: Mapping[type, Lowerer] | None = None) -> None:
        self._lowerers: dict[type, Lowerer] = dict(lowerers or {})

    def register(self, ast_type: type, lowerer: Lowerer) -> None:
        """Register (or override) how ``ast_type`` lowers to an executable node."""
        self._lowerers[ast_type] = lowerer

    def copy(self) -> LoweringRegistry:
        return LoweringRegistry(self._lowerers)

    def lower(self, node: Node, edges: Edges) -> DagNode:
        lowerer = self._lowerers.get(type(node))
        if lowerer is None:
            raise TypeError(f"no lowering registered for {type(node).__name__}")
        return lowerer(node, edges, self)


# --- default lowerers (parse-tree atom → executable node) --------------------


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


_ROW_NAMES = frozenset({"item", "current"})
"""The reserved per-row names (§5.3.4) — never wired from an enclosing binding.

Mirrors the exclusion `_refs_of_ast` already applies when collecting AST references, so the
text path and the AST path agree on which names an iteration rebinds for itself.
"""


def _lower_iteration(node: Node, edges: Edges, registry: LoweringRegistry) -> DagNode:
    assert isinstance(node, Iteration)
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
        return ReduceNode(node.reducer, deps={"rows": map_node})
    return CollectNode(deps={"rows": map_node})


def _body_intent_refs(body: str, intent: str | None) -> set[str]:
    """The `$name`s an iteration's body and per-row intent mention, minus the reserved row names.

    INVARIANT: the ONE reading of an iteration's template strings. Both compilation paths need
    it — `_body_ref_edges` at lowering time and `_refs_of_ast` when collecting a slot's
    references — and if they ever disagree about which names an iteration rebinds for itself,
    the AST path silently stops wiring an outer binding while the text path keeps working. That
    divergence is invisible: the reference substitutes VERBATIM and the run still succeeds.
    """
    return (find_references(body) | (find_references(intent) if intent else set())) - _ROW_NAMES


def _body_ref_edges(body: str, intent: str | None, edges: Edges) -> dict[str, DagNode]:
    """Reference edges for the `$name`s an iteration's body and per-row intent mention.

    INVARIANT: ``item`` and ``current`` are excluded. They are the RESERVED row names (§5.3.4),
    rebound per row by :class:`~url4.dag.nodes.MapNode`; wiring one to an enclosing binding of
    the same name would let an outer value capture the row and silently iterate the wrong data.

    An edge is added only for a name the enclosing group actually declares, so a body that
    references nothing gains no dependency and keeps its previous concurrency.
    """
    wired: dict[str, DagNode] = {}
    for ref in sorted(_body_intent_refs(body, intent)):
        key = f"pos:{ref}" if ref.isdigit() else f"bind:{ref}"
        if key in edges:
            wired[key] = edges[key]
    return wired


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


def _inline_collection(slots: list[_Slot]) -> DagNode:
    built = _build_slots(slots)
    return InlineCollectionNode(
        _slot_specs(slots), deps={f"src:{i}": node for i, node in enumerate(built)}
    )


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


# --- group wiring (shared by the text and parse-tree paths) ------------------


@dataclass
class _Slot:
    """One source segment awaiting edge wiring: ``make(edges)`` builds its node.

    ``name`` is set for name-only descriptors AND annotated named sources —
    under the ABNF contribution semantics (`OME-534`) BOTH contribute to the
    packed context. ``instrumental`` marks a scalar-``weight 0.0`` source:
    resolved and referenceable, excluded from the packed sources.
    """

    name: str | None
    refs: frozenset[str]
    make: Callable[[Edges], DagNode]
    instrumental: bool = False


@dataclass
class _Intent:
    """The classified intent: ``make(edges)`` builds it; only text substitutes.

    ``text`` carries the raw template for the broadcast path, which substitutes
    per source (with ``$current`` bound) instead of once, shared. It is set iff
    the intent is text — ``text is not None`` *is* the "is this text?" test.
    """

    make: Callable[[Edges], DagNode]
    text: str | None = None


def _quorum_of(params: Params) -> int | None:
    """The expression's ``quorum=N`` param; ``all`` (the default) is None."""
    for key, value in params:
        if key != "quorum":
            continue
        if value is None or value == "all":
            return None
        try:
            return int(value)
        except ValueError:
            raise ParseError(f"invalid quorum={value!r}; expected an integer or 'all'") from None
    return None


def _ref_edges(
    refs: frozenset[str], by_name: dict[str, DagNode], by_pos: dict[int, DagNode]
) -> dict[str, DagNode]:
    edges: dict[str, DagNode] = {}
    for ref in sorted(refs):
        if ref.isdigit() and int(ref) in by_pos:
            edges[f"pos:{ref}"] = by_pos[int(ref)]
        elif ref in by_name:
            edges[f"bind:{ref}"] = by_name[ref]
    return edges


def _build_slots(slots: list[_Slot]) -> list[DagNode]:
    """Two-phase build honoring reference visibility: named slots first, in order."""
    built: list[DagNode | None] = [None] * len(slots)
    by_name: dict[str, DagNode] = {}
    by_pos: dict[int, DagNode] = {}
    for i, slot in enumerate(slots):  # INVARIANT: named slots see only EARLIER named slots
        if slot.name is None:
            continue
        node = slot.make(_ref_edges(slot.refs, by_name, by_pos))
        built[i], by_name[slot.name], by_pos[i + 1] = node, node, node
    for i, slot in enumerate(slots):  # INVARIANT: unnamed sources see ALL named slots
        if slot.name is None:
            built[i] = slot.make(_ref_edges(slot.refs, by_name, by_pos))
    return [node for node in built if node is not None]


def _slot_specs(slots: list[_Slot]) -> tuple[SlotSpec, ...]:
    return tuple((slot.name, slot.instrumental) for slot in slots)


def _compile_group(
    slots: list[_Slot],
    intent: _Intent | None,
    broadcast: bool,
    *,
    from_list: bool,
    quorum: int | None = None,
) -> DagNode:
    if broadcast:
        return _broadcast_graph(slots, intent)
    built = _build_slots(slots)
    if intent is None:
        return GatherNode(
            _slot_specs(slots), quorum, deps={f"src:{i}": node for i, node in enumerate(built)}
        )
    return _reduce_graph(built, slots, intent, from_list=from_list, quorum=quorum)


def _fanout_call(node: DagNode) -> tuple[RelUrlNode, str | None] | None:
    """The relative-*expression* fetch behind ``node`` (+ its label), or None.

    The fan-out unit (``/path(...)!...``) may be wrapped by a GuardNode
    (``;optional``/``;t=``/``;retry=``) or — ABNF contribution semantics
    (`OME-534`) — a name-only BindingNode (``named:/p(...)!x``), whose name
    becomes the call's fan-out label instead of demoting the group to a local
    merge. Expansion changes the source count, so an ExpandNode never fans out.
    """
    label: str | None = None
    if isinstance(node, BindingNode):
        label = node.name
        node = node.deps["value"]
    if isinstance(node, GuardNode):
        node = node.inner
    if isinstance(node, RelUrlNode) and node.is_expr:
        return node, label
    return None


def _reduce_graph(
    built: list[DagNode],
    slots: list[_Slot],
    intent: _Intent,
    *,
    from_list: bool,
    quorum: int | None,
) -> DagNode:
    # WHY: fan-out + reduce is a LIST operation — it needs a parenthesised group of
    # relative-expression sources, mirroring the reference engine's fan-out gate
    # (``_is_fanout and raw_intent``: the source must be a list AND carry a
    # top-level intent). A *bare* single relative expression with a top-level
    # intent is not a list: its intent folds into that one call — matching the
    # eager AST path's :func:`_lower_rel_expr` — instead of spawning a spurious
    # reducer call to "combine" a single response.
    # INVARIANT (`OME-534`): fan-out additionally needs at least one
    # CONTRIBUTING call — instrumental (weight 0.0) members are not panel
    # members, so an all-instrumental call group has nothing to reduce and
    # takes the base path (its intent, with `$name` refs resolved, IS the
    # result — the `(r:0:/call(…)!x)!'$r'` extraction idiom).
    if (
        from_list
        and built
        and all(_fanout_call(node) is not None for node in built)
        and any(not slot.instrumental for slot in slots)
    ):
        return _fanout_graph(built, intent)
    if not from_list and len(built) == 1 and isinstance(built[0], RelUrlNode) and built[0].is_expr:
        return _fold_intent_into_call(built[0], intent)
    return _base_graph(built, slots, intent, quorum)


def _fold_intent_into_call(node: RelUrlNode, intent: _Intent) -> DagNode:
    """Attach a top-level intent to a single relative-expression call.

    ``/p(ctx)`` + an outer ``!intent`` become one ``/p?q=(ctx)!intent`` fetch,
    the exact node :func:`_lower_rel_expr` builds for the eager-AST twin — so the
    lazy text path and the AST path stay in lock-step for this shape.
    """
    deps: dict[str, DagNode] = {"intent": intent.make({})}
    deps.update(node.deps)  # carries the ctx:i context-slot deps too (`OME-535`)
    return RelUrlNode(
        node.path,
        context=node.context,
        is_expr=True,
        name=node.name,
        weight=node.weight,
        params=node.params,
        accept=node.accept,
        ctx_slots=node.ctx_slots,
        deps=deps,
    )


def _broadcast_graph(slots: list[_Slot], intent: _Intent | None) -> DagNode:
    """``!*`` — apply the intent once per source (spec §6.1).

    Sources resolve under the *outer* scope (no sibling reference edges,
    bindings not excluded from the parts). A text intent travels as a raw
    template so each :class:`MergeNode` substitutes it with that source's
    ``$current`` bound; a fetch intent is one shared node, resolved exactly
    once. The parts assemble into the §6.1.4 JSON collection.
    """
    template: str | None = None
    intent_node: DagNode | None = None
    if intent is None:
        template = ""
    elif intent.text is not None:
        template = intent.text
    else:
        intent_node = intent.make({})
    parts: dict[str, DagNode] = {}
    for i, slot in enumerate(slots):
        deps: dict[str, DagNode] = {"source": slot.make({})}
        if intent_node is not None:
            deps["intent"] = intent_node
        parts[f"part:{i}"] = MergeNode(intent_template=template, deps=deps)
    return BroadcastCollectNode(tuple(slot.name for slot in slots), deps=parts)


def _fanout_graph(built: list[DagNode], intent: _Intent) -> DagNode:
    """All-relative-expression group: parallel fetches + a reducer fetch.

    The instruction resolves under the outer scope (no slot edges), matching the
    reference engine's fan-out path. ``meta`` labels come from the (possibly
    guard-wrapped) call nodes' descriptors.
    """
    deps: dict[str, DagNode] = {"intent": intent.make({})}
    deps.update({f"call:{i}": node for i, node in enumerate(built)})
    meta = []
    for node in built:
        unwrapped = _fanout_call(node)
        assert unwrapped is not None  # gated by _reduce_graph
        call, label = unwrapped
        meta.append((label or call.name, call.weight))
    return FanoutReduceNode(tuple(meta), deps=deps)


def _base_graph(
    built: list[DagNode], slots: list[_Slot], intent: _Intent, quorum: int | None
) -> DagNode:
    """The single/base strategy: the intent resolves after the full gather.

    A text intent travels as ProcessNode's ``intent_template`` and substitutes
    against the populated post-gather scope — the only point where expansion's
    renumbered ``$N`` positions exist (spec §5.3.12.4). A fetch intent has no
    substitution to defer; a BarrierNode makes it structurally depend on every
    source, preserving the reference engine's sources-then-intent ordering.
    """
    deps: dict[str, DagNode] = {f"src:{i}": node for i, node in enumerate(built)}
    if intent.text is not None:
        return ProcessNode(_slot_specs(slots), quorum, intent_template=intent.text, deps=deps)
    waits = {f"wait:{i}": node for i, node in enumerate(built)}
    deps["intent"] = BarrierNode(deps={"inner": intent.make({}), **waits})
    return ProcessNode(_slot_specs(slots), quorum, deps=deps)


# --- the text (string) path ---------------------------------------------------


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


def _slot_identity(ast: Node) -> tuple[str | None, bool]:
    """The slot's ``(name, instrumental)`` — ABNF contribution semantics.

    WHY Binding is never instrumental (`OME-534`): the name-only forms
    (``a: v`` / ``a=v``) are contributing sources under the ABNF; the ONLY
    instrumental marker is an explicit scalar ``weight 0.0`` on a Source.
    """
    if isinstance(ast, Binding):
        return ast.name, False
    if isinstance(ast, Source):
        return ast.name, _is_instrumental_weight(ast.weight)
    return None, False


def _is_instrumental_weight(weight: object) -> bool:
    """True for the explicit scalar ``0.0`` (structured weights never qualify)."""
    return (
        isinstance(weight, (int, float)) and not isinstance(weight, bool) and float(weight) == 0.0
    )


def _make_binding_thunk(name: str, kind: str, rhs: str) -> Callable[[Edges], DagNode]:
    def make(edges: Edges) -> DagNode:
        return BindingNode(name, kind, deps={"value": LazyExprNode(rhs, deps=dict(edges))})

    return make


def _intent_from_raw(raw_intent: str | None, registry: LoweringRegistry) -> _Intent | None:
    if raw_intent is None:
        return None
    return _intent_from_ast(intent_atom(raw_intent), registry)


def _intent_from_ast(atom: Node | None, registry: LoweringRegistry) -> _Intent | None:
    if atom is None:
        return None
    if isinstance(atom, Text):
        value = atom.value
        return _Intent(lambda edges: TextNode(value, deps=dict(edges)), text=value)
    return _Intent(lambda edges: registry.lower(atom, edges))


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
            return ReduceNode(env.reducer, deps={"rows": map_node})
        return CollectNode(deps={"rows": map_node})
    return _compile_group_text(env.source_expr, env.intent, env.broadcast, registry, env.params)


# --- the parse-tree path + public API -----------------------------------------


def _slot_from_ast(source: Node, registry: LoweringRegistry) -> _Slot:
    name, instrumental = _slot_identity(source)
    return _Slot(
        name,
        frozenset(_refs_of_ast(source)),
        lambda edges: registry.lower(source, edges),
        instrumental=instrumental,
    )


def _refs_of_ast(node: Node) -> set[str]:
    refs: set[str] = set()
    for descendant in ast_walk(node):
        if isinstance(descendant, Text):
            refs |= find_references(descendant.value)
        elif isinstance(descendant, RelUrl):
            # A bare relative URI /data/$topic embeds refs in its path, the AST
            # twin of the text path's per-segment find_references (§8.2.3).
            refs |= find_references(descendant.value)
        elif isinstance(descendant, (RelExpr, RemoteExpr)) and descendant.context:
            refs |= find_references(descendant.context)
        elif isinstance(descendant, Iteration):
            # WHY read as TEXT: an iteration's body and per-row intent are template strings,
            # not child nodes — `children(Iteration)` yields only the collection — so the walk
            # cannot reach their `$name`s. Without this the enclosing group's slot declared no
            # dependency on them, `_ref_edges` emitted no `bind:` edge, and `_lower_iteration`
            # had nothing left to wire: the AST path substituted an outer reference VERBATIM,
            # which is the silent failure the text path already fixed (§6.2).
            #
            # INVARIANT: the SAME reading `_body_ref_edges` uses, shared rather than restated —
            # a slot that declares fewer references than the lowering step wires is a wiring
            # step with nothing to wire. The collection is deliberately not part of it: it
            # resolves in the ENCLOSING scope and reaches this walk as an ordinary child.
            refs |= _body_intent_refs(descendant.body, descendant.intent)
        elif isinstance(descendant, StructObject):
            refs |= find_references(descendant.raw)
        elif isinstance(descendant, VarRef) and descendant.name not in _ROW_NAMES:
            refs.add(descendant.name)
    return refs


@dataclass(eq=False)
class Graph:
    """A compiled expression: the sink node plus traversal/validation helpers."""

    sink: DagNode
    registry: LoweringRegistry | None = None

    def walk(self) -> Iterator[DagNode]:
        """Yield every reachable node once, preorder from the sink."""
        seen: set[int] = set()
        stack: list[DagNode] = [self.sink]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            yield node
            # node_children, not deps: a node may hold an executable subtree
            # off-edge (GuardNode's isolation boundary) and validate() must
            # reach into it.
            stack.extend(reversed(node_children(node)))

    def validate(self) -> None:
        """Force full expansion of every lazy fragment, for fail-fast linting.

        Raises :class:`~url4.core.errors.ParseError` on the first malformed deferred
        fragment (lazy sub-expressions and reducers; MapNode row bodies cannot
        be validated without ``$item`` data).
        """
        for node in self.walk():
            if isinstance(node, LazyExprNode):
                # Thread this graph's registry so a fragment using a custom
                # surface form validates with the same lowerings it will execute
                # with — otherwise validate() rejects an expression that runs.
                compile_expression(node.text, registry=self.registry).validate()
            elif isinstance(node, ReduceNode):
                grammar_parse(split_intent(node.reducer)[0])


def compile_expression(
    target: str | Node,
    *,
    registry: LoweringRegistry | None = None,
    bare_root_ok: bool = False,
) -> Graph:
    """Compile url4 surface text or a parse-tree node into an executable graph.

    ``bare_root_ok`` is the ENGINE-INTERNAL escape from the grammar's mandatory
    intent (`OME-508`): the executor's spawn boundary compiles its own wrappers
    (a map row's ``(body)``, a lazily-deferred collection) whose intent, if
    any, is held outside the text. User-facing entries leave it False.
    """
    registry = registry if registry is not None else default_registry()
    if isinstance(target, str):
        return Graph(_compile_text(target, registry, bare_root_ok=bare_root_ok), registry=registry)
    return Graph(_lower_top_level(target, registry), registry=registry)


def _lower_top_level(target: Node, registry: LoweringRegistry) -> DagNode:
    """Lower a top-level parse-tree node, keeping the text and AST paths in step.

    A *top-level* relative expression's intent is a top-level intent — folded
    into the call, exactly as the text path treats it after ``split_intent``.
    """
    if isinstance(target, RelExpr) and target.intent is not None:
        rel = registry.lower(replace(target, intent=None), {})
        intent = _intent_from_ast(target.intent, registry)
        assert intent is not None  # target.intent is not None
        assert isinstance(rel, RelUrlNode)  # _lower_rel_expr's output
        return _fold_intent_into_call(rel, intent)
    return registry.lower(target, {})


__all__ = [
    "Graph",
    "LoweringRegistry",
    "compile_expression",
    "default_registry",
]
