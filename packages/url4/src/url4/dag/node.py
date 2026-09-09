"""The DAG core contracts: the :class:`DagNode` protocol and :class:`ExecutionContext`.

This module is the DAG's dependency sink — it imports only the language-core
leaves (context, io_layer), so node implementations, the compiler, and the
executor can all depend on it without cycles.

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
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, NoReturn, Protocol, runtime_checkable

from url4.core.context import Context
from url4.io.layer import (
    FetchRequest,
    FetchResult,
    IOLayer,
    SupportsDefaultRoute,
    SupportsFetchEx,
    SupportsHoldings,
    SupportsProcessorRoutes,
)
from url4.observe import Log, LogScalar, ModelResponse, ObservationEvent, Observer, Usage


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


async def default_process(sources: str, intent: str | None, scope: Context) -> str:
    """The default merge of resolved sources and intent (Template Method hook)."""
    if intent and sources:
        return f"{intent}\n\n{sources}"
    return intent or sources or ""


class _ErrorTally:
    """A shared mutable counter so child contexts report into one total."""

    def __init__(self) -> None:
        self.count = 0


class _ObsState:
    """Per-run observation state: the observer, the run's trace id, and a
    shared monotonic sequence counter (:class:`~url4.observe.NodeFinished` /
    :class:`~url4.observe.RunFinished` carry ``engine_seq`` so a downstream
    consumer can order finishes even across concurrent spans). One instance is
    minted per :func:`~url4.dag.executor.run` call and shared by every
    :class:`ExecutionContext` in that run (via :meth:`ExecutionContext.child` /
    :meth:`ExecutionContext.with_span`), the same way :class:`_ErrorTally` is
    shared — engine-internal wiring, deliberately kept out of the public
    :mod:`url4.observe` surface.
    """

    __slots__ = ("observer", "trace_id", "_seq")

    def __init__(self, observer: Observer, trace_id: str) -> None:
        self.observer = observer
        self.trace_id = trace_id
        self._seq = 0

    def emit(self, event: ObservationEvent) -> None:
        self.observer.on_event(event)

    def new_span_id(self) -> str:
        return secrets.token_hex(8)  # 16 hex chars

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


# WHY: the default run-wide fan-out cap (see BoundedIOLayer below). Without it, a
# bare fan-out group, a FanoutReduceNode's parallel calls, or the aggregate of
# many MapNode rows each issue unboundedly many concurrent ctx.io.fetch calls,
# with only an IOLayer's own (possibly nonexistent) backstop — httpx's
# connection pool for HttpIOLayer, nothing at all for StaticIOLayer or a custom
# adapter. This is deliberately looser than MapNode's per-iteration default
# (DEFAULT_MAP_CONCURRENCY): it caps the WHOLE run's I/O, of which any one map
# is only a part.
DEFAULT_RUN_CONCURRENCY = 32


class BoundedIOLayer:
    """Wraps an :class:`~url4.io.layer.IOLayer` with a semaphore-bounded ``fetch``.

    This is the run-wide admission-control gate: the semaphore is acquired
    only around the inner ``fetch`` call itself — never across substitution,
    compilation, or a node's own scope-building — so it bounds concurrent I/O
    in flight without serializing anything else. :func:`run` installs one
    instance per run and every node (and every spawned sub-executor, via
    :meth:`ExecutionContext.child` sharing ``io``) fetches through it, so a
    fan-out of N independent sources or M map rows collectively never exceeds
    the bound — layered *underneath* any node-local cap such as MapNode's
    ``;iteration.concurrency``, never replacing it.

    The optional capability ports (``fetch_ex``, ``fetch_holdings``) are
    forwarded — bounded by the same semaphore — but only when the *inner*
    adapter provides them: they are bound as instance attributes so a
    ``runtime_checkable`` isinstance test against the wrapper reports exactly
    the wrapped adapter's capabilities, never more.
    """

    # WHY: conditionally bound in __init__ (annotation only — no class attribute, so
    # hasattr/isinstance stay false when the inner adapter lacks the port).
    fetch_ex: Callable[[FetchRequest], Awaitable[FetchResult]]
    fetch_holdings: Callable[[str | None, str | None], Awaitable[str]]
    processor_routes: Callable[[], Sequence[str]]

    def __init__(self, inner: IOLayer, limit: int) -> None:
        self._inner = inner
        self._sem = asyncio.Semaphore(limit)
        if isinstance(inner, SupportsFetchEx):
            self.fetch_ex = self._bounded_fetch_ex
        if isinstance(inner, SupportsHoldings):
            self.fetch_holdings = self._bounded_fetch_holdings
        if isinstance(inner, SupportsProcessorRoutes):
            # Not bounded: declaring routes is not I/O. Forwarded so a
            # `processor=` id still resolves through the wrapper (§27.3).
            self.processor_routes = inner.processor_routes

    async def fetch(self, target: str, *, relative: bool) -> str:
        async with self._sem:
            return await self._inner.fetch(target, relative=relative)

    async def _bounded_fetch_ex(self, request: FetchRequest) -> FetchResult:
        async with self._sem:
            return await self._inner.fetch_ex(request)  # type: ignore[attr-defined]

    async def _bounded_fetch_holdings(self, identity: str | None, collection: str | None) -> str:
        async with self._sem:
            return await self._inner.fetch_holdings(identity, collection)  # type: ignore[attr-defined]


def _declared_default_route(io: IOLayer) -> str | None:
    """The io world's first declared route, or ``None`` for registry-less adapters."""
    if isinstance(io, SupportsDefaultRoute):
        return io.default_route()
    return None


