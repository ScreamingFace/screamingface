"""The structural ``url4://`` calls of a run's text or graph: the run-start precheck's input.

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run that names another node is refused before my node runs
anything for it, even when its text holds a nested group the strict grammar rejects but the
engine's spawn compiles (``(('r1','r2')*(/b($item)!'i'))!'g'``).

INVARIANT (PR #1750 round 5, owner "fallback graph walk"): the strict scan
(:mod:`url4.dag.source_scan`) is used only where it read the WHOLE text. A text it could not
fully read — the run's text, a deferred group (``LazyExprNode.text``), a map body
(``MapNode.fragment``, whole: a segment may compile only inside it) — is compiled exactly as
``run()`` or the spawn hook compiles it, and that graph is walked, recursively. Every call found
feeds the ONE precheck (:func:`url4.dag.remote_nodes.precheck_remote_nodes`).
INVARIANT (FAIL CLOSED, round 5 security review): a fragment that does not compile either is
not call-free when it names ``url4://``: each URI in it becomes a ``maybe`` call (refused unless
it is a client's still-unspent hop), so a run never fetches a collection or runs a sibling ahead
of a remote call the walk could not rule out. The run's own text is exempt: if it does not
compile, ``run()`` fails before any node executes.
WHY policy-gated compiles: outside a node context the precheck refuses nothing, so a bare
``url4.run()`` compiles nothing extra.
WHY each occurrence counts: a repeated fragment's calls are memoized, not deduplicated, so a
second call to a client's one hop is still a second call.
"""

from __future__ import annotations

import re

from url4.core.errors import Url4Error
from url4.core.nodes import Node as AstNode

from url4.dag._graph_admission import kept_text_scan  # isort: skip
from url4.dag.compiler import Graph, LoweringRegistry, compile_expression  # isort: skip
from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import LazyExprNode, MapNode, RemoteFetchNode  # isort: skip
from url4.dag.processor import remote_processor_hop  # isort: skip
from url4.dag.remote_nodes import remote_policy_active  # isort: skip
from url4.dag.source_scan import SourceScan  # isort: skip

Calls = tuple[tuple[str, str], ...]
_URL4_URI = re.compile(r"url4://[^\s'\"(),!;*]+", re.IGNORECASE)


class RemoteWalk:
    """One precheck's walk. ``maybe`` collects the possible calls of uncompilable fragments."""

    def __init__(self, registry: LoweringRegistry | None) -> None:
        self.registry = registry
        self.maybe: list[tuple[str, str]] = []
        self._memo: dict[str | None, Calls] = {}

    def text(self, scan: SourceScan | None, text: str | AstNode, *, bare_root_ok: bool) -> Calls:
        """The calls of ``text``: its scan's when it read everything, else its compiled graph's."""
        if (scan is not None and not scan.opaque) or not remote_policy_active():
            return () if scan is None else scan.remote_nodes
        key = text if isinstance(text, str) else None  # the run's own parse tree: walked once
        if key in self._memo:
            return self._memo[key]
        if key is not None:
            self._memo[key] = ()  # INVARIANT: a text never recurses into itself
        calls = self._compiled(text, bare_root_ok=bare_root_ok)
        if key is not None:
            self._memo[key] = calls
        return calls

    def graph(self, target: Graph | DagNode) -> Calls:
        """Every call a graph makes structurally (PR #1587 round 15, F1b): each reachable
        ``RemoteFetchNode``, plus those in text a node keeps for later — none inside a remote
        context (that text runs at the remote node)."""
        graph = target if isinstance(target, Graph) else Graph(target)
        calls: list[tuple[str, str]] = []
        for node in graph.walk():
            if isinstance(node, RemoteFetchNode):
                calls.append((node.authority, node.path))
            scan = kept_text_scan(node)
            if isinstance(node, MapNode):
                calls.extend(self.text(scan, node.fragment, bare_root_ok=True))
            elif isinstance(node, LazyExprNode):
                calls.extend(self.text(scan, node.text, bare_root_ok=True))
            elif scan is not None:
                calls.extend(scan.remote_nodes)  # a verbatim context: shipped, never spawned here
        return tuple(calls)

    def _compiled(self, text: str | AstNode, *, bare_root_ok: bool) -> Calls:
        try:
            graph = compile_expression(text, registry=self.registry, bare_root_ok=bare_root_ok)
        except Url4Error:
            if bare_root_ok and isinstance(text, str):  # a fragment: FAIL CLOSED (see module)
                hops = (remote_processor_hop(uri) for uri in _URL4_URI.findall(text))
                self.maybe.extend(hop for hop in hops if hop is not None)
            return ()
        return self.graph(graph)


__all__ = ["RemoteWalk"]
