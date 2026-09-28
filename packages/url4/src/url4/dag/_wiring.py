"""Group-wiring strategy for the DAG compiler (source slots → graph shape).

This is the compiler's second reason to change, split out of
:mod:`url4.dag.compiler`: deciding which graph shape a group's sources and
intent become — gather, fan-out + reduce, broadcast, or the single/base
process. It knows nothing about parse-tree node types or surface text; a
:class:`_Slot` carries a ``make(edges)`` callable supplied by the lowering
path, so this module stays pure graph construction.

The lowerers (:mod:`url4.dag._lowering`) import these strategies; the split is
one-directional, so no cycle exists. The public module
:mod:`url4.dag.compiler` re-exports every name here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from url4.core.errors import ParseError
from url4.core.nodes import Params

from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import (  # isort: skip
    BarrierNode,
    BindingNode,
    BroadcastCollectNode,
    FanoutReduceNode,
    GatherNode,
    GuardNode,
    InlineCollectionNode,
    MergeNode,
    ProcessNode,
    RelUrlNode,
    SlotSpec,
)

Edges = Mapping[str, DagNode]


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


def _inline_collection(slots: list[_Slot]) -> DagNode:
    built = _build_slots(slots)
    return InlineCollectionNode(
        _slot_specs(slots), deps={f"src:{i}": node for i, node in enumerate(built)}
    )
