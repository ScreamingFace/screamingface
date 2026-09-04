"""OME-1026 rework U2 — the app-lifetime background refresh manager.

FEATURE: stale-while-revalidate for discovery. A user-facing request waits at
most its own budget; the refresh it triggered keeps running to completion so a
later request observes a real snapshot.

STORY: as a user opening the model picker I see something immediately — live,
stale, or seeds — and the list is live by the time I look again.

INVARIANT (why this exists at all): ``ObservationCache.get_or_refresh`` awaits
its refresh while HOLDING the single-flight lock. Wrapping that in
``asyncio.wait_for(..., 3)`` would cancel the winner mid-flight, recording no
failure and leaving the next caller to dial again — turning one upstream attempt
into N. The wait and the work must be separable, which is what this manager
provides.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from aigateway.core.background_error_sink import mark_observed
from aigateway.core.background_refresh import BackgroundRefreshManager
from aigateway.core.parameter_discovery import DiscoveryError


@pytest_asyncio.fixture
async def manager():
    mgr = BackgroundRefreshManager(max_inflight=8)
    try:
        yield mgr
    finally:
        await mgr.aclose()


# ── deduplication by identity ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_callers_for_one_key_share_a_single_refresh(manager) -> None:
    """INVARIANT: one upstream attempt per identity, however many callers arrive."""
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def _refresh() -> str:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return "snapshot"

    handles = [manager.start_or_join("acct:anthropic:work", _refresh) for _ in range(5)]
    await started.wait()

    assert calls == 1, "five callers must cause ONE refresh"
    assert len({id(h) for h in handles}) == 1, "and share one task handle"

    release.set()
    assert await handles[0] == "snapshot"


@pytest.mark.asyncio
async def test_distinct_keys_refresh_independently(manager) -> None:
    release = asyncio.Event()
    seen: list[str] = []

    def _make(name: str):
        async def _refresh() -> str:
            seen.append(name)
            await release.wait()
            return name

        return _refresh

    a = manager.start_or_join("acct-a:anthropic:work", _make("a"))
    b = manager.start_or_join("acct-b:anthropic:work", _make("b"))
    await asyncio.sleep(0)

    assert a is not b
    release.set()
    assert {await a, await b} == {"a", "b"}
    assert sorted(seen) == ["a", "b"]


@pytest.mark.asyncio
async def test_a_completed_key_is_refreshed_again_on_the_next_request(manager) -> None:
    """Dedup must not become permanent memoization — the cache decides freshness."""
    calls = 0

    async def _refresh() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert await manager.start_or_join("k", _refresh) == 1
    assert await manager.start_or_join("k", _refresh) == 2


# ── the wait is separable from the work (the core requirement) ─────────────────


@pytest.mark.asyncio
async def test_a_timed_out_wait_leaves_the_refresh_running_to_completion(manager) -> None:
    """INVARIANT: the 3 s budget bounds the WAIT, never the work.

    # WHY this is the whole point: the user gets stale-or-seeds now, and the very
    # next request finds a real snapshot — because nothing cancelled the winner.
    """
    release = asyncio.Event()
    finished = asyncio.Event()

    async def _refresh() -> str:
        await release.wait()
        finished.set()
        return "late-snapshot"

    task = manager.start_or_join("k", _refresh)
    completed = await manager.wait_up_to(task, timeout=0.01)

    assert completed is False, "the wait must give up"
    assert not task.done(), "but the refresh must still be running"
    assert not task.cancelled()

    release.set()
    assert await task == "late-snapshot"
    assert finished.is_set()


@pytest.mark.asyncio
async def test_cancelling_the_waiting_request_does_not_cancel_the_shared_refresh(
    manager,
) -> None:
    """A client disconnect must not abort work other callers are waiting on."""
    release = asyncio.Event()

    async def _refresh() -> str:
        await release.wait()
        return "survived"

    task = manager.start_or_join("k", _refresh)

    waiter = asyncio.ensure_future(manager.wait_up_to(task, timeout=30))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert not task.done() and not task.cancelled()
    release.set()
    assert await task == "survived"


# ── failure handling: degrade on discovery errors, stay loud on bugs ──────────


@pytest.mark.asyncio
async def test_a_discovery_error_is_a_normal_failed_attempt(manager) -> None:
    async def _refresh() -> str:
        raise DiscoveryError("unreachable")

    task = manager.start_or_join("k", _refresh)
    assert await manager.wait_up_to(task, timeout=1) is True
    with pytest.raises(DiscoveryError):
        await task
    assert manager.inflight == 0, "a finished task must not leak a slot"


@pytest.mark.asyncio
async def test_an_assertion_error_is_never_absorbed_as_degradation(manager) -> None:
    """INVARIANT: the suite's no-egress tripwire raises AssertionError.

    # WHY it must survive: absorbing it would turn a forbidden real network dial
    # into a quiet "discovery degraded" outcome, and a test that genuinely reached
    # the internet would pass green.
    """

    async def _refresh() -> str:
        raise AssertionError("test attempted real discovery egress")

    task = manager.start_or_join("k", _refresh)
    await manager.wait_up_to(task, timeout=1)

    with pytest.raises(AssertionError, match="real discovery egress") as caught:
        await task
    # OME-1026 F6: awaiting the task IS observing it, but the manager's done-callback
    # retained the error first (callbacks run before an awaiting caller resumes). Say
    # so, exactly as ``_terminal_reason`` does on the production path — otherwise the
    # suite-wide teardown reports a bug this case deliberately asserted.
    mark_observed(caught.value)


@pytest.mark.asyncio
async def test_an_unexpected_programming_error_stays_observable(manager) -> None:
    """A bug must be reported, not silently indistinguishable from an outage."""
    observed: list[tuple[str, BaseException]] = []

    mgr = BackgroundRefreshManager[str](
        max_inflight=4, on_error=lambda key, exc: observed.append((key, exc))
    )
    try:

        async def _refresh() -> str:
            raise ZeroDivisionError("boom")

        task = mgr.start_or_join("k", _refresh)
        assert task is not None
        await mgr.wait_up_to(task, timeout=1)
        await asyncio.sleep(0)

        assert [k for k, _ in observed] == ["k"]
        assert isinstance(observed[0][1], ZeroDivisionError)
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_a_discovery_error_is_not_reported_as_a_programming_error(manager) -> None:
    observed: list[str] = []
    mgr = BackgroundRefreshManager[str](
        max_inflight=4, on_error=lambda key, _exc: observed.append(key)
    )
    try:

        async def _refresh() -> str:
            raise DiscoveryError("bad_status", status=503)

        task = mgr.start_or_join("k", _refresh)
        assert task is not None
        await mgr.wait_up_to(task, timeout=1)
        await asyncio.sleep(0)

        assert observed == [], "an expected discovery failure is not a bug report"
    finally:
        await mgr.aclose()


# ── boundedness ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_inflight_map_is_bounded_and_refuses_rather_than_growing() -> None:
    """INVARIANT: no unbounded per-profile task map.

    # WHY refuse instead of queue or evict: refusing degrades this ONE caller to
    # stale-or-seeds, which is already the documented answer when a refresh is slow.
    # Evicting a live task would abandon work another caller is awaiting, and queueing
    # would let an unbounded backlog accumulate under exactly the load that caused it.
    """
    mgr = BackgroundRefreshManager(max_inflight=2)
    release = asyncio.Event()

    async def _refresh() -> str:
        await release.wait()
        return "x"

    assert mgr.start_or_join("a", _refresh) is not None
    assert mgr.start_or_join("b", _refresh) is not None
    await asyncio.sleep(0)

    assert mgr.inflight == 2
    assert mgr.start_or_join("c", _refresh) is None, "at capacity: refuse, do not grow"

    # An already-tracked key still JOINS at capacity — it opens no new slot.
    assert mgr.start_or_join("a", _refresh) is not None

    release.set()
    await mgr.aclose()


@pytest.mark.asyncio
async def test_capacity_refusal_log_bounds_and_sanitizes_the_key(caplog) -> None:
    """INVARIANT: a refused user-derived identity cannot forge or flood a log line."""
    mgr = BackgroundRefreshManager(max_inflight=1)
    release = asyncio.Event()

    async def _refresh() -> str:
        await release.wait()
        return "x"

    try:
        assert mgr.start_or_join("occupied", _refresh) is not None
        await asyncio.sleep(0)
        caplog.set_level("INFO", logger="aigateway.core.background_refresh")
        hostile = "profile\n" + ("x" * 512) + "\rFORGED"

        assert mgr.start_or_join(hostile, _refresh) is None

        rendered = next(
            record.getMessage()
            for record in caplog.records
            if "refused (at capacity)" in record.getMessage()
        )
        assert "\n" not in rendered
        assert "\r" not in rendered
        assert "FORGED" not in rendered
    finally:
        release.set()
        await mgr.aclose()


@pytest.mark.asyncio
async def test_a_freed_slot_is_reusable(manager) -> None:
    mgr = BackgroundRefreshManager(max_inflight=1)
    try:

        async def _quick() -> str:
            return "done"

        first = mgr.start_or_join("a", _quick)
        assert first is not None
        assert await first == "done"
        await asyncio.sleep(0)
        assert mgr.inflight == 0
        second = mgr.start_or_join("b", _quick)
        assert second is not None
        assert await second == "done"
    finally:
        await mgr.aclose()


# ── shutdown ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shutdown_cancels_and_awaits_unfinished_refreshes() -> None:
    """INVARIANT: no task outlives the app, and shutdown does not race it.

    # WHY await after cancelling: a cancelled-but-unawaited task logs
    # "Task was destroyed but it is pending!" and its cleanup (open sockets in the
    # discovery transport) may never run.
    """
    mgr = BackgroundRefreshManager(max_inflight=4)
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def _refresh() -> str:
        entered.set()
        try:
            await asyncio.Event().wait()  # never completes
        except asyncio.CancelledError:
            cleaned.set()
            raise
        return "unreachable"

    task = mgr.start_or_join("k", _refresh)
    assert task is not None
    await entered.wait()

    await mgr.aclose()

    assert task.done(), "aclose must have awaited it"
    assert task.cancelled()
    assert cleaned.is_set(), "the task's own cleanup must have run"
    assert mgr.inflight == 0


@pytest.mark.asyncio
async def test_aclose_is_idempotent_and_refuses_new_work_afterwards() -> None:
    mgr = BackgroundRefreshManager(max_inflight=4)
    await mgr.aclose()
    await mgr.aclose()

    async def _refresh() -> str:
        raise AssertionError("must not run after shutdown")

    assert mgr.start_or_join("k", _refresh) is None


@pytest.mark.asyncio
async def test_the_manager_holds_a_strong_reference_to_every_task(manager) -> None:
    """A bare create_task result can be garbage collected mid-flight."""
    release = asyncio.Event()

    async def _refresh() -> str:
        await release.wait()
        return "kept"

    manager.start_or_join("k", _refresh)
    await asyncio.sleep(0)

    assert manager.inflight == 1
    assert manager.tracked_keys() == ("k",)
    release.set()


# ── supersede: cancel one identity's refresh (OME-1026 rework U3) ──────────────


@pytest.mark.asyncio
async def test_cancel_stops_one_refresh_and_frees_its_slot(manager) -> None:
    """FEATURE: credential replacement supersedes the refresh started by the old owner.

    # WHY cancel rather than let it finish: the task holds an auth context built from
    # the PREVIOUS credential. Letting it run spends an upstream request whose answer
    # describes an owner who no longer holds the profile.
    """
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def _refresh() -> str:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaned.set()
            raise
        return "unreachable"

    task = manager.start_or_join(("acct", "anthropic", "work"), _refresh)
    await entered.wait()

    assert manager.cancel(("acct", "anthropic", "work")) is True
    await asyncio.sleep(0)

    assert task.cancelled()
    assert cleaned.is_set(), "the superseded task's own cleanup must run"
    assert manager.inflight == 0, "a cancelled task must not keep occupying a slot"


@pytest.mark.asyncio
async def test_cancel_is_a_no_op_for_an_unknown_or_finished_key(manager) -> None:
    async def _quick() -> str:
        return "done"

    assert manager.cancel(("never", "started", "x")) is False
    assert await manager.start_or_join(("k", "k", "k"), _quick) == "done"
    await asyncio.sleep(0)
    assert manager.cancel(("k", "k", "k")) is False


@pytest.mark.asyncio
async def test_a_cancelled_key_accepts_a_new_refresh_immediately(manager) -> None:
    """INVARIANT: the replacement refresh must not JOIN the doomed one.

    # WHY this is subtle: ``Task.cancel()`` does not make a task ``done()`` — the
    # coroutine only observes the cancellation on the next loop pass. A dedup check
    # that merely asked ``not done()`` would hand the new owner a handle to the task
    # being torn down, and the caller would wait out its budget for nothing.
    """
    started: list[str] = []
    release = asyncio.Event()

    def _make(tag: str):
        async def _refresh() -> str:
            started.append(tag)
            await release.wait()
            return tag

        return _refresh

    key = ("acct", "anthropic", "work")
    doomed = manager.start_or_join(key, _make("old"))
    await asyncio.sleep(0)
    manager.cancel(key)

    fresh = manager.start_or_join(key, _make("new"))
    assert fresh is not None
    assert fresh is not doomed, "a superseded task must never be joined"

    release.set()
    assert await fresh == "new"
    assert started == ["old", "new"]


@pytest.mark.asyncio
async def test_shutdown_also_awaits_a_task_cancelled_by_supersede() -> None:
    """A cancelled task keeps a strong reference until it actually finishes."""
    mgr = BackgroundRefreshManager(max_inflight=2)
    entered = asyncio.Event()

    async def _refresh() -> str:
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    task = mgr.start_or_join(("a", "b", "c"), _refresh)
    assert task is not None
    await entered.wait()
    mgr.cancel(("a", "b", "c"))

    await mgr.aclose()

    assert task.done() and task.cancelled()


@pytest.mark.asyncio
async def test_tuple_identities_never_collide_across_accounts(manager) -> None:
    """INVARIANT: identity is a TUPLE, so no profile name can forge another's key.

    # WHY not a joined string: a profile name is user-supplied. With ``a:b:name`` keys
    # a name containing the separator could alias a sibling identity; tuple equality
    # has no such failure mode, and cancel-by-identity compares fields, not prefixes.
    """
    release = asyncio.Event()
    seen: list[tuple[str, ...]] = []

    def _make(identity: tuple[str, ...]):
        async def _refresh() -> tuple[str, ...]:
            seen.append(identity)
            await release.wait()
            return identity

        return _refresh

    a = ("acct-a", "anthropic", "work:x")
    b = ("acct-a", "anthropic", "work", "x")
    ta = manager.start_or_join(a, _make(a))
    tb = manager.start_or_join(b, _make(b))
    await asyncio.sleep(0)

    assert ta is not tb
    release.set()
    assert {await ta, await tb} == {a, b}
    assert sorted(seen) == sorted([a, b])
