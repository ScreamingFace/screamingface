"""The per-source execution disposition: retries, timeouts, tolerated failure."""

from __future__ import annotations

import asyncio
import contextvars
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


@dataclass(frozen=True, slots=True)
class GuardRetry:
    """This run of a guarded subtree is a retry: which one, and the failure that caused it.

    Think of it as the "second notice" stamp on a re-sent letter, naming why the first one
    bounced. A ``;retry=`` re-runs the guarded subtree with nothing changed, so this is the ONLY
    way code inside it can tell a retry from the first send — and a retry after one kind of
    failure from a retry after another. url4 says what happened; what a retry should do
    differently is the reader's business (the guard knows nothing about caches or models).

    Worked example: ``;retry=2`` whose first send fails ``judge_reply_invalid`` and first retry
    fails ``upstream_error`` runs the subtree under: nothing (the first send),
    ``GuardRetry(1, "judge_reply_invalid")``, ``GuardRetry(2, "upstream_error")``.

    Args (as fields):
        number: 1 for the first retry, k for the k-th.
        failure_code: the ``Url4Error.code`` of the failure that ended the send before this one.
    """

    number: int
    failure_code: str


# INVARIANT: bound only around one retry's `_once`, and reset after it, so it is visible to the
# guarded subtree (whose tasks copy this context) and to nothing else. A first send binds
# nothing, so it reads exactly like unguarded code — including inside an OUTER guard's retry,
# which stays visible to a nested guard's first send (it is still a re-send of that subtree).
_current_retry: contextvars.ContextVar[GuardRetry | None] = contextvars.ContextVar(
    "url4_guard_retry", default=None
)


def current_guard_retry() -> GuardRetry | None:
    """The retry this code runs under, or None on a first send and outside any guard.

    Nearest wins: a nested guard's own retry replaces an outer one for its subtree, because the
    nested guard is the one re-running it and its failure is the one that caused the re-run.
    """
    return _current_retry.get()


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
        last: Url4Error | None = None
        for number in range(self.retries + 1):
            try:
                return await self._send(scope, ctx, number, last)
            except Url4Error as exc:
                if exc.permanent:
                    raise
                last = exc
        assert last is not None  # the loop always runs at least once
        raise last

    async def _send(
        self, scope: Context, ctx: ExecutionContext, number: int, last: Url4Error | None
    ) -> Payload:
        """Run the subtree once; a retry runs it with its GuardRetry published (see there)."""
        if last is None:
            return await self._once(scope, ctx)
        token: contextvars.Token[GuardRetry | None] = _current_retry.set(
            GuardRetry(number, last.code)
        )
        try:
            return await self._once(scope, ctx)
        finally:
            _current_retry.reset(token)

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
