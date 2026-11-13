"""The structural ``url4://`` calls of a run's text or graph: the run-start precheck's input.

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run that names another node is refused before my node runs
anything for it, even when its text holds a nested group the strict grammar rejects but the
engine compiles (``(('r1','r2')*(/b($item)!'i'))!'g'``), in a group, a map body or a call's
context.

INVARIANT (PR #1750 rounds 5/6, owner "fallback graph walk"): the strict scan
(:mod:`url4.dag.source_scan`) is used only where it read the WHOLE text. A text it could not
fully read — the run's text, a deferred group (``LazyExprNode.text``), a map body
(``MapNode.fragment``, whole: a segment may compile only inside it), any of them holding such a
segment in a call's context — is compiled exactly as ``run()`` or the spawn hook compiles it,
and that graph is walked. Every call found feeds the ONE precheck
(:func:`url4.dag.remote_nodes.precheck_remote_nodes`).
INVARIANT (FAIL CLOSED, round 5 security review): a fragment that does not compile (or is too
deep to compile) is not call-free when it names ``url4://`` OUTSIDE quotes: each such URI becomes
a ``maybe`` call (refused unless it is a client's still-unspent hop). Quoted text is data, never a
call (C4), so a quoted mention adds nothing (round 6). The run's own text is exempt: if it does
not compile, ``run()`` fails before any node executes.
INVARIANT (round 6): the walk is iterative — a deeply nested run must never escape ``run()`` as a
raw ``RecursionError`` under a node policy when it runs fine without one.
WHY policy-gated compiles: outside a node context the precheck refuses nothing, so a bare
``url4.run()`` compiles nothing extra.
WHY each occurrence counts (capped at two): a repeated fragment is compiled once, but its calls
count per occurrence, so a second call to a client's one hop is still a second call; two is all
the precheck can tell apart, and the cap keeps a fragment repeated at every level linear.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from url4.core.errors import Url4Error
from url4.core.nodes import Node as AstNode

from url4.dag._graph_admission import kept_text_scan  # isort: skip
from url4.dag.compiler import Graph, LoweringRegistry, compile_expression  # isort: skip
from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import LazyExprNode, MapNode, RemoteFetchNode  # isort: skip
from url4.dag.processor import remote_processor_hop  # isort: skip
from url4.dag.remote_nodes import remote_policy_active  # isort: skip
from url4.dag.source_scan import SourceScan  # isort: skip

Call = tuple[str, str]
Calls = tuple[Call, ...]
_URL4_URI = re.compile(r"url4://[^\s'\"(),!;*]+", re.IGNORECASE)
_QUOTE_RUN = re.compile(r"'(?:\\.|[^'\\])*'", re.DOTALL)  # mirrors core._scan.skip_quoted
_ROOT = ""  # the key of the text or graph a precheck starts from (a fragment is never empty)


@dataclass
class _Unit:
    """One compiled text: its own calls, and the fragment texts it spawns (each occurrence)."""

    calls: list[Call] = field(default_factory=list)
    spawns: list[str] = field(default_factory=list)


class RemoteWalk:
    """One precheck's walk. ``maybe`` collects the possible calls of uncompilable fragments."""

    def __init__(self, registry: LoweringRegistry | None) -> None:
        self.registry = registry
        self.maybe: list[Call] = []
        self._units: dict[str, _Unit] = {}

    def text(self, scan: SourceScan | None, text: str | AstNode, *, bare_root_ok: bool) -> Calls:
        """The calls of ``text``: its scan's when it read everything, else its compiled graph's."""
        if (scan is not None and not scan.opaque) or not remote_policy_active():
            return () if scan is None else scan.remote_nodes
        graph = self._compile(text, bare_root_ok=bare_root_ok)
        return () if graph is None else self._total(self._unit(graph))

    def graph(self, target: Graph | DagNode) -> Calls:
        """Every call a graph makes structurally (PR #1587 round 15, F1b): each reachable
        ``RemoteFetchNode``, plus those in text a node keeps for later — none inside a remote
        context (that text runs at the remote node)."""
        return self._total(self._unit(target if isinstance(target, Graph) else Graph(target)))

    def _unit(self, graph: Graph) -> _Unit:
        unit = _Unit()
        for node in graph.walk():
            if isinstance(node, RemoteFetchNode):
                unit.calls.append((node.authority, node.path))
            spawned = _spawned_text(node)
            if spawned is not None and remote_policy_active():
                # WHY no strict scan first: the spawn hook compiles this text one level at a time;
                # re-parsing it whole at every level made a deep run cubic (round 6).
                unit.spawns.append(spawned)
                continue
            scan = kept_text_scan(node)
            if scan is not None:
                # no policy: the scan, as before; or a verbatim context (shipped, never run here)
                unit.calls.extend(scan.remote_nodes)
        return unit

    def _total(self, root: _Unit) -> Calls:
        """``root``'s calls plus every spawned text's, each compiled once, with no recursion."""
        self._units[_ROOT] = root
        totals: dict[str, Calls] = {}
        open_keys: set[str] = set()  # INVARIANT: a text never waits on itself (a spawn cycle)
        stack: list[tuple[str, bool]] = [(_ROOT, False)]
        while stack:
            key, children_done = stack.pop()
            if key in totals or (key in open_keys and not children_done):
                continue
            unit = self._units.get(key) or self._spawn_unit(key)
            if children_done:
                spawned = (totals.get(text, ()) for text in unit.spawns)  # () only on a cycle
                totals[key] = _capped((unit.calls, *spawned))
                continue
            open_keys.add(key)
            stack.append((key, True))
            stack.extend((text, False) for text in unit.spawns if text not in totals)
        del self._units[_ROOT]
        return totals[_ROOT]

    def _spawn_unit(self, text: str) -> _Unit:
        graph = self._compile(text, bare_root_ok=True)
        unit = _Unit() if graph is None else self._unit(graph)
        self._units[text] = unit
        return unit

    def _compile(self, text: str | AstNode, *, bare_root_ok: bool) -> Graph | None:
        try:
            return compile_expression(text, registry=self.registry, bare_root_ok=bare_root_ok)
        except (Url4Error, RecursionError):
            if bare_root_ok and isinstance(text, str):  # a fragment: FAIL CLOSED (see module)
                hops = (remote_processor_hop(uri) for uri in _URL4_URI.findall(_unquoted(text)))
                self.maybe.extend(hop for hop in hops if hop is not None)
            return None


def _spawned_text(node: DagNode) -> str | None:
    if isinstance(node, MapNode):
        return node.fragment
    return node.text if isinstance(node, LazyExprNode) else None


def _capped(parts: Iterable[Iterable[Call]]) -> Calls:
    seen: Counter[Call] = Counter()
    calls: list[Call] = []
    for part in parts:
        for call in part:
            if seen[call] < 2:
                seen[call] += 1
                calls.append(call)
    return tuple(calls)


def _unquoted(text: str) -> str:
    """``text`` with every terminated ``'…'`` quote run blanked (``\\'`` / ``\\\\`` escapes
    honoured), as the grammar reads quotes (C4); an unterminated quote stays a literal."""
    return _QUOTE_RUN.sub(" ", text)


__all__ = ["RemoteWalk"]
