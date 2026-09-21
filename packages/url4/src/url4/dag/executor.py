"""The dataflow executor: demand-driven, memoized, structurally concurrent.

One :class:`asyncio.Task` per node per run, keyed by node identity — diamond
dependencies resolve exactly once, and independent nodes run in parallel
simply because their tasks coexist. Execution is pull-based from the sink, so
only reachable nodes are ever scheduled.

Tasks live in one :class:`asyncio.TaskGroup`: the first failure cancels every
in-flight sibling (a deliberate improvement over the reference engine's bare
``gather``, which left siblings running). The group's ``ExceptionGroup`` is
unwrapped back to the first real error so callers keep catching plain
:class:`~url4.core.errors.Url4Error` subclasses.

Dependency tasks are created (scheduled) in ``deps`` insertion order, which
keeps *dispatch* deterministic — the sequence of ``create_task`` calls. That is
not the same as I/O *completion* order: independent nodes still run in
parallel, so their ``ctx.io.fetch`` calls may arrive at (or return from) the
I/O layer in any interleaving. An order-sensitive ``IOLayer`` must not assume
FIFO arrival.

The public ``run()`` entry and its composition root live in
:mod:`url4.dag._run` — split by reason to change (second review, F1): this
module is the scheduling engine; that module is the public API surface.
"""

from __future__ import annotations

import asyncio

from url4.core.context import Context
from url4.core.errors import CycleError
from url4.observe import (
    NodeFinished,
    NodeStarted,
    _bind_node_sinks,
)

from url4.dag.compiler import Graph, LoweringRegistry, compile_expression  # isort: skip
from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
    SourceFailure,
    node_children,
    reraise_first,
)


def check_acyclic(root: DagNode) -> None:
    """Raise :class:`CycleError` if the graph reachable from ``root`` has a cycle.

    Iterative DFS with gray/black coloring. Compiler-emitted graphs are acyclic
    by construction; this guards graphs assembled by hand from custom nodes.
    """
    GRAY, BLACK = 1, 2
    state: dict[int, int] = {}
    stack: list[tuple[DagNode, bool]] = [(root, False)]
    while stack:
        node, leaving = stack.pop()
        if leaving:
            state[id(node)] = BLACK
            continue
        if state.get(id(node)) == BLACK:
            continue
        if state.get(id(node)) == GRAY:
            raise CycleError(f"dependency cycle through {type(node).__name__} node")
        state[id(node)] = GRAY
        stack.append((node, True))
        for dep in node_children(node):
            if state.get(id(dep)) != BLACK:
                stack.append((dep, False))


