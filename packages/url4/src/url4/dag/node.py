"""The DAG core contracts: the :class:`DagNode` protocol and :class:`ExecutionContext`.

This module is the DAG's contracts sink: the node protocol, the payload and hook
types, and the graph-traversal helpers. It imports only the language-core leaves
(context) plus its own private implementation module (:mod:`url4.dag._context`),
so node implementations, the compiler, and the executor can all depend on it
without cycles.

Design notes
------------
- **Expression-problem flip.** The parse tree (:mod:`url4.core.nodes`) is a closed
  union of pure-data nodes with external operations. DAG nodes invert that:
  behavior lives ON the node (``resolve``), so the node set is *open* — any
  object satisfying :class:`DagNode` executes, which is what custom-node
  extensibility requires (Strategy per node type, Liskov behind the protocol).
- **The executor delivers inputs; nodes never await their own deps.** ``deps``
  declares labeled edges (role → node, insertion-ordered — join and dispatch
  order derive from it); ``resolve`` receives the resolved values by role.
  Scheduling policy (memoization, parallelism, cancellation) lives entirely in
  the executor, and nodes stay pure and unit-testable with a plain dict. The
  one capability a node reaches for is I/O, via ``ctx.io`` (the injected
  :class:`~url4.io.layer.IOLayer` port).
- **Payloads are strings** at every language-level boundary. ``list[str]`` is
  an internal contract between the multi-valued producers
  (:class:`~url4.dag.nodes.MapNode` rows, :class:`~url4.dag.nodes.ExpandNode`
  elements) and their Collect/Process consumer: rows may contain newlines, so
  a joined-string edge would corrupt row boundaries.
  :class:`SourceFailure` is the third payload shape: a *tolerated* terminal
  failure of an ``;optional`` source (spec §10.1) — data, not an exception, so
  it flows through the group gather instead of cancelling the TaskGroup.
  Custom nodes should contract on ``str``.

The per-run :class:`ExecutionContext`, the run-wide :class:`BoundedIOLayer`, and
``default_process``/``DEFAULT_RUN_CONCURRENCY`` live in :mod:`url4.dag._context`;
this module re-exports them unchanged — they are part of the public surface, and
``url4.dag`` re-exports them in turn. Engine internals (``_ErrorTally``,
``_ObsState``, the unset-hook fallbacks, ``_declared_default_route``) stay in
``_context``: import them from there, never from here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import NoReturn, Protocol, runtime_checkable

from url4.core.context import Context

from url4.dag._context import (  # isort: skip
    DEFAULT_RUN_CONCURRENCY,
    BoundedIOLayer,
    ExecutionContext,
    default_process,
)


@dataclass(frozen=True)
class SourceFailure:
    """A tolerated source failure: the terminal state of a failed ``;optional``
    source (spec Part A, "Terminal state"). Carries the spec error ``code`` and
    message so the envelope can report the outcome; group nodes skip it in the
    packed sources and in ``$name``/``$N`` population."""

    code: str
    message: str


Payload = str | list[str] | SourceFailure

ProcessFn = Callable[[str, str | None, Context], Awaitable[str]]
SpawnFn = Callable[[str, Context], Awaitable[str]]
ExecuteNodeFn = Callable[["DagNode", Context], Awaitable[Payload]]

# The engine-side wiring shape for spawn/execute_node: unlike SpawnFn/
# ExecuteNodeFn (the PUBLIC ``ctx.spawn(text, scope)`` / ``ctx.execute_node(node,
# scope)`` call shape a resolve() sees), these hooks take the INVOKING context
# explicitly. `ExecutionContext.spawn`/`execute_node` are real bound methods
# (not per-instance closures), so `self` is always whichever context instance
# `.spawn(...)` was called on — the hook then builds its sub-executor from
# THAT context (not a context frozen at wiring time), which is what lets a
# fragment spawned from deep inside another spawned fragment parent its
# observation span under its immediate caller rather than the run root.
SpawnHook = Callable[["ExecutionContext", str, Context], Awaitable[str]]
ExecuteNodeHook = Callable[["ExecutionContext", "DagNode", Context], Awaitable[Payload]]


@runtime_checkable
class DagNode(Protocol):
    """The executable-node port: labeled dependency edges + one operation."""

    @property
    def deps(self) -> Mapping[str, DagNode]:
        """Labeled edges, role → node. Insertion order is significant."""
        ...

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        """Produce this node's value from its resolved dependency ``inputs``."""
        ...


@runtime_checkable
class SupportsChildren(Protocol):
    """A node holding an executable subtree that is NOT one of its ``deps``."""

    def children(self) -> Sequence[DagNode]:
        """Every node this one can execute, edges included."""
        ...


def node_children(node: DagNode) -> list[DagNode]:
    """Every node ``node`` can execute — its edges, plus any held subtree.

    Structural traversals (cycle detection, graph walks) must see subtrees a
    node holds as an *attribute* rather than an edge: an isolation boundary is
    still a path a cycle can run through, and a missed one fails as a hang
    rather than an error. Opting in via :class:`SupportsChildren` keeps that
    the node's own business — the traversals stay ignorant of node types, so a
    future node with an isolated subtree (a retry group, a custom node) is
    covered by implementing ``children()`` rather than by editing every walk.
    """
    if isinstance(node, SupportsChildren):
        return list(node.children())
    return list(node.deps.values())


def first_error(group: BaseExceptionGroup) -> BaseException | None:
    """The first non-cancellation leaf of an exception group, or ``None``.

    TaskGroup failures arrive as (possibly nested) groups; url4 callers catch
    plain :class:`~url4.core.errors.Url4Error` subclasses, so the executor and
    MapNode unwrap with this before re-raising.
    """
    for exc in group.exceptions:
        if isinstance(exc, BaseExceptionGroup):
            found = first_error(exc)
            if found is not None:
                return found
        elif not isinstance(exc, asyncio.CancelledError):
            return exc
    return None


def reraise_first(group: BaseExceptionGroup) -> NoReturn:
    """Re-raise a TaskGroup failure as the plain error url4 callers expect.

    Unwrap the (possibly nested) group to its first non-cancellation leaf via
    :func:`first_error` and re-raise that with ``from None``; a group carrying
    only cancellations re-raises verbatim. Shared by the top-level executor and
    :class:`~url4.dag.nodes.MapNode` so both surface the identical exception
    type for the same underlying failure.
    """
    error = first_error(group)
    if error is None:
        raise group
    raise error from None


__all__ = [
    "DEFAULT_RUN_CONCURRENCY",
    "BoundedIOLayer",
    "DagNode",
    "ExecuteNodeFn",
    "ExecutionContext",
    "Payload",
    "ProcessFn",
    "SourceFailure",
    "SpawnFn",
    "default_process",
    "first_error",
    "reraise_first",
]
