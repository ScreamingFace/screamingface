"""OME-1026 — app-lifetime background refresh for discovery snapshots.

FEATURE: stale-while-revalidate. A user-facing request waits at most its own
budget; the refresh it triggered runs to completion in the background, so a later
request observes a real snapshot instead of dialing again.

INVARIANT (why this class exists): ``ObservationCache.get_or_refresh`` awaits its
refresh callable while HOLDING the single-flight lock. Bounding that with
``asyncio.wait_for(..., 3)`` would cancel the winner mid-flight — no failure
recorded, the lock released, and the next arrival dialing a second time. One
upstream attempt becomes N under exactly the slow-upstream conditions that caused
the timeout. So the WAIT and the WORK must be separable objects: this manager owns
the work, and callers wait on it with their own budget.

INVARIANT (dedup by identity): one in-flight refresh per key. Callers arriving
while one runs JOIN it rather than starting another.

INVARIANT (bounded): the in-flight map has a hard capacity. At capacity a NEW key
is refused (``None``) rather than admitted — the caller then serves stale or seeds,
which is already the documented answer for a slow refresh. Refusing keeps a
per-profile map from becoming an unbounded, remotely-triggerable allocation.

INVARIANT (loud on bugs): a ``DiscoveryError`` is a normal failed attempt. Anything
else — ``AssertionError`` from the suite's no-egress tripwire above all — is a
programming error: it is reported through ``on_error`` and re-raised to whoever
awaits the task, never folded into "discovery degraded". The default ``on_error``
is :func:`aigateway.core.background_error_sink.record_unexpected`, which retains a
sanitized record until something observes it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .background_error_sink import record_unexpected, safe_background_key
from .parameter_discovery import DiscoveryError

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Hashable

logger = logging.getLogger(__name__)

# WHY 3.0 (F5): mirrors the default of ``AIGW_DISCOVERY_TIMEOUT_SECONDS`` — the time
# one discovery step may take — rather than inventing a second notion of "too long".
# Callers that know the configured value pass it in.
_DEFAULT_SHUTDOWN_TIMEOUT_S = 3.0


class BackgroundRefreshManager[KeyT: Hashable]:
    """Deduplicated, shielded, bounded background refreshes keyed by cache identity.

    # WHY generic over the key: the private catalog's identity is the TUPLE
    # ``(account_id, provider, profile_name, credential_revision)``. Joining those
    # into a string would make a user-supplied profile name able to alias a sibling
    # identity through the separator, and it would turn "cancel this profile's
    # refresh" into prefix matching. Tuple equality has neither failure mode.
    """

    def __init__(
        self,
        *,
        max_inflight: int,
        on_error: Callable[[KeyT, BaseException], None] | None = None,
        shutdown_timeout_s: float = _DEFAULT_SHUTDOWN_TIMEOUT_S,
    ) -> None:
        if max_inflight <= 0:
            raise ValueError("max_inflight must be positive")
        self._max_inflight = max_inflight
        self._shutdown_timeout_s = shutdown_timeout_s
        self._on_error = on_error if on_error is not None else record_unexpected
        # INVARIANT: this dict is the STRONG reference set. asyncio only holds a weak
        # reference to a running task, so a bare ``create_task`` result can be garbage
        # collected mid-flight — the refresh would then vanish silently and the "a later
        # request sees the snapshot" guarantee would hold only by luck.
        self._tasks: dict[KeyT, asyncio.Task[Any]] = {}
        # Superseded tasks: cancelled and no longer dedup candidates, but still
        # STRONGLY referenced until they finish unwinding. Dropping the reference at
        # cancel time would let the loop garbage-collect a task mid-cancellation, so
        # its ``finally`` cleanup (an open discovery socket) might never run.
        self._superseded: set[asyncio.Task[Any]] = set()
        self._closed = False

    @property
    def inflight(self) -> int:
        """Every LIVE task: joinable, or superseded and still unwinding.

        # INVARIANT (F5): a superseded task is cancelled but NOT finished — provider
        # cleanup code may absorb the cancellation and keep running. Counting only
        # ``_tasks`` let repeated credential rotation start an unbounded number of live
        # tasks while this gauge read zero. ``done()`` is the honest liveness test: a
        # task that has finished occupies nothing, whichever map still holds it until
        # its done-callback runs.
        """
        return sum(1 for task in self._pending_tasks() if not task.done())

    def tracked_keys(self) -> tuple[KeyT, ...]:
        return tuple(self._tasks)

    def start_or_join(
        self, key: KeyT, factory: Callable[[], Coroutine[Any, Any, Any]]
    ) -> asyncio.Task[Any] | None:
        """The task refreshing ``key``: an existing one, a new one, or ``None``.

        ``None`` means "not started" — the manager is closed, or it is at capacity
        with no slot to reclaim. The caller must treat that as a normal degraded
        outcome (serve stale, else seeds), never as an error.

        # AIDEV-NOTE: deliberately SYNCHRONOUS. There is no ``await`` between the
        # lookup and the insert, so asyncio's single-threaded loop cannot interleave a
        # second caller in between — the dedup needs no lock of its own. Adding an
        # await here would reintroduce the double-dial race this class exists to close.
        """
        if self._closed:
            return None
        existing = self._tasks.get(key)
        if existing is not None and not existing.done():
            return existing
        live = self.inflight
        if existing is None and live >= self._max_inflight:
            # Only a NEW key consumes capacity; joining an existing one never does.
            # INVARIANT (F5): the bound is on LIVE tasks, superseded ones included.
            # Otherwise each rotation could add a cancellation-resistant task that no
            # longer counted, and the hard cap would bound nothing.
            logger.info(
                "background discovery refresh refused (at capacity) key=%s inflight=%d",
                safe_background_key(key),
                live,
            )
            return None
        task = asyncio.get_running_loop().create_task(factory())
        self._tasks[key] = task
        task.add_done_callback(lambda finished: self._reap(key, finished))
        return task

    def cancel(self, key: KeyT) -> bool:
        """Supersede the refresh for ``key``; ``True`` if one was actually cancelled.

        Called when the credential behind an identity is replaced, its owner changes,
        or the profile is deleted: the in-flight task holds an auth context built from
        the PREVIOUS credential, so its answer describes an owner who no longer holds
        the profile.

        # INVARIANT (why the key is dropped here and not left to ``_reap``):
        # ``Task.cancel()`` does not make a task ``done()`` — the coroutine observes the
        # cancellation only on a later loop pass. Leaving the key in ``_tasks`` would let
        # the next caller JOIN the doomed task and wait out its whole budget for a result
        # that can never arrive. ``_reap`` is idempotent about this: it deletes only when
        # the stored task is still the one that finished, so it cannot remove a
        # replacement started in the meantime.
        """
        task = self._tasks.get(key)
        if task is None or task.done():
            return False
        del self._tasks[key]
        self._superseded.add(task)
        task.cancel()
        return True

    async def wait_up_to(self, task: asyncio.Task[Any], *, timeout: float) -> bool:
        """Wait at most ``timeout`` for ``task``. Returns whether it finished.

        # WHY ``asyncio.wait`` and not ``wait_for``/``shield``: ``asyncio.wait`` never
        # cancels what it waits on, and cancelling THIS coroutine (a disconnected
        # client) propagates to the wait, not to the task. ``wait_for`` would cancel
        # the task on timeout — the exact failure mode this class exists to prevent.
        # INVARIANT: this method never raises the task's exception. The caller decides
        # how to treat a failed refresh; it inspects the task itself.
        """
        if task.done():
            return True
        await asyncio.wait({task}, timeout=timeout)
        return task.done()

    def pending_tasks(self) -> tuple[asyncio.Task[Any], ...]:
        """Every task this manager still holds a STRONG reference to.

        Tracked AND superseded: a cancelled task still needs awaiting so its own
        cleanup runs before the process moves on. Public because it is the honest
        answer to "what is this manager still responsible for", which shutdown
        accounting is asserted against (adversarial B4).
        """
        return (*self._tasks.values(), *self._superseded)

    # The original private name, kept because ``inflight`` and ``drain`` read it and
    # several tests in this unit were written against it.
    _pending_tasks = pending_tasks

    def _reap(self, key: KeyT, task: asyncio.Task[Any]) -> None:
        # Drop the slot first: a finished task must never keep capacity occupied, even
        # if the reporting below raises.
        if self._tasks.get(key) is task:
            del self._tasks[key]
        self._superseded.discard(task)
        if task.cancelled():
            # Shutdown, or a deliberate supersede. Not a failure to report.
            return
        exc = task.exception()
        if exc is None or isinstance(exc, DiscoveryError):
            # ``exception()`` also marks the result retrieved, so a normal failed
            # attempt does not surface as "exception was never retrieved".
            return
        self._on_error(key, exc)

    async def drain(self) -> None:
        """Await every in-flight refresh WITHOUT cancelling any.

        # WHY the trailing yield: ``gather`` resumes as soon as the tasks finish, but
        # each task's done-callback — which frees its slot — is scheduled with
        # ``call_soon``. Without one more loop pass, a caller that drained would still
        # observe the slots as occupied.
        """
        pending = [task for task in self._pending_tasks() if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.sleep(0)

    async def aclose(self) -> None:
        """Cancel every unfinished refresh and AWAIT it.

        # WHY await after cancelling: a cancelled-but-unawaited task emits
        # "Task was destroyed but it is pending!" and — worse — its own ``finally``
        # cleanup may never run, so the discovery transport's socket would leak across
        # a reload or a TestClient lifecycle.
        """
        self._closed = True
        pending = [task for task in self.pending_tasks() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            # INVARIANT (F5): BOUNDED. An unbounded gather here let one provider that
            # absorbs cancellation hang process shutdown — and a TestClient teardown —
            # forever. Giving up is the lesser evil: the alternative is never exiting.
            _done, alive = await asyncio.wait(pending, timeout=self._shutdown_timeout_s)
            if alive:
                logger.warning(
                    "background discovery refresh shutdown gave up on %d unfinished task(s)",
                    len(alive),
                )
        self._release_finished()

    def _release_finished(self) -> None:
        """Drop every FINISHED task; keep every live one strongly referenced.

        # INVARIANT (adversarial B4): ``aclose`` used to clear both maps outright. A
        # provider that absorbs cancellation is then still running while ``inflight``
        # reads 0 and the tracked set is empty — the manager's own accounting claiming
        # work died that is still holding a discovery socket, and the task itself
        # garbage-collectable mid-flight (asyncio keeps only a weak reference), which
        # is what produces "Task was destroyed but it is pending!".
        # WHY it is safe to keep them: ``_closed`` already refuses new work, and each
        # task's done-callback (``_reap``) removes it the moment it really finishes, so
        # holding on is bounded by the task's own lifetime rather than by this method.
        """
        for key, task in list(self._tasks.items()):
            if task.done():
                del self._tasks[key]
        self._superseded = {task for task in self._superseded if not task.done()}
