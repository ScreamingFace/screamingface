"""The wake-up's own machinery, exercised with a fake CORE-NATS connection (OME-1091 F6,
design review follow-up).

Every OTHER unit pull test fakes `_jetstream` alone and leaves `_nc` at its default `None`
(see `tests/unit/test_queue_fairness.py`), so `_ensure_wake_subscription` always returns
`None` there and every one of those pulls takes the ORIGINAL slow-pass fallback — the wake
path itself, and the defects specific to it, are unexercised. This file gives `pull` a fake
`_nc` too, so `_ensure_wake_subscription` succeeds and the wake path actually runs:

- a wake naming one bucket makes the repeat pass fetch ONLY that bucket (the targeted pass,
  the design review's accepted fix over a full re-rotation);
- an empty-payload wake (`release_held`'s drain-wide nudge) does a full pass instead;
- a blip that leaves something already collected returns it at once and never re-binds the
  dropped subscription (the old code went on into the wake wait / slow
  pass, and the next visit's rebind can raise mid-outage, discarding delivered messages);
- a wake landing near `timeout_s`'s deadline never lets the pull run over it (the
  defect, measured at 2.9s for a real `pull(1, timeout_s=2.0)`);
- a surplus `fetch` return is NAK'd on the wake path exactly like the fast pass (V-4);
- a pass that collects something but not the full batch runs ONE top-up rotation over
  just the bucket(s) it came from and returns (the wake path's own
  version of the OME-1091 burst property — `test_queue_fairness.py`'s
  `test_one_callers_burst_fills_the_batch_from_one_bucket` exercises the FALLBACK only),
  rather than either an instant partial return or a full re-rotation.

Self-contained fixtures rather than imports from a sibling test module: the append-only rule
means each cycle brings its own.
"""

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import nats.errors
import pytest

from screamingface_engine import runner_queue
from screamingface_engine.runner_queue import RunQueue

pytestmark = pytest.mark.asyncio


class _WakeFakeSub:
    """One bucket's pull subscription. `fetch` records every subject it is asked to visit
    (and its window), serves that subject's queued messages (over-returning one extra when
    the subject is in `over_return_subjects`, the V-4 shape), and — when nothing is queued
    and `simulate_wait` is set — actually SLEEPS the window before raising, like the real
    broker's blocking fetch, so a test can measure real elapsed time against it."""

    def __init__(self, js: "_WakeFakeJetStream", subject: str) -> None:
        self._js = js
        self._subject = subject

    async def fetch(self, batch: int, timeout: float) -> list[Any]:
        self._js.fetched_subjects.append(self._subject)
        self._js.fetch_windows.append((self._subject, timeout))
        if self._subject in self._js.blip_subjects:
            raise nats.errors.Error("broker blip")
        pending = self._js.messages.setdefault(self._subject, [])
        take = batch + 1 if self._subject in self._js.over_return_subjects else batch
        out = pending[:take]
        del pending[:take]
        if out:
            return [SimpleNamespace(data=payload, nak=self._nak) for payload in out]
        if self._js.simulate_wait:
            await asyncio.sleep(timeout)
        raise TimeoutError("nats: timeout")

    async def _nak(self) -> None:
        self._js.nakked.append(self._subject)

    async def unsubscribe(self) -> None:
        pass


class _WakeFakeJetStream:
    """The slice of `JetStreamContext` the queue uses, instrumented for the wake path:
    every `pull_subscribe` call is counted per subject (so a test can assert a dropped
    subscription is never rebound), and `_WakeFakeSub` above serves each subject's
    messages."""

    def __init__(self, *, simulate_wait: bool = False) -> None:
        self.messages: dict[str, list[bytes]] = {}
        self.fetched_subjects: list[str] = []
        self.fetch_windows: list[tuple[str, float]] = []
        self.blip_subjects: set[str] = set()
        self.over_return_subjects: set[str] = set()
        self.nakked: list[str] = []
        self.rebind_attempts: dict[str, int] = {}
        self.simulate_wait = simulate_wait
        self._subs: dict[str, _WakeFakeSub] = {}

    async def add_stream(self, **kwargs: Any) -> object:
        return object()

    async def _api_request(self, subject: str, req: bytes = b"", **_: Any) -> dict[str, Any]:
        return {"state": {"messages": 0, "first_ts": None}}

    async def pull_subscribe(
        self,
        subject: str,
        durable: str | None = None,
        stream: str | None = None,
        config: Any = None,
    ) -> _WakeFakeSub:
        self.rebind_attempts[subject] = self.rebind_attempts.get(subject, 0) + 1
        sub = self._subs.get(subject)
        if sub is None:
            sub = _WakeFakeSub(self, subject)
            self._subs[subject] = sub
        return sub


