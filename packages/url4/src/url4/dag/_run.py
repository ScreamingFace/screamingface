"""The public ``run()`` entry: validation, composition root, and run lifecycle.

Split from :mod:`url4.dag.executor` (second review, F1) by reason to change:
the :class:`~url4.dag.executor.Executor` changes when scheduling or observation
semantics change; this module changes when the public ``run()`` API grows. It
validates the run's knobs (``_validate_concurrency``), builds the per-run
:class:`~url4.dag.ExecutionContext` (``_run_context`` — the composition root
that owns the default ``HttpIOLayer``, imported lazily so the static import
graph names no transport), mints the observation bookkeeping
(``_start_observation`` / ``_finish_observation`` / ``_expression_hash``), and
delegates to ``_wire_spawn`` (which stays in :mod:`url4.dag.executor` because
it builds executors). ``url4.dag`` re-exports :func:`run` unchanged, so no
public import path moves.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from typing import Literal, cast

from url4.core.nodes import Node as AstNode
from url4.io.layer import IOLayer
from url4.observe import Observer, RunFinished, RunStarted

from url4.dag._context import _ObsState  # isort: skip
from url4.dag.compiler import Graph, LoweringRegistry, compile_expression  # isort: skip
from url4.dag.executor import Executor, _wire_spawn  # isort: skip
from url4.dag.node import (  # isort: skip
    DEFAULT_RUN_CONCURRENCY,
    BoundedIOLayer,
    DagNode,
    ExecutionContext,
    ProcessFn,
    default_process,
)


def _validate_concurrency(concurrency: int | None) -> None:
    """Reject a run-wide I/O cap that can't be honored — before any allocation.

    The surface ``;iteration.concurrency`` syntax rejects ``n < 1`` with a
    ParseError; :func:`run`'s programmatic ``concurrency`` kwarg must do the
    same, and BEFORE :class:`BoundedIOLayer` builds an :class:`asyncio.Semaphore`.
    A ``Semaphore(0)`` can never be acquired, so every fetch would hang forever
    (no error, no timeout, and ``run``'s try/finally would never close the owned
    client). A non-int is rejected too so a bad upstream config value surfaces
    here, not as a raw asyncio TypeError at first-fetch time. ``None`` opts out.
    ``bool`` is an ``int`` subclass, so ``True`` (1) is accepted and ``False``
    (0) is rejected — the latter would otherwise hang.
    """
    if concurrency is None:
        return
    if not isinstance(concurrency, int):
        raise TypeError(
            f"run(): `concurrency` must be an int or None (None opts out of the "
            f"run-wide I/O cap); got {type(concurrency).__name__}={concurrency!r}"
        )
    if concurrency < 1:
        raise ValueError(
            "run(): `concurrency` must be >= 1, or None to opt out of the "
            f"run-wide I/O cap; got {concurrency!r}"
        )


def _to_node(target: str | AstNode | Graph | DagNode, registry: LoweringRegistry | None) -> DagNode:
    if isinstance(target, Graph):
        return target.sink
    if isinstance(target, DagNode):  # parse-tree nodes have no resolve → fall through
        return target
    return compile_expression(cast("str | AstNode", target), registry=registry).sink


async def run(
    target: str | AstNode | Graph | DagNode,
    io: IOLayer | None = None,
    *,
    processor: str | None = None,
    process: ProcessFn = default_process,
    registry: LoweringRegistry | None = None,
    ctx: ExecutionContext | None = None,
    concurrency: int | None = DEFAULT_RUN_CONCURRENCY,
    strict_fields: bool = False,
    observer: Observer | None = None,
    trace_id: str | None = None,
    root_span_id: str | None = None,
) -> str:
    """Evaluate a url4 expression (text, parse tree, graph, or node) to a string.

    ``io`` is the :class:`~url4.io.layer.IOLayer` performing fetches and backend
    calls; it defaults to a batteries-included :class:`~url4.io.http.HttpIOLayer`
    (httpx GET). Pass a :class:`~url4.io.static.StaticIOLayer` for deterministic,
    network-free runs. Pass an explicit ``ctx`` instead to inspect per-run state
    afterwards (e.g. ``ctx.collected_errors``).

    ``processor`` is the route a fan-out reduce dispatches to. Unset, it
    resolves to the io world's first declared route
    (:class:`~url4.io.layer.SupportsDefaultRoute`) — the core hardcodes no
    route names; with neither, a reduce raises a clear
    :class:`~url4.core.errors.ResolutionError`.

    When ``ctx`` is supplied, ``io``/``processor``/``process`` must be left at
    their defaults — the ctx already carries them, and combining both is
    ambiguous (see the ``ValueError`` below). Execution runs on a *child* of the
    supplied ``ctx`` (fresh ``spawn`` wiring, shared scope/io/error-tally/process
    hook), so ``ctx`` itself is never mutated: it is safe to hold on to the same
    ``ExecutionContext`` and pass it to overlapping concurrent ``run()`` calls
    (each gets its own ``spawn`` closure/registry on its own child), and
    ``ctx.collected_errors`` still totals every run's captured row errors
    (they share one error tally by construction).

    ``concurrency`` bounds how many ``ctx.io.fetch`` calls this run (including
    every fragment it spawns) may have in flight at once — the run-wide
    admission-control gate that a bare fan-out group, a fan-out+reduce, and the
    aggregate of a collection's rows would otherwise have no cap on at all
    (per-map ``;iteration.concurrency`` only tightens *within* one map, it does
    not bound the whole run). Defaults to :data:`DEFAULT_RUN_CONCURRENCY`; pass
    ``None`` to opt out and run fully unbounded (the pre-existing behavior),
    e.g. if the ``IOLayer`` already enforces its own limit.

    ``strict_fields`` selects the spec §5.3.4.1 field-path error mode: the
    default (False) is the lenient LLM mode — a missing field / bad index
    substitutes ``""``; True is the strict RDS mode — it raises
    :class:`~url4.core.errors.ScopeError` with code ``malformed_source``. With a
    supplied ``ctx``, ``strict_fields=True`` tightens the run; the ctx's own
    mode otherwise applies.

    ``observer``, when given, receives one :class:`~url4.observe.RunStarted`,
    one :class:`~url4.observe.NodeStarted`/:class:`~url4.observe.NodeFinished`
    pair per node evaluation, and one :class:`~url4.observe.RunFinished` for
    this run — minted once, here, for the top-level run only (every fragment
    this run spawns shares the same observer via ``ExecutionContext.child``).
    ``on_event`` is called synchronously and inline; an observer that raises
    fails the run with that exact exception (nothing here catches it).

    ``trace_id``/``root_span_id`` let a caller (e.g. a hosting service that
    already minted its own run-root identity) pin the ids :class:`~url4.observe.RunStarted`
    carries and the top-level node's ``parent_span_id`` resolves to, instead of
    the engine minting fresh ones. Only meaningful together with ``observer``;
    ignored (no-op) when ``observer`` is ``None``, since no ids are ever minted
    or emitted in that case.
    """
    if ctx is not None and (
        io is not None or processor is not None or process is not default_process
    ):
        raise ValueError(
            "run(): pass either `ctx` or `io`/`processor`/`process`, not both — "
            "a supplied `ctx` already carries its own io/processor/process, so "
            "the other kwargs would be silently ignored"
        )
    _validate_concurrency(concurrency)
    run_ctx, owned_io = _run_context(io, ctx, processor, process, strict_fields)
    if concurrency is not None:
        # Wraps only run_ctx's (private, freshly-built-or-childed) io reference,
        # never the caller-supplied ctx.io directly — same non-mutation
        # discipline as the spawn wiring above. Every node in this run, and
        # every fragment it spawns, shares this one bounded wrapper via
        # ExecutionContext.child, so the cap is truly run-wide.
        run_ctx.io = BoundedIOLayer(run_ctx.io, concurrency)
    obs = _start_observation(run_ctx, observer, target, trace_id, root_span_id)
    _wire_spawn(run_ctx, registry)
    try:
        result = await Executor(run_ctx).execute(_to_node(target, registry))
    except BaseException as exc:
        status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "error"
        _finish_observation(obs, status)
        raise
    else:
        _finish_observation(obs, "ok")
        return result
    finally:
        if owned_io is not None:
            await owned_io.aclose()


def _start_observation(
    run_ctx: ExecutionContext,
    observer: Observer | None,
    target: str | AstNode | Graph | DagNode,
    trace_id: str | None = None,
    root_span_id: str | None = None,
) -> _ObsState | None:
    """Mint the run's ``_ObsState``, wire it onto ``run_ctx``, and emit
    :class:`~url4.observe.RunStarted` — once, here, for the top-level owned
    run only. ``None`` (a no-op run) when no ``observer`` was passed.

    ``trace_id``/``root_span_id``, when supplied, are used verbatim instead of
    minting fresh ones — letting a caller's own run-root identity (e.g. a
    hosting service's ``publish.run``) agree with the engine's."""
    if observer is None:
        return None
    obs = _ObsState(observer, trace_id if trace_id is not None else secrets.token_hex(16))
    run_ctx._obs = obs
    run_ctx._current_span_id = root_span_id if root_span_id is not None else secrets.token_hex(8)
    obs.emit(RunStarted(obs.trace_id, run_ctx._current_span_id, _expression_hash(target)))
    return obs


def _finish_observation(obs: _ObsState | None, status: Literal["ok", "error", "cancelled"]) -> None:
    """Emit :class:`~url4.observe.RunFinished`; a no-op when ``obs`` is ``None``."""
    if obs is not None:
        obs.emit(RunFinished(status, obs.next_seq()))


def _expression_hash(target: str | AstNode | Graph | DagNode) -> str:
    """A short, deterministic fingerprint of ``target`` for
    :class:`~url4.observe.RunStarted` — identifies "which expression" without
    carrying (and potentially leaking) the full source text through the
    observation stream.

    A raw hand-built :class:`DagNode` has no engine-guaranteed ``__repr__`` —
    the default object repr is id-based and differs run to run, which would
    break the "deterministic" contract above. ``str``/``AstNode``/``Graph``
    targets stringify structurally (source text / a dataclass repr), so only
    the ``DagNode`` fallback needs the type-name-only fingerprint.
    """
    if isinstance(target, (str, AstNode, Graph)):
        fingerprint = str(target)
    else:
        fingerprint = type(target).__name__
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]


def _run_context(
    io: IOLayer | None,
    ctx: ExecutionContext | None,
    processor: str | None,
    process: ProcessFn,
    strict_fields: bool,
):
    """The per-run context + the owned adapter to close (None when injected).

    With no ``ctx``, a fresh context is built (defaulting ``io`` to an owned
    HttpIOLayer). A supplied ``ctx`` yields a *child*, never ``ctx`` itself:
    ``_wire_spawn`` mutates whatever it's given, and ctx may be shared across
    overlapping run() calls — mutating it in place would let a second call's
    spawn wiring silently replace the first's, a logical race across the two
    runs' await points. child() shares scope/io/error-tally/process, so
    ``ctx.collected_errors`` still totals correctly. ``strict_fields`` is
    tighten-only on a supplied ctx: a run may opt INTO strictness, never out.
    """
    if ctx is not None:
        run_ctx = ctx.child(ctx.scope)
        if strict_fields:
            run_ctx.strict_fields = True
        return run_ctx, None
    owned_io = None
    if io is None:
        # Composition-root default: imported lazily so the execution core's
        # static import graph never references a concrete transport (httpx).
        from url4.io.http import HttpIOLayer

        io = owned_io = HttpIOLayer()
    run_ctx = ExecutionContext(
        io, processor=processor, process=process, strict_fields=strict_fields
    )
    return run_ctx, owned_io


__all__ = ["run"]
