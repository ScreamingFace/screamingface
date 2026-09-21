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
    compile_expression,
    default_registry,
)

__all__ = [
    "Graph",
    "LoweringRegistry",
    "compile_expression",
    "default_registry",
]