class Executor:
    """Executes one graph run against a per-run :class:`ExecutionContext`."""

    def __init__(self, ctx: ExecutionContext) -> None:
        self._ctx = ctx
        # id -> (task, node); the node reference pins the id for the run's lifetime
        self._memo: dict[int, tuple[asyncio.Task, DagNode]] = {}
        self._tg: asyncio.TaskGroup | None = None
        # Debug-only guard for the resolve-once invariant documented in ``_run``:
        # id -> how many times that node's evaluation task ran. Not allocated, and
        # never incremented or asserted, under ``python -O`` (``__debug__`` is
        # False), so the production hot path is unchanged.
        if __debug__:
            self._resolve_counts: dict[int, int] = {}

    async def execute(self, root: DagNode, *, _prevalidated: bool = False) -> str:
        """Execute ``root`` and render the sink payload as the run's string result.

        A ``list[str]`` sink (a bare hand-built Map/Expand) joins on newlines; a
        tolerated :class:`~url4.dag.node.SourceFailure` sink (a lone optional
        source that failed) renders as the empty result. Compiler-emitted graphs
        end in string-producing sinks, so both cases only arise for hand-built
        graphs.
        """
        result = await self.execute_payload(root, _prevalidated=_prevalidated)
        if isinstance(result, SourceFailure):
            return ""
        return result if isinstance(result, str) else "\n".join(result)

    async def execute_payload(self, root: DagNode, *, _prevalidated: bool = False) -> Payload:
        # Acyclicity is a property of the *graph*, not of the executor, so it is
        # checked once per graph rather than once per ``execute``. The default
        # (``_prevalidated=False``) keeps the guard for graphs assembled by hand
        # from custom nodes (the only graphs that can cycle — compiler-emitted
        # ones are acyclic by construction), pinned by
        # ``test_cycle_detected_before_any_resolve``. The spawn closure validates a
        # compiled fragment once (on first compile) and passes ``True`` so the
        # same memoized graph re-executed once per row / per lazy consumer skips
        # the redundant O(V+E) DFS N times — which would otherwise dwarf the
        # compile it took to get here for large collections.
        if not _prevalidated:
            check_acyclic(root)
        try:
            async with asyncio.TaskGroup() as tg:
                self._tg = tg
                result = await self._run(root, self._ctx._current_span_id)
        except BaseExceptionGroup as group:
            reraise_first(group)
        finally:
            # Checked on the failure paths too: a run that double-resolved a node
            # before failing still did the duplicate I/O. If the assert fires while
            # an error is already propagating, the invariant break becomes the
            # surfaced error and the original travels as its ``__context__`` —
            # the diagnostic is not lost.
            if __debug__:
                self._check_resolve_counts()
        return result

    async def _run(self, node: DagNode, parent_span_id: str | None) -> Payload:
        assert self._tg is not None
        # INVARIANT: check-then-act on ``_memo`` is safe ONLY because there is no
        # ``await`` between the ``.get()`` and the store below: ``create_task`` schedules
        # without yielding, so on this single-threaded loop the whole block is an
        # atomic critical section. Two parents of a diamond dependency can both
        # call ``_run(shared_child)`` "concurrently", but never interleave here.
        # This is what keeps diamond deps resolving exactly once
        # (test_diamond_binding_resolved_once). Do not insert an ``await`` (a log
        # call, a metric, anything) between the check and the assignment — doing
        # so would let a second caller schedule a duplicate task before the first
        # one lands in ``_memo``, silently resolving a shared node twice.
        # `parent_span_id` is a plain value threaded through only for the FIRST
        # caller to reach a given node (the one that creates its task) — a
        # diamond's second caller has no effect on it, which is exactly right:
        # the shared node observes exactly one NodeStarted/NodeFinished pair.
        memoized = self._memo.get(id(node))
        if memoized is None:
            task = self._tg.create_task(self._eval(node, parent_span_id))
            self._memo[id(node)] = memoized = (task, node)
        return await memoized[0]

    def _check_resolve_counts(self) -> None:
        """Assert the resolve-once invariant documented in ``_run`` (debug only).

        Every node scheduled during a *successful* run must have resolved exactly
        once; a shared diamond dependency resolving twice is the silent regression
        the ``_run`` comment forbids. Compiled out under ``python -O``
        (``__debug__`` False), so it costs nothing in production.
        """
        duplicates = {node_id: n for node_id, n in self._resolve_counts.items() if n != 1}
        assert not duplicates, (
            f"executor memo invariant violated: nodes resolved != once: {duplicates}"
        )

    async def _eval(self, node: DagNode, parent_span_id: str | None) -> Payload:
        if __debug__:
            # One entry per node whose evaluation task started. On the success
            # path each scheduled task runs its single ``resolve``, so a count of
            # 2 means the ``_run`` memo let a shared node schedule twice.
            self._resolve_counts[id(node)] = self._resolve_counts.get(id(node), 0) + 1
        obs = self._ctx._obs
        roles = list(node.deps)  # insertion order → deterministic scheduling
        if obs is None:
            values = await asyncio.gather(*(self._run(dep, None) for dep in node.deps.values()))
            return await node.resolve(dict(zip(roles, values, strict=True)), self._ctx)
        span_id = obs.new_span_id()
        obs.emit(NodeStarted(span_id, parent_span_id, type(node).__name__, _detail(node)))
        node_ctx = self._ctx.with_span(span_id)
        try:
            values = await asyncio.gather(*(self._run(dep, span_id) for dep in node.deps.values()))
        except BaseException:
            # A dependency failed (or we were cancelled) BEFORE our own resolve
            # ran — we were aborted, not at fault. "cancelled" covers both a
            # real CancelledError and a dep's Url4Error propagating through
            # gather; the failing dep already emitted its own error finish, so
            # re-attributing its code/permanent here would double-count it.
            obs.emit(NodeFinished(span_id, "cancelled", obs.next_seq()))
            raise
        try:
            with _bind_node_sinks(node_ctx.report_usage, node_ctx.report_response, node_ctx.log):
                result = await node.resolve(dict(zip(roles, values, strict=True)), node_ctx)
        except BaseException as exc:
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
            code = getattr(exc, "code", None)
            permanent = getattr(exc, "permanent", None)
            obs.emit(
                NodeFinished(
                    span_id,
                    status,
                    obs.next_seq(),
                    code if isinstance(code, str) else None,
                    permanent if isinstance(permanent, bool) else None,
                )
            )
            raise
        obs.emit(NodeFinished(span_id, "ok", obs.next_seq()))
        return result


def _detail(node: DagNode) -> str:
    """Best-effort human-readable detail for a :class:`~url4.observe.NodeStarted`
    event — a route/URL/text the node carries, or ``""`` when none applies."""
    for attr in ("target", "path", "text", "body"):
        value = getattr(node, attr, None)
        if isinstance(value, str) and value:
            return value
    return ""


