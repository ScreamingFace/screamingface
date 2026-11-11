"""Refuse a statically known remote-node call before a run schedules anything (OME-1811 review).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run whose expression names another node fails before my node does
any work for it: no local sibling, and in the engine no paid model call, runs first.

INVARIANT: under a remote-node policy, every :class:`RemoteFetchNode` reachable from the sink
(edges and held subtrees, :func:`node_children`) and a literal ``url4://`` processor of a graph
holding a :class:`FanoutReduceNode` fail ``x.remote_node_unsupported`` HERE, before the executor
starts a single dependency. Without a policy this is a no-op.
WHY the execution-time checks stay (``RemoteFetchNode.resolve``,
``processor._check_remote_processor``): a fragment built at run time (a map row, a Form-3
processor expression) is not in the graph yet. ``spawn`` runs this preflight on every fragment
it compiles, so a fragment's own siblings are covered too; only order relative to work already
running outside the fragment is not.
"""

from __future__ import annotations

from url4.dag.node import DagNode, node_children
from url4.dag.nodes import FanoutReduceNode, RemoteFetchNode
from url4.dag.processor import classify_processor, remote_processor_hop
from url4.dag.remote_nodes import preflight_remote_node


def preflight_remote_nodes(sink: DagNode, processor: str | None) -> None:
    """Raise ``x.remote_node_unsupported`` for any remote call this graph is sure to refuse."""
    reduces = False
    seen: set[int] = set()
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
    if reduces and processor is not None and classify_processor(processor) == "uri":
        hop = remote_processor_hop(processor.strip())
        if hop is not None:
            preflight_remote_node(*hop)


__all__ = ["preflight_remote_nodes"]
