"""Compile url4 surface text (or a parse tree) into an executable node graph.

This is the public facade for the compiler. The implementation is split by
reason to change into two private modules — :mod:`url4.dag._lowering` (the
:class:`LoweringRegistry` and the per-node lowerers, plus the text and
parse-tree decoding) and :mod:`url4.dag._wiring` (the group-wiring strategy:
slot → graph shape). Every name that used to live here is re-exported below, so
imports from this module keep working unchanged.

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

Extensibility: :class:`LoweringRegistry` maps parse-tree node types to lowering
functions (Registry / Abstract Factory) — replace how any surface form lowers
without touching the lowering module.
"""

from __future__ import annotations

from url4.dag._lowering import (  # isort: skip
    Graph,
    Lowerer as Lowerer,
    LoweringRegistry,
    _annotation_number as _annotation_number,
    _body_intent_refs as _body_intent_refs,
    _body_ref_edges as _body_ref_edges,
    _build_ctx_nodes as _build_ctx_nodes,
    _collection_dag as _collection_dag,
    _compile_group_text as _compile_group_text,
    _compile_text as _compile_text,
    _context_slots as _context_slots,
    _GROUP_BINDING_RE as _GROUP_BINDING_RE,
    _guard_options as _guard_options,
    _intent_from_ast as _intent_from_ast,
    _intent_from_raw as _intent_from_raw,
    _is_instrumental_weight as _is_instrumental_weight,
    _is_lazy_group as _is_lazy_group,
    _lower_binding as _lower_binding,
    _lower_collection as _lower_collection,
    _lower_expression as _lower_expression,
    _lower_identity_ref as _lower_identity_ref,
    _lower_iteration as _lower_iteration,
    _lower_rel_expr as _lower_rel_expr,
    _lower_relurl as _lower_relurl,
    _lower_remote_expr as _lower_remote_expr,
    _lower_self_ref as _lower_self_ref,
    _lower_source as _lower_source,
    _lower_struct as _lower_struct,
    _lower_text as _lower_text,
    _lower_top_level as _lower_top_level,
    _lower_url as _lower_url,
    _lower_var_ref as _lower_var_ref,
    _make_binding_thunk as _make_binding_thunk,
    _map_from_text as _map_from_text,
    _push_label as _push_label,
    _refs_of_ast as _refs_of_ast,
    _reject_bare_group as _reject_bare_group,
    _render_ref as _render_ref,
    _ROW_NAMES as _ROW_NAMES,
    _scalar_weight as _scalar_weight,
    _slot_from_ast as _slot_from_ast,
    _slot_from_text as _slot_from_text,
    _slot_identity as _slot_identity,
    _wire_context_slots as _wire_context_slots,
    compile_expression,
    default_registry,
)
from url4.dag._wiring import (  # isort: skip
    Edges as Edges,
    _base_graph as _base_graph,
    _broadcast_graph as _broadcast_graph,
    _build_slots as _build_slots,
    _compile_group as _compile_group,
    _fanout_call as _fanout_call,
    _fanout_graph as _fanout_graph,
    _fold_intent_into_call as _fold_intent_into_call,
    _inline_collection as _inline_collection,
    _Intent as _Intent,
    _quorum_of as _quorum_of,
    _reduce_graph as _reduce_graph,
    _ref_edges as _ref_edges,
    _Slot as _Slot,
    _slot_specs as _slot_specs,
)

__all__ = [
    "Graph",
    "LoweringRegistry",
    "compile_expression",
    "default_registry",
]
