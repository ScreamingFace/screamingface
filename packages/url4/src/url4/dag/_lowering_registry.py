"""The lowering registry: parse-tree node type → lowering function.

Split out of :mod:`url4.dag._lowering`, which re-exports both names here. This is
the leaf of the lowering split: it imports no lowering module, so the per-node
lowerers (:mod:`url4.dag._lowering_nodes`) can call :meth:`LoweringRegistry.lower`
without an import cycle. The dependency is one-directional — the lowerer modules
import this one, never the reverse.

Extensibility: :class:`LoweringRegistry` maps parse-tree node types to lowering
functions (Registry / Abstract Factory) — replace how any surface form lowers
without touching the lowerer modules.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from url4.core.nodes import Node

from url4.dag._wiring import Edges  # isort: skip
from url4.dag.node import DagNode  # isort: skip

Lowerer = Callable[[Node, Edges, "LoweringRegistry"], DagNode]


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