class ExecutionContext:
    """Per-run capabilities handed to every ``resolve`` call.

    Carries the :class:`~url4.io.layer.IOLayer` port ``io`` (all I/O flows
    through it), the reducer ``processor`` path (unset, it resolves to the io
    world's first declared route via
    :class:`~url4.io.layer.SupportsDefaultRoute`), the lexical ``scope`` for
    ``$name`` fallback in dynamically spawned fragments, the overridable
    ``process`` merge hook, ``strict_fields`` (the spec §5.3.4.1 field-path
    error mode: lenient/LLM by default, strict/RDS when True), and two
    executor-injected escape hatches nodes only ever call:

    - ``spawn`` — compile and execute a url4 *text fragment* on a fresh
      executor (MapNode rows, lazy sub-expressions);
    - ``execute_node`` — execute a *prebuilt node subtree* on a fresh executor
      (GuardNode's isolation boundary: a guarded failure must surface as a
      value, which requires the subtree to fail inside its own TaskGroup, not
      the outer one).

    Contexts are per-run — no state is shared across runs — but ``child``
    frames share the run's error tally so ``collected_errors`` totals
    per-row failures captured under ``;iteration.on_error=collect``.
    """

    def __init__(
        self,
        io: IOLayer,
        *,
        processor: str | None = None,
        process: ProcessFn = default_process,
        scope: Context | None = None,
        strict_fields: bool = False,
        self_collection: str | None = None,
        _tally: _ErrorTally | None = None,
        _spawn_hook: SpawnHook | None = None,
        _execute_node_hook: ExecuteNodeHook | None = None,
        _obs: _ObsState | None = None,
        _current_span_id: str | None = None,
    ) -> None:
        self.io = io
        # The self-holdings collection for THIS run — spec §5.6.3.1: "a path
        # qualifier after the endpoint selects which collection `@` refers to".
        # WHY: it lives here, not on the node, because a node serves concurrent
        # requests — per-request state on a shared node would race.
        self.self_collection = self_collection
        # WHY: no hardcoded processor route in the core — unset resolves to the
        # io world's first declared route (SupportsDefaultRoute), or stays None
        # (a fan-out reduce then fails with a clear error naming the fix).
        self.processor = processor if processor is not None else _declared_default_route(io)
        self.process = process
        self.scope = scope if scope is not None else Context.root()
        self.strict_fields = strict_fields
        self._tally = _tally if _tally is not None else _ErrorTally()
        self._spawn_hook = _spawn_hook
        self._execute_node_hook = _execute_node_hook
        # Observation wiring (both None unless a run() caller passed `observer=`):
        # `_obs` is the shared per-run emitter, `_current_span_id` is the span
        # THIS context's resolve() runs under — the parent for anything it spawns.
        self._obs = _obs
        self._current_span_id = _current_span_id

    @property
    def collected_errors(self) -> int:
        """Per-row failures captured under ``;iteration.on_error=collect`` this run."""
        return self._tally.count

    def record_collected_error(self) -> None:
        self._tally.count += 1

    def child(self, scope: Context) -> ExecutionContext:
        """A context for a spawned fragment: new scope, shared everything else."""
        return ExecutionContext(
            self.io,
            processor=self.processor,
            process=self.process,
            scope=scope,
            strict_fields=self.strict_fields,
            self_collection=self.self_collection,
            _tally=self._tally,
            _spawn_hook=self._spawn_hook,
            _execute_node_hook=self._execute_node_hook,
            _obs=self._obs,
            _current_span_id=self._current_span_id,
        )

    def with_span(self, span_id: str) -> ExecutionContext:
        """The SAME scope, under a new current-span — the parent id for
        anything this node's ``resolve`` spawns (a lazy fragment, a map row,
        a guarded subtree). Every other field clones like :meth:`child`."""
        return ExecutionContext(
            self.io,
            processor=self.processor,
            process=self.process,
            scope=self.scope,
            strict_fields=self.strict_fields,
            self_collection=self.self_collection,
            _tally=self._tally,
            _spawn_hook=self._spawn_hook,
            _execute_node_hook=self._execute_node_hook,
            _obs=self._obs,
            _current_span_id=span_id,
        )

    async def spawn(self, text: str, scope: Context) -> str:
        """Compile and execute a url4 *text fragment* on a fresh executor
        (MapNode rows, lazy sub-expressions). A real bound method — not a
        per-instance closure — so the engine hook always sees the context
        `.spawn` was actually called on, which is what lets a spawned
        fragment's observation span parent to ITS caller rather than to
        whichever context first wired the hook."""
        if self._spawn_hook is None:
            return await _spawn_unset(text, scope)
        return await self._spawn_hook(self, text, scope)

    async def execute_node(self, node: DagNode, scope: Context) -> Payload:
        """Execute a *prebuilt node subtree* on a fresh executor (GuardNode's
        isolation boundary). See :meth:`spawn` for why this is a bound method."""
        if self._execute_node_hook is None:
            return await _execute_node_unset(node, scope)
        return await self._execute_node_hook(self, node, scope)

    def report_usage(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        response_model: str | None = None,
        cache_read_tokens: int | None = None,
        cache_creation_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        cost_usd: Decimal | None = None,
    ) -> None:
        """Report model token usage under this node's current span. A no-op
        when no ``observer`` was passed to :func:`~url4.dag.executor.run`.

        ``model`` is the REQUESTED model; pass ``response_model`` when the provider
        reports which model actually served the call (see :class:`~url4.observe.Usage`).

        The cache/reasoning classes and ``cost_usd`` are optional evidence: omit any the
        provider did not report. INVARIANT: omitting one leaves it ``None``, which means
        "not reported" and is NOT the same claim as ``0`` — see
        :class:`~url4.observe.Usage`. ``cost_usd`` is already USD; this layer performs no
        conversion or arithmetic on it.
        """
        if self._obs is not None:
            self._obs.emit(
                Usage(
                    self._current_span_id,
                    provider,
                    model,
                    input_tokens,
                    output_tokens,
                    response_model,
                    cache_read_tokens,
                    cache_creation_tokens,
                    reasoning_tokens,
                    cost_usd,
                )
            )

    def report_response(
        self,
        *,
        finish_reason: str | None,
        refusal: str | None,
        cache_status: Literal["hit", "miss", "bypass"] | None = None,
        cache_reason: str | None = None,
    ) -> None:
        """Report how one model round trip ended, under this node's current
        span. A no-op when no ``observer`` was passed to
        :func:`~url4.dag.executor.run`.

        INVARIANT: emits one event per call — a node making several round trips
        (a tool-calling turn) produces several events on the same span, never a
        single collapsed one.

        ``cache_status`` / ``cache_reason`` describe whether the answering
        gateway served this trip from its response cache. They DEFAULT to
        nothing on purpose: not every world talks to a cache, and this is a
        live seam whose existing callers must keep compiling unchanged.
        """
        if self._obs is not None:
            self._obs.emit(
                ModelResponse(
                    self._current_span_id, finish_reason, refusal, cache_status, cache_reason
                )
            )

    def log(
        self, severity: str, body: str, *, attributes: Mapping[str, LogScalar] | None = None
    ) -> None:
        """Emit a log line attributed to this node's current span. A no-op
        when no ``observer`` was passed to :func:`~url4.dag.executor.run`.

        Attributes are snapshotted immutably. Observer failures still propagate;
        use ``current_log_sink()`` for best-effort producer emission.
        """
        if self._obs is not None:
            self._obs.emit(Log(self._current_span_id, severity, body, attributes or {}))


async def _spawn_unset(text: str, scope: Context) -> str:
    raise RuntimeError(
        "ExecutionContext.spawn is not wired — execute nodes via url4.dag.run/Executor"
    )


async def _execute_node_unset(node: DagNode, scope: Context) -> Payload:
    raise RuntimeError(
        "ExecutionContext.execute_node is not wired — execute nodes via url4.dag.run/Executor"
    )


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