class _FakeCoreClient:
    """The slice of `nats.aio.client.Client` the wake-up uses. `subscribe` records the
    callback so a test can `deliver` a wake exactly as the broker would, without going
    through the queue's own `publish`/`release_held`."""

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []
        self._cb: Any = None

    async def subscribe(self, subject: str, cb: Any) -> Any:
        self._cb = cb
        return SimpleNamespace(unsubscribe=self._unsubscribe)

    async def _unsubscribe(self) -> None:
        pass

    async def publish(self, subject: str, payload: bytes = b"") -> None:
        self.published.append((subject, payload))

    async def deliver(self, payload: bytes) -> None:
        assert self._cb is not None, "the wake subscription must be bound before delivering"
        await self._cb(SimpleNamespace(data=payload))


def _queue(js: _WakeFakeJetStream, core: _FakeCoreClient, **kwargs: Any) -> RunQueue:
    queue = RunQueue("nats://unused:4222", **kwargs)

    async def _fake_jetstream() -> _WakeFakeJetStream:
        return js

    queue._jetstream = _fake_jetstream  # type: ignore[assignment,method-assign]  # noqa: SLF001
    queue._nc = core  # type: ignore[assignment]  # noqa: SLF001
    return queue


async def _settle() -> None:
    """Let the pull's fast pass run to completion and reach the wake wait before a test
    delivers its wake — these fakes' fetches are instant (no message, no blip, no
    `simulate_wait`), so a couple of scheduler turns is enough."""
    for _ in range(10):
        await asyncio.sleep(0)


# --- 1. the targeted wake pass ----------------------------------------------------------------


async def test_a_wake_for_one_bucket_makes_the_next_pass_fetch_only_it() -> None:
    """The whole point of tracking WHICH bucket a wake was for: the repeat pass fetches
    only that one, not a full rotation."""
    js = _WakeFakeJetStream()
    core = _FakeCoreClient()
    queue = _queue(js, core, bucket_count=4)
    subjects = queue.bucket_subjects()
    target = subjects[2]

    pull_task = asyncio.create_task(queue.pull(1, timeout_s=5.0))
    await _settle()
    js.fetched_subjects.clear()  # only the wake pass's own fetches matter here
    js.messages[target] = [b"payload"]
    await core.deliver(target.encode())

    pulled = await pull_task
    assert len(pulled) == 1
    assert js.fetched_subjects == [target], "the wake pass must visit only the woken bucket"


async def test_an_empty_payload_wake_does_a_full_pass() -> None:
    """`release_held`'s drain-wide nudge carries no bucket — its given-back messages can
    span any of them — so an empty payload must trigger a FULL pass, not a targeted one."""
    js = _WakeFakeJetStream()
    core = _FakeCoreClient()
    queue = _queue(js, core, bucket_count=4)
    subjects = queue.bucket_subjects()

    pull_task = asyncio.create_task(queue.pull(1, timeout_s=5.0))
    await _settle()
    js.fetched_subjects.clear()
    # The wake pass follows the fast pass's rotation offset, so its order is `subjects`
    # rotated by `_rr_index`; the message sits in the LAST bucket of that order, so every
    # other bucket is visited first.
    start = queue._rr_index  # noqa: SLF001
    order = subjects[start:] + subjects[:start]
    js.messages[order[-1]] = [b"payload"]
    await core.deliver(b"")

    pulled = await pull_task
    assert len(pulled) == 1
    assert js.fetched_subjects == order, "an 'all' wake must sweep every bucket, in rotation"


# --- 2. a blip must never be followed by a rebind ----------------------------------


async def test_a_blip_after_a_collected_message_returns_it_at_once_and_never_rebinds() -> None:
    """DEFECT: the old code let a fast pass that stopped on a blip go on into the
    wake wait or the slow pass, and the very next visit to the DROPPED subscription
    rebinds it (`_bound_subscription` -> `js.pull_subscribe`) — which raises during a
    broker outage and would unwind `pull`, discarding the message already collected and
    delivered (never acked, never NAK'd). The fix returns it at once, straight from the
    fast pass, and never touches the broken subject again."""
    js = _WakeFakeJetStream()
    core = _FakeCoreClient()
    queue = _queue(js, core, bucket_count=2)
    subjects = queue.bucket_subjects()
    ok, blipped = subjects[0], subjects[1]
    js.messages[ok] = [b"payload"]
    js.blip_subjects.add(blipped)

    pull_task = asyncio.create_task(queue.pull(2, timeout_s=5.0))
    await _settle()
    assert pull_task.done(), (
        "the collected message must be returned at once, not held waiting for a wake"
    )
    # A wake arriving AFTER `pull` has already returned — another pod's publish, say —
    # must find nothing left to do for this call; delivering one here would be exactly
    # what let the old code revisit (and rebind) the broken subject a second time.
    await core.deliver(ok.encode())

    pulled = await pull_task
    assert len(pulled) == 1
    assert js.rebind_attempts[blipped] == 1, "the dropped subscription must never be rebound"