def _wire_spawn(ctx: ExecutionContext, registry: LoweringRegistry | None) -> None:
    """Bind the dynamic-expansion hook: compile a fragment, run it fresh.

    WHY this lives in executor.py and not ``url4.dag._run`` (the F1 split):
    these closures are the only engine-internal constructors of
    :class:`Executor` (one fresh executor per row / per lazy consumer) and they
    consume ``check_acyclic`` — the same reason-to-change neighborhood as the
    executor itself. They also read this module's ``compile_expression`` /
    ``check_acyclic`` globals, which is the monkeypatch seam
    ``tests/unit/test_iteration.py`` spies through.

    The compiled :class:`~url4.dag.compiler.Graph` is memoized by its surface
    text for the run's lifetime. Every row of a
    :class:`~url4.dag.nodes.MapNode` spawns the *same* body text (``body`` and
    ``intent`` are node attributes, constant across rows), and every shared
    :class:`~url4.dag.nodes.LazyExprNode` fragment that several consumers pull
    resolves to the same text — so the lowering (``decode_envelope`` →
    recursive-descent parse → graph wiring) runs once per *unique* fragment, not once
    per row. ``registry`` is fixed for the run (captured here), so the text alone
    is a complete cache key; the dict is scoped to this closure and dies with the
    run, so it can neither leak across a long-lived process nor corrupt results
    across runs with different custom lowerings (a module-level cache would do
    both). The compiled graph is pure template data + structural ``deps`` — all
    per-run state lives in the :class:`Executor` / :class:`ExecutionContext` —
    so reusing one graph across N fresh executors (one per row, each on
    ``ctx.child(scope)`` with that row's ``$item`` binding) is safe by
    construction.
    """
    compiled: dict[str, Graph] = {}

    # WHY `invoking_ctx`, not the `ctx` this closure was wired against: these
    # hooks are stored as `ExecutionContext._spawn_hook` / `_execute_node_hook`
    # and reached through the real bound methods `ExecutionContext.spawn` /
    # `execute_node` — so `invoking_ctx` is always whichever context instance
    # `.spawn(...)`/`.execute_node(...)` was actually called on (carrying that
    # node's own `_current_span_id`), never the run-level `ctx` this function
    # closed over at wiring time. That is what lets a fragment spawned from
    # inside another spawned fragment parent its observation span to its
    # immediate caller instead of to the run root.
    async def spawn_hook(invoking_ctx: ExecutionContext, text: str, scope: Context) -> str:
        graph = compiled.get(text)
        if graph is None:
            # INVARIANT: safe under concurrent rows — ``compile_expression`` is
            # synchronous (no ``await``), so the get → compile → store is an atomic
            # critical section on this single-threaded loop — the second row to reach
            # the same text always hits the cache (mirrors the ``_memo`` invariant
            # in ``_run``). A duplicate compile would only be wasted work anyway
            # (same text → an equivalent graph), never a correctness bug.
            # AIDEV-NOTE: bare_root_ok — spawn is the ENGINE's boundary; its texts are
            # engine-authored wrappers (a map row's "(body)", a deferred
            # collection) whose intent is held outside the text (`OME-508`).
            # User bare groups never reach here: every user entry
            # (build/run/serve, and _slot_from_text for nested sources)
            # rejects them eagerly.
            graph = compile_expression(text, registry=registry, bare_root_ok=True)
            # Acyclicity is a graph property, so validate once per unique
            # fragment, not once per row that re-executes it. Compiler-emitted
            # graphs are acyclic by construction; this single check guards a
            # buggy custom ``LoweringRegistry`` wiring a cycle into a spawned
            # fragment — ``_prevalidated=True`` below then skips the per-row
            # re-check in ``execute`` (which still defaults to checking, for
            # hand-built graphs passed directly to ``run`` / ``execute``).
            check_acyclic(graph.sink)
            compiled[text] = graph
        return await Executor(invoking_ctx.child(scope)).execute(graph.sink, _prevalidated=True)

    async def execute_node_hook(
        invoking_ctx: ExecutionContext, node: DagNode, scope: Context
    ) -> Payload:
        # GuardNode's isolation boundary: the prebuilt subtree runs on its own
        # executor (own TaskGroup), so a tolerated failure surfaces to the guard
        # as an exception to convert — never as a sibling-cancelling TaskGroup
        # fault in the outer run. Payload-preserving (no string join): a guarded
        # ExpandNode must deliver its list[str] to the group intact.
        return await Executor(invoking_ctx.child(scope)).execute_payload(node, _prevalidated=True)

    ctx._spawn_hook = spawn_hook
    ctx._execute_node_hook = execute_node_hook


__all__ = ["Executor", "check_acyclic"]
