"""The structural ``url4://`` calls of a run's text or graph: the run-start precheck's input.

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run that names another node is refused before my node runs
anything for it, even when its text holds a nested group the strict grammar rejects but the
engine's spawn compiles (``(('r1','r2')*(/b($item)!'i'))!'g'``).

INVARIANT (PR #1750 round 5, owner "fallback graph walk"): the strict scan
(:mod:`url4.dag.source_scan`) stays the source of truth wherever it can read the text. Whatever it
cannot read — the run's whole text, a deferred group (``LazyExprNode.text``), an iteration-body
segment (:attr:`SourceScan.opaque`) — is compiled the way the run or the spawn hook compiles it,
and its graph walked here, recursively. Every call found feeds the ONE precheck
(:func:`url4.dag.remote_nodes.precheck_remote_nodes`); nothing here refuses on its own.
WHY policy-gated compiles: outside a node context the precheck refuses nothing, so a bare
``url4.run()`` compiles nothing extra (the strict scans are what they always were).
WHY each occurrence counts: a repeated fragment's calls are memoized, not deduplicated, so a
second call to a client's one hop is still a second call.
"""

from __future__ import annotations

from url4.core.errors import Url4Error

from url4.dag._graph_admission import kept_text_scan  # isort: skip
from url4.dag.compiler import Graph, LoweringRegistry, compile_expression  # isort: skip
from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import LazyExprNode, RemoteFetchNode  # isort: skip
from url4.dag.remote_nodes import remote_policy_active  # isort: skip
from url4.dag.source_scan import SourceScan  # isort: skip

Calls = tuple[tuple[str, str], ...]


class _Walk:
    """One precheck's walk: each fragment text compiled once, its calls counted per occurrence."""

    def __init__(self, registry: LoweringRegistry | None) -> None:
        self.registry = registry
        self.memo: dict[str, Calls] = {}

    def scan(self, scan: SourceScan) -> Calls:
        return (*scan.remote_nodes, *(c for text in scan.opaque for c in self.text(text)))

    def graph(self, graph: Graph) -> Calls:
        calls: list[tuple[str, str]] = []
        for node in graph.walk():
            if isinstance(node, RemoteFetchNode):
                calls.append((node.authority, node.path))
            scan = kept_text_scan(node)
            if scan is not None:
                calls.extend(self.scan(scan))
            elif isinstance(node, LazyExprNode):
                calls.extend(self.text(node.text))  # the strict parse failed: walk what spawns
        return tuple(calls)

    def text(self, text: str, *, bare_root_ok: bool = True) -> Calls:
        """The calls of ``text`` compiled as the spawn hook (or, top level, ``run()``) does."""
        if not remote_policy_active():
            return ()
        if text not in self.memo:
            self.memo[text] = ()  # INVARIANT: a text never recurses into itself
            try:
                graph = compile_expression(text, registry=self.registry, bare_root_ok=bare_root_ok)
            except Url4Error:
                return ()  # WHY: a text that does not compile fails when (and only if) it runs
            self.memo[text] = self.graph(graph)
        return self.memo[text]


def scan_remote_calls(scan: SourceScan, registry: LoweringRegistry | None) -> Calls:
    """The calls of a parsed text: its scan's, plus the walk of every segment it could not read."""
    return _Walk(registry).scan(scan)


def graph_remote_calls(target: Graph | DagNode, registry: LoweringRegistry | None) -> Calls:
    """Every call a pre-built ``target`` makes structurally (PR #1587 round 15, F1b).

    INVARIANT: each ``RemoteFetchNode`` reachable through ``node_children`` (``Graph.walk``),
    plus those in text a node keeps for later — and none inside a remote context (that text runs
    at the remote node).
    """
    return _Walk(registry).graph(target if isinstance(target, Graph) else Graph(target))


def text_remote_calls(text: str, registry: LoweringRegistry | None) -> Calls:
    """The calls of run text the strict grammar rejects, compiled exactly as ``run()`` will."""
    return _Walk(registry).text(text, bare_root_ok=False)


__all__ = ["graph_remote_calls", "scan_remote_calls", "text_remote_calls"]