# --- 3. the deadline caps every window, even a wake's -----------------------------


async def test_the_pull_never_exceeds_timeout_s_with_a_wake_near_the_deadline(monkeypatch) -> None:
    """DEFECT: a wake landing near the deadline started its pass with the
    NORMAL, unclamped fast window — measured at 2.9s for a real `pull(1, timeout_s=2.0)`.
    Every fetch window in every pass must be capped by what remains until the deadline."""
    monkeypatch.setattr(runner_queue, "PULL_FAST_PASS_S", 0.3)
    js = _WakeFakeJetStream(simulate_wait=True)
    core = _FakeCoreClient()
    queue = _queue(js, core, bucket_count=1)
    subjects = queue.bucket_subjects()
    timeout_s = 1.0
    wake_at = timeout_s - 0.05

    async def _deliver_late() -> None:
        await asyncio.sleep(wake_at)
        await core.deliver(subjects[0].encode())

    delivery = asyncio.create_task(_deliver_late())
    started = time.monotonic()
    pulled = await queue.pull(1, timeout_s=timeout_s)
    elapsed = time.monotonic() - started
    await delivery

    assert pulled == []
    assert elapsed < timeout_s + 0.1, f"took {elapsed:.3f}s against a {timeout_s}s timeout"


# --- 4. V-4 (the surplus NAK) also holds on the wake path -----------------------------------


async def test_a_surplus_from_fetch_is_nakd_on_the_wake_path_too() -> None:
    """V-4: nats-py's `_fetch_n` can over-return from a subscription's pending queue; the
    targeted wake pass must clamp to the batch and NAK the surplus exactly like the fast
    pass does — not drop it, and not ack it away."""
    js = _WakeFakeJetStream()
    core = _FakeCoreClient()
    queue = _queue(js, core, bucket_count=2)
    subjects = queue.bucket_subjects()
    target = subjects[0]
    js.over_return_subjects.add(target)

    pull_task = asyncio.create_task(queue.pull(2, timeout_s=5.0))
    await _settle()
    js.messages[target] = [b"m1", b"m2", b"m3"]
    await core.deliver(target.encode())

    pulled = await pull_task
    assert len(pulled) == 2, "the wake pass must clamp to the batch"
    assert js.nakked == [target], "the surplus must be NAK'd, not dropped"


# --- 5. the top-up, not an instant return or a full re-rotation ----------------------------


async def test_one_callers_burst_fills_the_batch_via_the_top_up_on_the_wake_path() -> None:
    """The OME-1091 burst property (`test_queue_fairness.py`'s
    `test_one_callers_burst_fills_the_batch_from_one_bucket`, which exercises the
    `_nc=None` FALLBACK only) must also hold on the WAKE path: a caller's burst already
    sitting in one bucket still fills the batch in one `pull` call — via the fast pass
    plus its top-up rotation over that same bucket — well under the timeout, never held
    for the deadline."""
    js = _WakeFakeJetStream()
    core = _FakeCoreClient()
    queue = _queue(js, core, bucket_count=16)
    subjects = queue.bucket_subjects()
    target = subjects[5]
    js.messages[target] = [f"m{i}".encode() for i in range(8)]

    started = time.monotonic()
    pulled = await queue.pull(4, timeout_s=5.0)
    elapsed = time.monotonic() - started

    assert len(pulled) == 4, "a single caller's burst must fill the batch in one pull"
    assert elapsed < 1.0, f"took {elapsed:.3f}s, not well under the 5.0s timeout"


async def test_a_wake_pass_that_partially_fills_the_batch_tops_up_and_returns() -> None:
    """A wake pass that finds 1 message in bucket X — every other bucket empty, and a
    bigger batch than 1 — must top up from X alone and return, rather than holding for a
    further wake that may never target this pull's buckets again, or for the deadline."""
    js = _WakeFakeJetStream()
    core = _FakeCoreClient()
    queue = _queue(js, core, bucket_count=4)
    subjects = queue.bucket_subjects()
    target = subjects[1]

    pull_task = asyncio.create_task(queue.pull(4, timeout_s=10.0))
    await _settle()
    js.messages[target] = [b"payload"]
    started = time.monotonic()
    await core.deliver(target.encode())

    pulled = await pull_task
    elapsed = time.monotonic() - started

    assert len(pulled) == 1
    assert elapsed < 1.0, f"took {elapsed:.3f}s waiting for a top-up that had nothing more"
