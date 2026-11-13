"""Refuse a statically known remote-node call before a run schedules anything (OME-1811 review).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run whose expression names another node fails before my node does
any work for it: no outer fetch, no local sibling, and in the engine no paid model call, runs first.

INVARIANT: under a remote-node policy, every :class:`RemoteFetchNode` reachable from the sink
fails ``x.remote_node_unsupported`` HERE, before the executor starts a single dependency.
"Reachable" spans edges and held subtrees (:func:`node_children`) AND the text a deferred node
will spawn (a :class:`MapNode` body, a :class:`LazyExprNode` group): that text is static, so it is
compiled and walked now, ahead of the collection or sibling the run would otherwise do first.
A graph holding a :class:`FanoutReduceNode` also refuses a ``url4://`` processor: a literal one,
or a Form-3 expression whose value needs no run (:mod:`url4.dag._static_processor`).
Without a policy this is a no-op, and compiles nothing.
WHY the execution-time checks stay (``RemoteFetchNode.resolve``,
``processor._check_remote_processor``): a value computed at run time (a fetched processor URI, a
row value) is unknowable here, and a fragment that does not compile is the run's error to report.
"""

from __future__ import annotations

from url4.core.errors import Url4Error
from url4.dag._static_processor import static_processor_value
from url4.dag.compiler import LoweringRegistry, compile_expression
from url4.dag.node import DagNode, ProcessFn, node_children
from url4.dag.nodes import FanoutReduceNode, LazyExprNode, MapNode, RemoteFetchNode
from url4.dag.processor import classify_processor, remote_processor_hop
from url4.dag.remote_nodes import preflight_remote_node, remote_policy_active


async def preflight_remote_nodes(
    sink: DagNode, processor: str | None, registry: LoweringRegistry | None, process: ProcessFn
) -> None:
    """Raise ``x.remote_node_unsupported`` for any remote call this graph is sure to refuse."""
    if not remote_policy_active():
        return
    if _walk(sink, registry) and processor is not None:
        value = processor.strip()
        if classify_processor(value) == "expression":
            value = await static_processor_value(value, registry, process) or ""
        hop = remote_processor_hop(value) if classify_processor(value) == "uri" else None
        if hop is not None:
            preflight_remote_node(*hop)


def _walk(sink: DagNode, registry: LoweringRegistry | None) -> bool:
    """Preflight every remote node reachable from ``sink``; whether any of them reduces."""
    reduces = False
    seen: set[int] = set()
    fragments: set[str] = set()
    stack = [sink]
    while stack:
        node = stack.pop()
        if id(node) in seen:  # INVARIANT: a shared node (a DAG, not a tree) is walked once
            continue
        seen.add(id(node))
        if isinstance(node, RemoteFetchNode):
            preflight_remote_node(node.authority, node.path)
        reduces = reduces or isinstance(node, FanoutReduceNode)
        stack.extend(node_children(node))
        text = _fragment(node)
        if text is not None and text not in fragments:  # INVARIANT: each text compiles once
            fragments.add(text)
            stack.extend(_compiled(text, registry))
    return reduces


def _fragment(node: DagNode) -> str | None:
    if isinstance(node, MapNode):
        return node.fragment
    return node.text if isinstance(node, LazyExprNode) else None


def _compiled(text: str, registry: LoweringRegistry | None) -> list[DagNode]:
    # AIDEV-NOTE: bare_root_ok mirrors the spawn hook, which compiles these same texts.
    try:
        return [compile_expression(text, registry=registry, bare_root_ok=True).sink]
    except Url4Error:
        return []  # WHY: a fragment that fails to compile fails when (and only if) it runs


__all__ = ["preflight_remote_nodes"]
