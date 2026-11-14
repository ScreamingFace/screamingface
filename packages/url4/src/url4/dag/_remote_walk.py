"""The structural ``url4://`` calls a run makes: the run-start remote precheck's input.

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run that names another node is refused before my node runs
anything for it, wherever its text puts the call: a group the strict grammar rejects, a call's
context, an iteration's per-row intent, a holdings context sent to my own evaluation path.

INVARIANT (PR #1750 round 7, owner decision "always compile"): under a remote-node policy the
precheck never trusts the strict scan. It compiles the run text exactly as ``run()`` does and
every fragment the graph will spawn (``MapNode.fragment``, ``LazyExprNode.text``, and every
verbatim call context as ``(context)``, the way the node's own evaluation path would run it)
exactly as the spawn hook does, and walks those graphs. Only a TRUE prose context (no holdings
ref) that fails to compile is read as the scan always read it (rounds 8/9; prose naming
``url4://`` keeps running); a holdings context is a fragment, fail closed.
Every call found feeds the ONE precheck (:func:`url4.dag.remote_nodes.precheck_remote_nodes`).
WHY (round 7): rounds 5/6 kept a scan-first shortcut, and each re-check found a shape the scan
did not see (a per-row intent, a holdings context); the compiled graph is what actually runs.
INVARIANT (FAIL CLOSED): a fragment that does not compile is not call-free when it names
``url4://`` OUTSIDE quotes: each such URI becomes a ``maybe`` call (refused unless it is a
client's still-unspent hop). Quoted text is data, never a call (C4). The run's own text that
does not compile adds nothing: ``run()`` then fails at compile, before any node executes. ANY
exception a fragment's compile raises means "does not compile" — none escapes the precheck.
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
from typing import Protocol, runtime_checkable

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
# INVARIANT (round 9): a spawned text is keyed by its KIND too, so a map/lazy fragment never
# shares a cache entry (and so prose mode) with a verbatim context of the same text.
_FRAGMENT = "fragment"  # a map body / lazy group: compiled as the spawn hook does
_CONTEXT = "context"  # a verbatim call context, as ``(context)``: prose only if TRUE prose
_EVAL = "eval"  # what the node's own eval path runs for a call (round 10): compiled as run()
Key = tuple[str, str]
_ROOT: Key = ("root", "")  # the text or graph a precheck starts from


@runtime_checkable
class SupportsEvalPath(Protocol):
    """The optional io port: what the world's own eval path RUNS for a relative ``target``.

    ``eval_expression(target)`` is ``(expression_text, processor)`` for a target the world
    dispatches to its eval path, else ``None`` (round 10). INVARIANT: the adapter owns the answer
    (``Url4Node`` uses its own dispatch and reassembly), so this precheck never copies them.
    WHY declared here: the engine defines the port it consumes; the node implements it
    structurally and never imports the engine (layering).
    """

    def eval_expression(self, target: str) -> tuple[str, str | None] | None: ...


@dataclass
class _Unit:
    """One compiled text: its own calls, and the texts it spawns (each occurrence, keyed)."""

    calls: list[Call] = field(default_factory=list)
    spawns: list[Key] = field(default_factory=list)


class RemoteWalk:
    """One precheck's walk.

    ``maybe`` collects the possible calls of uncompilable fragments; ``processors`` the
    ``processor=`` values of calls to the node's own eval path, for the async precheck to read
    as it reads the run's own processor.
    """

    def __init__(self, registry: LoweringRegistry | None, io: object = None) -> None:
        self.registry = registry
        self.io = io
        self.maybe: list[Call] = []
        self.processors: list[str] = []
        self._units: dict[Key, _Unit] = {}
        self._contexts: dict[Key, tuple[RelUrlNode, str]] = {}

    def text(self, text: str | AstNode, *, bare_root_ok: bool) -> Calls:
        """The calls of ``text``, compiled as ``run()`` (or, a fragment, the spawn hook) does."""
        if not remote_policy_active():
            return ()
        graph = self._compile(text, bare_root_ok=bare_root_ok)
        if isinstance(graph, RecursionError) and not self.maybe_calls(text):
            raise _too_deep() from None
        # WHY no fallback otherwise: the run's own text that does not compile fails there first
        return self._total(self._unit(graph)) if isinstance(graph, Graph) else ()

    def graph(self, target: Graph | DagNode) -> Calls:
        """Every call a pre-built graph makes (PR #1587 round 15, F1b), its spawns included."""
        if not remote_policy_active():
            return ()
        return self._total(self._unit(target if isinstance(target, Graph) else Graph(target)))

    def maybe_calls(self, text: str | AstNode) -> bool:
        """Add each unquoted ``url4://`` URI ``text`` names as a ``maybe`` call; whether any."""
        found = _URL4_URI.findall(_unquoted(text)) if isinstance(text, str) else []
        hops = [hop for hop in map(remote_processor_hop, found) if hop is not None]
        self.maybe.extend(hops)
        return bool(hops)

    def _unit(self, graph: Graph) -> _Unit:
        unit = _Unit()
        for node in graph.walk():
            if isinstance(node, RemoteFetchNode):
                unit.calls.append((node.authority, node.path))
            spawned = _spawned_text(node)
            if spawned is not None:
                unit.spawns.append((_FRAGMENT, spawned))
            elif isinstance(node, RelUrlNode):
                unit.spawns.extend(self._call_spawns(node))
        return unit

    def _call_spawns(self, node: RelUrlNode) -> list[Key]:
        """What a relative call runs on this node: the eval path's text, else its context.

        INVARIANT (round 10, owner): a call the io world routes to its own eval path is walked as
        EXACTLY the expression that path runs (``SupportsEvalPath``: its reassembled
        ``(context)!intent`` plus param chain) and its ``processor=`` is checked like the run's.
        A resolved (slotted) context is run-time data there: the owner-accepted limit.
        INVARIANT (rounds 8/9): every verbatim context is also compiled as ``(context)``.
        """
        spawns: list[Key] = []
        evaluated = self._evaluated(node)
        if evaluated is not None:
            text, processor = evaluated
            if processor:
                self.processors.append(processor)
            if node.ctx_slots is None or not node.is_expr:
                spawns.append((_EVAL, text))
        if node.is_expr and node.ctx_slots is None and node.context:
            # WHY kept for an eval-path call too: the rounds 8/9 checks of the context itself
            # stay as they were; the eval text adds what only the appended intent reveals.
            key = (_CONTEXT, f"({node.context})")
            self._contexts.setdefault(key, (node, node.context))
            spawns.append(key)
        return spawns

    def _evaluated(self, node: RelUrlNode) -> tuple[str, str | None] | None:
        target = node.static_target() if isinstance(self.io, SupportsEvalPath) else None
        if target is None or not isinstance(self.io, SupportsEvalPath):
            return None
        try:
            return self.io.eval_expression(target)
        except Url4Error:
            return None  # the dispatch refuses this very target before it runs anything

    def _total(self, root: _Unit) -> Calls:
        """``root``'s calls plus every spawned text's, each compiled once, with no recursion."""
        self._units[_ROOT] = root
        totals: dict[Key, Calls] = {}
        open_keys: set[Key] = set()  # INVARIANT: a text never waits on itself (a spawn cycle)
        stack: list[tuple[Key, bool]] = [(_ROOT, False)]
        while stack:
            key, children_done = stack.pop()
            if key in totals or (key in open_keys and not children_done):
                continue
            unit = self._units.get(key) or self._spawn_unit(key)
            if children_done:
                spawned = (totals.get(child, ()) for child in unit.spawns)  # () only on a cycle
                totals[key] = _capped((unit.calls, *spawned))
                continue
            open_keys.add(key)
            stack.append((key, True))
            stack.extend((child, False) for child in unit.spawns if child not in totals)
        del self._units[_ROOT]
        return totals[_ROOT]

    def _spawn_unit(self, key: Key) -> _Unit:
        kind, text = key
        graph = self._compile(text, bare_root_ok=kind != _EVAL)  # the eval path runs run(text)
        if isinstance(graph, Graph):
            unit = self._unit(graph)
        else:
            unit = _Unit(calls=list(self._uncompiled(key, graph)))
        self._units[key] = unit
        return unit

    def _uncompiled(self, key: Key, error: Exception) -> Calls:
        """FAIL CLOSED for a spawned text that does not compile (see the module).

        Only TRUE prose (a verbatim context with no holdings ref) may read its scan instead of
        the URI fallback, and after a too-deep compile only when it names no ``url4://`` URI.
        WHY decided here, lazily: scanning a context walks every context nested in it, so doing
        it for each level up front made nested ``@`` contexts cubic (round 10).
        """
        prose = self._prose_calls(key)
        too_deep = isinstance(error, RecursionError)
        found = self.maybe_calls(key[1]) if prose is None or too_deep else False
        if too_deep and not found and prose is None:
            raise _too_deep() from None
        return prose or ()

    def _prose_calls(self, key: Key) -> Calls | None:
        if key[0] != _CONTEXT:
            return None
        node, context = self._contexts[key]
        scan = None if holds_holdings_ref(context) else kept_text_scan(node)
        return None if scan is None else scan.remote_nodes

    def _compile(self, text: str | AstNode, *, bare_root_ok: bool) -> Graph | Exception:
        """``text``'s graph, or the exception its compile raised.

        WHY any exception (round 8): a compile is not the precheck's to raise from; a raw
        ValueError (``(@,)``) once escaped the precheck of a run that runs on main.
        """
        try:
            return compile_expression(text, registry=self.registry, bare_root_ok=bare_root_ok)
        except Exception as error:  # RecursionError included: the callers tell them apart
            return error


def _spawned_text(node: DagNode) -> str | None:
    """The fragment text ``node`` spawns on this node at run time, if any."""
    if isinstance(node, MapNode):
        return node.fragment
    return node.text if isinstance(node, LazyExprNode) else None


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


__all__ = ["RemoteWalk", "SupportsEvalPath"]
