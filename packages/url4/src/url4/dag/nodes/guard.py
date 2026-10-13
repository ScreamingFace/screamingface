"""The per-source execution disposition: retries, timeouts, tolerated failure."""

from __future__ import annotations

import asyncio
import contextvars
import random
from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.core._annotations import checked_retries, checked_timeout
from url4.core.context import Context
from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.dag._context import IO_ADMISSION, IoAdmission
from url4.io.idempotency import IDEMPOTENCY_SCOPE, IdempotencyScope

from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
    SourceFailure,
)

from url4.dag.nodes._shared import _frame  # isort: skip

# Spec C §13.3 backoff: attempt k waits min(500 ms * 2^(k-1) + random(0, 500 ms), 30 s).
_BACKOFF_BASE_S = 0.5
_BACKOFF_JITTER_S = 0.5
_BACKOFF_CAP_S = 30.0

# Seams, so tests neither wait the backoff out nor depend on the global random state.
_sleep = asyncio.sleep
_jitter = random.uniform


def _backoff_delay(attempt: int) -> float:
    """The wait before retry ``attempt`` (1-based), per Spec C §13.3."""
    delay = _BACKOFF_BASE_S * 2 ** (attempt - 1) + _jitter(0, _BACKOFF_JITTER_S)
    return min(delay, _BACKOFF_CAP_S)


def _retry_wait(attempt: int, error: Url4Error) -> float:
    """The backoff, raised to the source's ``Retry-After`` when it asked for more (§14.3)."""
    retry_after = error.retry_after if isinstance(error, ResolutionError) else None
    return max(_backoff_delay(attempt), retry_after or 0.0)


def _time_left(deadline: asyncio.Timeout | None) -> float:
    """Seconds until ``deadline`` fires (infinite without one)."""
    when = None if deadline is None else deadline.when()
    return float("inf") if when is None else when - asyncio.get_running_loop().time()


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


# INVARIANT: bound only around one retry's run of the subtree (`_send`; never the backoff wait),
# and reset after it, so it is visible to the guarded subtree (whose tasks copy this context) and
# to nothing else. A first send binds nothing, so it reads exactly like unguarded code —
# including inside an OUTER guard's retry, which stays visible to a nested guard's first send
# (it is still a re-send of that subtree).
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

    Retry and timeout follow Spec C §13.3. ``retries`` is the number of EXTRA
    attempts; only a transient :class:`~url4.core.errors.Url4Error` (``permanent``
    false) is retried, after an exponential backoff with jitter that a source's
    ``Retry-After`` can lengthen (§14.3); a permanent one raises at once, and so
    does any exception that is not a ``Url4Error`` (an adapter bug is not a
    transient condition). ``timeout`` (``;t=``) is CUMULATIVE: one deadline covers
    every attempt, every backoff wait and the wait for the run-wide I/O permit, and
    its expiry ends the source — a timed-out attempt is never retried, and a retry
    whose wait would outlast the deadline is not started (the last real error is
    raised instead). A timeout is a *non-result*: the request may have applied its
    effect before the wait stopped.

    Retried effects ("reuse until answered", :mod:`url4.io.idempotency`): inside
    one guarded resolve each target has an idempotency key, which the HTTP adapter
    sends as ``Idempotency-Key``. A retry re-sends a target with the SAME key while
    no reply came back for it (timeout, network error, lost response), so the
    remote can deduplicate; once a reply arrived, the next request to that target
    gets a NEW key, so resampling a malformed reply stays possible. Deduplicating
    is the remote's choice (Spec C §15), so a guarded effect must still be
    idempotent — and url4's own server does not deduplicate on the key yet, so a
    url4→url4 hop is not protected. Known limit: under ``;optional`` an effect that
    was applied but whose source then failed is dropped like any other failure.

    A source that still fails is terminal — ``required`` (default) raises,
    ``optional`` returns a :class:`~url4.dag.node.SourceFailure` value for the
    group to tolerate.
    """

    inner: DagNode
    optional: bool = False
    timeout: float | None = None
    retries: int = 0
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # $ref edges only

    def __post_init__(self) -> None:
        # The one range rule the builders and the lowering share (report C3): a
        # negative count would skip every attempt, `nan` would never fire.
        checked_retries(self.retries)
        if self.timeout is not None:
            checked_timeout(self.timeout)

    def children(self) -> list[DagNode]:
        """``inner`` is an attribute, not an edge — declare it so the structural
        traversals (cycle detection, :meth:`Graph.walk`) still see through the
        isolation boundary. See :func:`~url4.dag.node.node_children`."""
        return [*self.deps.values(), self.inner]

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        scope = _frame(inputs, ctx)
        # One key scope per guarded resolve; a nested guard keeps its outer one, so an
        # outer retry re-sends the inner requests with the same keys.
        fresh = self.retries > 0 and IDEMPOTENCY_SCOPE.get() is None
        token = IDEMPOTENCY_SCOPE.set(IdempotencyScope()) if fresh else None
        try:
            return await self._within_deadline(scope, ctx)
        except Exception as exc:  # control-flow signals (CancelledError) propagate
            if not self.optional:
                raise
            code = exc.code if isinstance(exc, Url4Error) else ErrorCode.RESOLUTION_FAILED
            return SourceFailure(code, str(exc) or type(exc).__name__)
        finally:
            if token is not None:
                IDEMPOTENCY_SCOPE.reset(token)

    async def _within_deadline(self, scope: Context, ctx: ExecutionContext) -> Payload:
        if self.timeout is None:
            return await self._attempts(scope, ctx, None)
        probe = IoAdmission(IO_ADMISSION.get())
        token = IO_ADMISSION.set(probe)
        deadline = asyncio.timeout(self.timeout)
        try:
            async with deadline:
                return await self._attempts(scope, ctx, deadline)
        except TimeoutError as exc:
            if not deadline.expired():
                raise  # the inner node's own TimeoutError, not this deadline
            raise self._timeout_error(probe) from exc
        finally:
            IO_ADMISSION.reset(token)

    def _timeout_error(self, probe: IoAdmission) -> ResolutionError:
        if probe.starved:
            return ResolutionError(
                f"source timed out after {self.timeout:g}s (;t=) waiting for an I/O permit "
                "(the run's concurrency cap); no request was sent",
                code=ErrorCode.ADMISSION_TIMEOUT,
            )
        return ResolutionError(
            f"source timed out after {self.timeout:g}s (;t=)", code=ErrorCode.TIMEOUT
        )

    async def _attempts(
        self, scope: Context, ctx: ExecutionContext, deadline: asyncio.Timeout | None
    ) -> Payload:
        attempt = 0
        last: Url4Error | None = None
        while True:
            try:
                return await self._send(scope, ctx, attempt, last)
            except Url4Error as exc:
                if exc.permanent or attempt == self.retries:
                    raise
                attempt += 1
                last = exc
                wait = _retry_wait(attempt, exc)
                if wait >= _time_left(deadline):
                    raise  # `;t=` ends during the wait: report the real failure, not a timeout
            await _sleep(wait)

    async def _send(
        self, scope: Context, ctx: ExecutionContext, attempt: int, last: Url4Error | None
    ) -> Payload:
        """Run the subtree once; a retry runs it with its GuardRetry published (see there)."""
        if last is None:
            return await ctx.execute_node(self.inner, scope)
        token: contextvars.Token[GuardRetry | None] = _current_retry.set(
            GuardRetry(attempt, last.code)
        )
        try:
            return await ctx.execute_node(self.inner, scope)
        finally:
            _current_retry.reset(token)
