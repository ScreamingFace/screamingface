"""Lower url4 surface text (or a parse tree) into executable DAG nodes.

The compiler's first reason to change, split out of :mod:`url4.dag.compiler`.
This module is the facade over four private modules, split by reason to change:

- :mod:`url4.dag._lowering_registry` — the :class:`LoweringRegistry` (the extension point);
- :mod:`url4.dag._lowering_nodes` — the default per-node lowerers, the context-slot
  wiring, iteration, collection and descriptor lowering;
- :mod:`url4.dag._lowering_text` — the text path (surface text → lazy nodes);
- :mod:`url4.dag._lowering_intent` — intent, reducer and row-intent classification,
  and a slot's name and ``$name`` references.

This module keeps the public names (``Lowerer``, ``LoweringRegistry``,
``default_registry``, ``Graph``, ``compile_expression``) and the top-level
parse-tree entry (``_lower_top_level``). The group-wiring strategy (slot → graph
shape) lives in :mod:`url4.dag._wiring`; the lowering modules import it, never the
reverse.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace

from url4.core.grammar import parse as grammar_parse
from url4.core.nodes import Node, RelExpr
from url4.core.parser import split_intent

from url4.dag._lowering_intent import _intent_from_ast  # isort: skip
from url4.dag._lowering_nodes import default_registry  # isort: skip
from url4.dag._lowering_registry import Lowerer as Lowerer, LoweringRegistry  # isort: skip
from url4.dag._lowering_text import _compile_text  # isort: skip
from url4.dag._wiring import _fold_intent_into_call  # isort: skip
from url4.dag.node import DagNode, node_children  # isort: skip
from url4.dag.nodes import LazyExprNode, ReduceNode, RelUrlNode  # isort: skip


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
        # WHY: a call's own intent is not a group's code pointer (PRD P16), so it is never
        # classified here. The text path never classifies it either, so the two paths agree.
        intent = _intent_from_ast(target.intent, registry, classify=False)
        assert intent is not None  # target.intent is not None
        assert isinstance(rel, RelUrlNode)  # _lower_rel_expr's output
        return _fold_intent_into_call(rel, intent)
    return registry.lower(target, {})
