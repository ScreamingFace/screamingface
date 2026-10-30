"""The executor's per-run node memo, with consumer-counted release.

# FEATURE: url4 DAG execution memory — a node's result lives only as long as a consumer
#   still needs it (a 330 MB route result was pinned for the whole run).

One :class:`asyncio.Task` per node per run, keyed by node identity: that is what makes
diamond dependencies resolve exactly once. On top of that, :meth:`RunMemo.count` records,
for every node reachable from the root through ``deps``, how many ``_run`` calls the run
will make for it — one per ``(parent, role)`` edge, since a parent gathers every role, even
two roles naming the same node. Each successful ``_run`` return spends one; when the last
one is spent no further call can come, so the entry (and the result it pins) is dropped.

# INVARIANT: release never changes what a run computes. Every ``_run`` call for a node
#   comes from a parent's ``deps`` gather (each parent resolves once) or the root call, so
#   the count is an upper bound and a released node is never asked for again.
# INVARIANT: the root is never released and nothing is released before counting — an
#   uncounted run (prevalidated spawn/guard graphs) memoises exactly as before, and a reused
#   executor still answers its root from the memo.
# INVARIANT: only a SUCCESSFUL consumption spends a count; a failed or cancelled task stays
#   memoised, so a failed run's state is what it always was.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from url4.dag.node import DagNode, Payload


class RunMemo:
    """``id(node) -> (task, node)``; the node reference pins the id while the entry lives."""

    def __init__(self) -> None:
        self._entries: dict[int, tuple[asyncio.Task, DagNode]] = {}
        self._pending: dict[int, int] = {}

    def count(self, root: DagNode) -> None:
        """Count every node's consumer edges over ``deps`` (held subtrees run elsewhere)."""
        # WHY ``deps``, not ``node_children``: a held subtree (a guard's) executes on its
        # own Executor with its own memo, so its nodes are never ``_run`` here.
        pending: dict[int, int] = {}
        seen = {id(root)}
        stack = [root]
        while stack:
            for dep in stack.pop().deps.values():
                pending[id(dep)] = pending.get(id(dep), 0) + 1
                if id(dep) not in seen:
                    seen.add(id(dep))
                    stack.append(dep)
        pending.pop(id(root), None)  # a root that is also a dep is still never released
        self._pending = pending

    async def resolve(self, node: DagNode, schedule: Callable[[], asyncio.Task]) -> Payload:
        # INVARIANT: check-then-act is safe ONLY because there is no ``await`` between the
        # ``.get()`` and the store: ``schedule`` (``create_task``) does not yield, so on this
        # single-threaded loop the block is an atomic critical section. Two parents of a
        # diamond can both reach here "concurrently" but never interleave
        # (test_diamond_binding_resolved_once). Do not insert an ``await`` (a log call, a
        # metric, anything) between the check and the assignment — a second caller would
        # then schedule a duplicate task, silently resolving a shared node twice.
        entry = self._entries.get(id(node))
        if entry is None:
            self._entries[id(node)] = entry = (schedule(), node)
        result = await entry[0]
        self._spend(node)
        return result

    def _spend(self, node: DagNode) -> None:
        left = self._pending.get(id(node))
        if left is None:
            return
        if left > 1:
            self._pending[id(node)] = left - 1
            return
        del self._pending[id(node)]
        del self._entries[id(node)]
