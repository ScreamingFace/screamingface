"""The structural ``url4://`` calls a run makes: the run-start remote precheck's input.

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run that names another node is refused before my node runs
anything for it, wherever its text puts the call: a group the strict grammar rejects, a call's
context, an iteration's per-row intent, a holdings context sent to my own evaluation path.

INVARIANT (PR #1750 round 7, owner decision "always compile"): under a remote-node policy the
precheck never trusts the strict scan. It compiles the run text exactly as ``run()`` does and
every fragment the graph will spawn (``MapNode.fragment``, ``LazyExprNode.text``, a holdings
context as the evaluation path reads it) exactly as the spawn hook does, and walks those graphs.
Every call found feeds the ONE precheck (:func:`url4.dag.remote_nodes.precheck_remote_nodes`).
WHY (round 7): rounds 5/6 kept a scan-first shortcut, and each re-check found a shape the scan
did not see (a per-row intent, a holdings context); the compiled graph is what actually runs.
INVARIANT (FAIL CLOSED): a fragment that does not compile is not call-free when it names
``url4://`` OUTSIDE quotes: each such URI becomes a ``maybe`` call (refused unless it is a
client's still-unspent hop). Quoted text is data, never a call (C4). The run's own text that
does not compile adds nothing: ``run()`` then fails at compile, before any node executes.
INVARIANT (FAIL CLOSED, round 7): a compile the stack cannot finish — the run text or a
fragment — is never read as "no calls": its unquoted ``url4://`` URIs are ``maybe`` calls, and
naming none it is refused ``malformed_source`` (permanent). The precheck runs deeper in the stack
than ``run()``'s own compile, so a text at one exact depth once overflowed only here and ran
unchecked.
INVARIANT (round 6): the walk itself is iterative; it adds no recursion of its own.
WHY policy-gated: outside a node context the precheck refuses nothing, so a bare ``url4.run()``
compiles nothing extra.
WHY each occurrence counts (capped at two): a repeated fragment is compiled once, but its calls
count per occurrence, so a second call to a client's one hop is still a second call; two is all
the precheck can tell apart, and the cap keeps a fragment repeated at every level linear.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from url4.core.errors import ErrorCode, ParseError, Url4Error
from url4.core.nodes import Node as AstNode

from url4.dag._graph_admission import kept_text_scan  # isort: skip
from url4.dag.compiler import Graph, LoweringRegistry, compile_expression  # isort: skip
from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import LazyExprNode, MapNode, RelUrlNode, RemoteFetchNode  # isort: skip
from url4.dag.processor import remote_processor_hop  # isort: skip
from url4.dag.remote_nodes import remote_policy_active  # isort: skip
from url4.dag.source_scan import holds_holdings_ref  # isort: skip

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

    def text(self, text: str | AstNode, *, bare_root_ok: bool) -> Calls:
        """The calls of ``text``, compiled as ``run()`` (or, a fragment, the spawn hook) does."""
        if not remote_policy_active():
            return ()
        graph = self._compile(text, bare_root_ok=bare_root_ok)
        return () if graph is None else self._total(self._unit(graph))

    def graph(self, target: Graph | DagNode) -> Calls:
        """Every call a pre-built graph makes (PR #1587 round 15, F1b), its spawns included."""
        if not remote_policy_active():
            return ()
        return self._total(self._unit(target if isinstance(target, Graph) else Graph(target)))

    def _unit(self, graph: Graph) -> _Unit:
        unit = _Unit()
        for node in graph.walk():
            if isinstance(node, RemoteFetchNode):
                unit.calls.append((node.authority, node.path))
            spawned = _spawned_text(node)
            if spawned is not None:
                unit.spawns.append(spawned)
                continue
            scan = kept_text_scan(node)
            if scan is not None:
                # a prose context, shipped verbatim to its route: read as the scan always read it
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
        except RecursionError:
            # FAIL CLOSED: the URIs it names are refused as remote calls; naming none, it is
            # refused as too deep to check — never read as call-free.
            if not self._maybe_calls(text):
                raise _too_deep() from None
        except Url4Error:
            if bare_root_ok:  # a fragment (the run's own text then fails at its compile)
                self._maybe_calls(text)
        return None

    def _maybe_calls(self, text: str | AstNode) -> bool:
        """Add each unquoted ``url4://`` URI ``text`` names as a ``maybe`` call; whether any."""
        found = _URL4_URI.findall(_unquoted(text)) if isinstance(text, str) else []
        hops = [hop for hop in map(remote_processor_hop, found) if hop is not None]
        self.maybe.extend(hops)
        return bool(hops)


def _spawned_text(node: DagNode) -> str | None:
    """The text ``node`` compiles and runs later on this node, if any."""
    text: str | None = None
    if isinstance(node, MapNode):
        text = node.fragment
    elif isinstance(node, LazyExprNode):
        text = node.text
    elif isinstance(node, RelUrlNode) and node.ctx_slots is None and node.context:
        # WHY (round 7): a holdings context ships verbatim, and the node's own evaluation path
        # runs it as an expression HERE; any other verbatim context is prose (scanned as before).
        if holds_holdings_ref(node.context):
            text = f"({node.context})"
    return text


def _too_deep() -> ParseError:
    return ParseError(
        "the expression is nested too deeply to check it for remote-node calls before it runs",
        code=ErrorCode.MALFORMED_SOURCE,
        permanent=True,
    )


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
