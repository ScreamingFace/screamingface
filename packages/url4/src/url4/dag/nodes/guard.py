"""The per-source execution disposition: retries, timeouts, tolerated failure."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.core.context import Context
from url4.core.errors import ErrorCode, ResolutionError, Url4Error

from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
    SourceFailure,
)

from url4.dag.nodes._shared import _frame  # isort: skip


@dataclass(eq=False)
class GuardNode:
    """The per-source execution disposition (spec §10.1): retry, timeout, optional.

    ``inner`` is deliberately an *attribute*, not a dependency edge. A
    dependency's exception propagates through the run's shared TaskGroup and
    cancels every sibling before this node could catch it — so the guarded
    subtree executes via ``ctx.execute_node`` on an isolated sub-executor
    (its own TaskGroup), the same containment boundary ``spawn`` gives lazy
    fragments. The cost is a separate memo for the subtree; the compiler keeps
    shared bindings OUT of the subtree (they flow in as this node's reference
    edges → scope frame), so diamond deps still resolve exactly once.

    Failure handling: a permanent error (``Url4Error.permanent``) never
    retries; a transient one retries up to ``retries`` extra attempts; a
    timeout (``;t=``) is transient. A timeout is a *non-result*, not a negative
    one: the guarded effect may have completed already before the wait stopped,
    so a retry can apply it twice. Guarded effects must therefore be idempotent.
    A source that still fails is terminal — ``required`` (default) raises,
    ``optional`` returns a :class:`~url4.dag.node.SourceFailure` value for the
    group to tolerate.
    """

    inner: DagNode
    optional: bool = False
    timeout: float | None = None
    retries: int = 0
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # $ref edges only

    def children(self) -> list[DagNode]:
        """``inner`` is an attribute, not an edge — declare it so the structural
        traversals (cycle detection, :meth:`Graph.walk`) still see through the
        isolation boundary. See :func:`~url4.dag.node.node_children`."""
        return [*self.deps.values(), self.inner]

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        scope = _frame(inputs, ctx)
        try:
            return await self._attempt(scope, ctx)
        except Exception as exc:  # control-flow signals (CancelledError) propagate
            if not self.optional:
                raise
            code = exc.code if isinstance(exc, Url4Error) else ErrorCode.RESOLUTION_FAILED
            return SourceFailure(code, str(exc) or type(exc).__name__)

    async def _attempt(self, scope: Context, ctx: ExecutionContext) -> Payload:
        last: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                return await self._once(scope, ctx)
            except Url4Error as exc:
                if exc.permanent:
                    raise
                last = exc
        assert last is not None  # the loop always runs at least once
        raise last

    async def _once(self, scope: Context, ctx: ExecutionContext) -> Payload:
        if self.timeout is None:
            return await ctx.execute_node(self.inner, scope)
        try:
            async with asyncio.timeout(self.timeout):
                return await ctx.execute_node(self.inner, scope)
        except TimeoutError as exc:
            raise ResolutionError(
                f"source timed out after {self.timeout:g}s (;t=)", code=ErrorCode.TIMEOUT
            ) from exc
