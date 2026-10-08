"""A run start that the Engine did not admit waits for capacity (OME-1066).

FEATURE: OME-1066 — Engine admission (OME-1091) turns "no room" into a wait, not a failure.
STORY: as a researcher whose Evaluation starts while the Engine is busy, my Candidates are
shown as waiting for capacity and then start; they fail only after a clear, bounded wait
that names capacity as the cause — and waiting never stops my other Candidates.

Spec: `docs/spec/2026-09-28-sdk-run-isolation.md` §6. A `503` on `GET /?q=` schedules
nothing (spec E3), so the same start may be sent again.
"""

from __future__ import annotations

import asyncio
import io
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from _isolation_engine import (
    QUEUE_DETAIL,
    RunPlan,
    StubEngine,
    candidate,
    isolation_engine,
    result_body,
    url4_of,
)

from screamingface._core.ports import _ConnectionNotice
from screamingface._core.retry import _utc_now
from screamingface._engine import admission as admission_module
from screamingface._engine import transport as transport_module
from screamingface._engine.admission import _AdmissionWait
from screamingface._engine.transport import (
    AsyncUrl4CloudTransport,
    Url4CloudTransport,
    _start_async,
    _start_sync,
)
from screamingface._evaluation.progress import _ProgressObserver
from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface._ui.evaluation_view import _candidate_row_html
from screamingface.errors import ExecutionError
from screamingface.events import Event

_BUSY: tuple[int, str | None] = (503, "0")


def _busy(retry_after: str | None) -> httpx.Response:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return httpx.Response(503, headers=headers)


def _policy(
    budget_s: float = 900.0,
    floor_s: float = 0.5,
    wall_clock: Callable[[], datetime] = _utc_now,
) -> _AdmissionWait:
    # A deterministic stand-in for the full-jitter backoff: attempt n waits n + 1 seconds.
    return _AdmissionWait(
        budget_s=budget_s,
        floor_s=floor_s,
        backoff=lambda attempt: attempt + 1.0,
        wall_clock=wall_clock,
    )


# The one clock the fake Engine's HTTP-date and the policy's parser both read (whole seconds,
# since an HTTP-date has no fractions). WHY (OME-1507): a header built from the real "now +
# 10s" and measured against a later wall-clock read can lose up to 1s and leave a window
# instead of a number; one injected clock makes the wait exact.
_WIRE_NOW = datetime(2026, 10, 6, 14, 41, 50, tzinfo=UTC)


# --- The policy: how long to wait, and when to stop --------------------------------------


def test_a_delta_seconds_retry_after_is_obeyed() -> None:
    assert _policy().next_delay(_busy("5"), now=0.0) == 5.0


def test_an_http_date_retry_after_is_obeyed() -> None:
    when = format_datetime(_WIRE_NOW + timedelta(seconds=10), usegmt=True)
    delay = _policy(wall_clock=lambda: _WIRE_NOW).next_delay(_busy(when), now=0.0)
    assert delay == 10.0


def test_the_default_wall_clock_is_real_utc_time() -> None:
    # INVARIANT: the seam is for tests; a production policy measures the Engine's HTTP-date
    # against real UTC time, never a frozen one.
    assert _AdmissionWait(budget_s=1.0, floor_s=0.0, backoff=float).wall_clock is _utc_now


@pytest.mark.parametrize("retry_after", [None, "soon", ""])
def test_an_absent_or_unparsable_retry_after_uses_the_backoff(retry_after: str | None) -> None:
    policy = _policy()
    assert policy.next_delay(_busy(retry_after), now=0.0) == 1.0
    assert policy.next_delay(_busy(retry_after), now=1.0) == 2.0
    assert policy.attempts == 2


def test_a_zero_retry_after_cannot_spin() -> None:
    # INVARIANT: every wait is at least the floor, so `Retry-After: 0` is not a hot loop.
    assert _policy(floor_s=0.5).next_delay(_busy("0"), now=0.0) == 0.5


def test_the_last_wait_is_cut_to_the_deadline_then_the_budget_ends() -> None:
    # WHY: the budget is a promise to the caller; the final attempt goes out AT the deadline.
    policy = _policy(budget_s=10.0)
    assert policy.next_delay(_busy("30"), now=0.0) == 10.0
    assert policy.next_delay(_busy("30"), now=10.0) is None
    assert policy.waited_s(now=10.0) == 10.0


def test_a_zero_budget_never_waits() -> None:
    assert _policy(budget_s=0.0).next_delay(_busy("1"), now=0.0) is None


def test_the_default_budget_is_fifteen_minutes() -> None:
    # Owner decision pending (spec Q4); the value is the recommendation, pinned so a change
    # is deliberate.
    assert admission_module._ADMISSION_BUDGET_S == 900.0  # noqa: SLF001


# --- The transport: a real stub engine ----------------------------------------------------


class _Listener:
    """An `on_event` that also takes connection notices, as the runner's bound observer does."""

    def __init__(self) -> None:
        self.notices: list[tuple[str, int | None]] = []

    def __call__(self, event: Event) -> None:
        del event

    def connection(self, notice: _ConnectionNotice) -> None:
        self.notices.append((notice.state, notice.attempt))


def _sync(engine: StubEngine, *, budget_s: float = 30.0) -> Url4CloudTransport:
    return Url4CloudTransport(engine.url, admission_budget_s=budget_s, reconnect_base_delay_s=0.01)


def _async(engine: StubEngine, *, budget_s: float = 30.0) -> AsyncUrl4CloudTransport:
    return AsyncUrl4CloudTransport(
        engine.url, admission_budget_s=budget_s, reconnect_base_delay_s=0.01
    )


def test_a_refused_start_waits_then_the_run_completes() -> None:
    plans = {url4_of("queued"): RunPlan(admission=[_BUSY, (503, "soon")])}
    listener = _Listener()
    with isolation_engine(plans) as engine:
        transport = _sync(engine)
        try:
            outcome = transport.run(candidate("queued"), listener)
        finally:
            transport.close()

    assert outcome.result_body == result_body(url4_of("queued"))
    assert engine.state.start_attempts[url4_of("queued")] == 3
    assert engine.state.deleted == []
    assert listener.notices == [
        ("waiting_for_capacity", 1),
        ("waiting_for_capacity", 2),
        ("admitted", None),
    ]


@pytest.mark.asyncio
async def test_async_a_refused_start_waits_then_the_run_completes() -> None:
    plans = {url4_of("queued"): RunPlan(admission=[_BUSY, (503, "soon")])}
    listener = _Listener()
    with isolation_engine(plans) as engine:
        transport = _async(engine)
        try:
            outcome = await transport.run(candidate("queued"), listener)
        finally:
            await transport.close()

    assert outcome.result_body == result_body(url4_of("queued"))
    assert engine.state.start_attempts[url4_of("queued")] == 3
    assert engine.state.deleted == []
    assert listener.notices == [
        ("waiting_for_capacity", 1),
        ("waiting_for_capacity", 2),
        ("admitted", None),
    ]


def test_a_retry_after_of_one_second_is_waited_out() -> None:
    plans = {url4_of("queued"): RunPlan(admission=[(503, "1")])}
    with isolation_engine(plans) as engine:
        transport = _sync(engine)
        try:
            began = time.monotonic()
            transport.run(candidate("queued"), None)
            elapsed = time.monotonic() - began
        finally:
            transport.close()

    assert elapsed >= 0.9
    assert engine.state.start_attempts[url4_of("queued")] == 2


@pytest.mark.asyncio
async def test_async_a_retry_after_of_one_second_is_waited_out() -> None:
    plans = {url4_of("queued"): RunPlan(admission=[(503, "1")])}
    with isolation_engine(plans) as engine:
        transport = _async(engine)
        try:
            began = time.monotonic()
            await transport.run(candidate("queued"), None)
            elapsed = time.monotonic() - began
        finally:
            await transport.close()

    assert elapsed >= 0.9
    assert engine.state.start_attempts[url4_of("queued")] == 2


def _assert_capacity_error(error: ExecutionError) -> None:
    # INVARIANT (OME-1066 acceptance): the error names Engine capacity, not a generic
    # transport failure, and it says a later retry may succeed.
    assert error.code == "engine_at_capacity"
    assert error.status == 503
    assert error.retryable is True
    assert "capacity" in error.message
    assert "the runner is at capacity" in error.message  # the Engine's own detail


def test_a_start_that_is_never_admitted_ends_with_a_capacity_error() -> None:
    plans = {url4_of("queued"): RunPlan(admission=[_BUSY] * 1000)}
    with isolation_engine(plans) as engine:
        transport = _sync(engine, budget_s=0.3)
        try:
            with pytest.raises(ExecutionError) as caught:
                transport.run(candidate("queued"), None)
        finally:
            transport.close()

    _assert_capacity_error(caught.value)
    assert engine.state.start_attempts[url4_of("queued")] >= 2
    assert engine.state.deleted == []  # nothing started, so there is nothing to stop


@pytest.mark.asyncio
async def test_async_a_start_that_is_never_admitted_ends_with_a_capacity_error() -> None:
    plans = {url4_of("queued"): RunPlan(admission=[_BUSY] * 1000)}
    with isolation_engine(plans) as engine:
        transport = _async(engine, budget_s=0.3)
        try:
            with pytest.raises(ExecutionError) as caught:
                await transport.run(candidate("queued"), None)
        finally:
            await transport.close()

    _assert_capacity_error(caught.value)
    assert engine.state.deleted == []


@pytest.mark.parametrize("status", [500, 502])
def test_another_5xx_on_start_still_fails_at_once(status: int) -> None:
    # INVARIANT (OME-1066 acceptance): only 503 means "not admitted"; other 5xx keep
    # today's behavior.
    plans = {url4_of("broken"): RunPlan(admission=[(status, None)])}
    with isolation_engine(plans) as engine:
        transport = _sync(engine)
        try:
            with pytest.raises(ExecutionError) as caught:
                transport.run(candidate("broken"), None)
        finally:
            transport.close()

    assert caught.value.status == status
    assert caught.value.code != "engine_at_capacity"
    assert engine.state.start_attempts[url4_of("broken")] == 1


def _wait_for_attempt(engine: StubEngine, name: str, count: int) -> None:
    deadline = time.monotonic() + 10
    while engine.state.start_attempts.get(url4_of(name), 0) < count:
        if time.monotonic() > deadline:
            raise AssertionError(f"{name!r} never sent start attempt {count}")
        time.sleep(0.01)


def test_a_waiting_start_does_not_stop_a_sibling() -> None:
    # INVARIANT (OME-1066 acceptance): waiting for capacity is not a failure — nothing is
    # stopped, and a sibling that was admitted runs to its result meanwhile.
    plans = {
        url4_of("queued"): RunPlan(admission=[(503, "1"), (503, "1")]),
        url4_of("admitted"): RunPlan(),
    }
    with isolation_engine(plans) as engine:
        transport = _sync(engine)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                queued = pool.submit(transport.run, candidate("queued"), None)
                _wait_for_attempt(engine, "queued", 1)
                sibling = transport.run(candidate("admitted"), None)
                still_waiting = engine.state.start_attempts[url4_of("queued")] < 3
                outcome = queued.result(timeout=10)
        finally:
            transport.close()

    assert sibling.result_body == result_body(url4_of("admitted"))
    assert still_waiting
    assert outcome.result_body == result_body(url4_of("queued"))
    assert engine.state.deleted == []


def test_an_owner_abort_ends_the_wait_at_once_and_never_starts_the_run() -> None:
    # INVARIANT (spec B3): after Ctrl-C the sweep runs on the main thread while this worker
    # waits. A plain sleep would wake up later, send the start again, and begin a paid Run
    # that nobody reads.
    plans = {url4_of("queued"): RunPlan(admission=[(503, "30"), *[_BUSY] * 10])}
    with isolation_engine(plans) as engine:
        transport = _sync(engine, budget_s=60.0)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                queued = pool.submit(transport.run, candidate("queued"), None)
                _wait_for_attempt(engine, "queued", 1)
                began = time.monotonic()
                transport.cancel_active()
                with pytest.raises(ExecutionError) as caught:
                    queued.result(timeout=10)
                elapsed = time.monotonic() - began
        finally:
            transport.close()

    assert caught.value.code == "run_aborted"
    assert elapsed < 5.0
    assert engine.state.start_attempts[url4_of("queued")] == 1
    assert url4_of("queued") not in engine.state.started.values()


@pytest.mark.asyncio
async def test_async_an_owner_abort_ends_the_wait_at_once_and_never_starts_the_run() -> None:
    plans = {url4_of("queued"): RunPlan(admission=[(503, "30"), *[_BUSY] * 10])}
    with isolation_engine(plans) as engine:
        transport = _async(engine, budget_s=60.0)
        try:
            queued = asyncio.create_task(transport.run(candidate("queued"), None))
            await asyncio.to_thread(_wait_for_attempt, engine, "queued", 1)
            began = time.monotonic()
            await transport.cancel_active()
            with pytest.raises(ExecutionError) as caught:
                await asyncio.wait_for(queued, timeout=10)
            elapsed = time.monotonic() - began
        finally:
            await transport.close()

    assert caught.value.code == "run_aborted"
    assert elapsed < 5.0
    assert engine.state.start_attempts[url4_of("queued")] == 1


# --- What the researcher sees -------------------------------------------------------------

_WAITING = _ConnectionNotice(state="waiting_for_capacity", attempt=1)
_ADMITTED = _ConnectionNotice(state="admitted")


def test_terminal_progress_prints_generic_capacity_lines() -> None:
    stream = io.StringIO()
    observer = _ProgressObserver(stream)
    observer.connection(candidate("opus"), _WAITING)
    observer.connection(candidate("opus"), _ADMITTED)

    assert stream.getvalue().splitlines() == [
        "ScreamingFace · opus · waiting for Engine capacity (attempt 1)",
        "ScreamingFace · opus · Engine capacity available — starting",
    ]


def test_panel_row_shows_the_wait_then_returns_to_its_status() -> None:
    selected = candidate("opus")
    progress = _EvaluationProgress(candidates=(selected,), case_count=1)
    progress.begin(selected)
    row = progress.rows[0]
    normal = _candidate_row_html(row, 1.0)

    progress.connection(selected, _WAITING)
    assert "Waiting for Engine capacity (attempt 1)" in _candidate_row_html(row, 1.0)
    assert progress.announcement == "opus waiting for Engine capacity (attempt 1)"

    progress.connection(selected, _ADMITTED)
    assert _candidate_row_html(row, 1.0) == normal
    assert progress.announcement == "opus Engine capacity available"


# --- The old call shape (`_start_sync(http, token, url4)`) waits too ----------------------


def _busy_then_accepted() -> httpx.MockTransport:
    answers = [
        httpx.Response(
            503,
            headers={"Retry-After": "0", "Content-Type": "application/problem+json"},
            json={"detail": "the runner is at capacity — retry shortly"},
        ),
        httpx.Response(
            202, headers={"Preference-Applied": "respond-async", "Location": "/?topic=t"}
        ),
    ]
    return httpx.MockTransport(lambda request: answers.pop(0))


def test_a_direct_start_call_uses_the_default_wait() -> None:
    # AIDEV-NOTE: direct callers pass no policy; they get the default budget and a plain
    # sleep (no owner abort to wake it), floored at the reconnect base delay.
    with httpx.Client(base_url="http://engine.test", transport=_busy_then_accepted()) as http:
        began = time.monotonic()
        _start_sync(http, "capability", "(@)!'hello'")

    assert time.monotonic() - began >= 0.4


@pytest.mark.asyncio
async def test_async_a_direct_start_call_uses_the_default_wait() -> None:
    async with httpx.AsyncClient(
        base_url="http://engine.test", transport=_busy_then_accepted()
    ) as http:
        began = time.monotonic()
        await _start_async(http, "capability", "(@)!'hello'")

    assert time.monotonic() - began >= 0.4


# --- Review round 1: only the Engine's own refusal is waited out -------------------------


def test_a_409_after_a_resent_start_means_this_run_was_admitted() -> None:
    # INVARIANT (review fix 1): one capability names one topic, so a 409 "a run already
    # exists" on a RE-SENT start is THIS Run — an earlier attempt was scheduled although its
    # answer was a refusal. Failing here would drop the capability without a stop and leave
    # a paid Run running; the WebSocket is already attached to its topic, so read it.
    plans = {url4_of("hidden"): RunPlan(admission=[_BUSY], hidden_accept=True)}
    listener = _Listener()
    with isolation_engine(plans) as engine:
        transport = _sync(engine)
        try:
            outcome = transport.run(candidate("hidden"), listener)
        finally:
            transport.close()

    assert outcome.result_body == result_body(url4_of("hidden"))
    assert engine.state.start_attempts[url4_of("hidden")] == 2
    assert engine.state.deleted == []
    assert listener.notices[-1] == ("admitted", None)


@pytest.mark.asyncio
async def test_async_a_409_after_a_resent_start_means_this_run_was_admitted() -> None:
    plans = {url4_of("hidden"): RunPlan(admission=[_BUSY], hidden_accept=True)}
    with isolation_engine(plans) as engine:
        transport = _async(engine)
        try:
            outcome = await transport.run(candidate("hidden"), None)
        finally:
            await transport.close()

    assert outcome.result_body == result_body(url4_of("hidden"))
    assert engine.state.start_attempts[url4_of("hidden")] == 2
    assert engine.state.deleted == []


def _conflict() -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda request: httpx.Response(
            409,
            headers={"Content-Type": "application/problem+json"},
            json={"detail": "a run already exists"},
        )
    )


def test_a_409_on_a_first_start_is_still_an_error() -> None:
    # WHY: with no refusal before it, a 409 is not a hidden admission of this attempt.
    with httpx.Client(base_url="http://engine.test", transport=_conflict()) as http:
        with pytest.raises(ExecutionError) as caught:
            _start_sync(http, "capability", "(@)!'hello'")

    assert caught.value.status == 409


@pytest.mark.asyncio
async def test_async_a_409_on_a_first_start_is_still_an_error() -> None:
    async with httpx.AsyncClient(base_url="http://engine.test", transport=_conflict()) as http:
        with pytest.raises(ExecutionError) as caught:
            await _start_async(http, "capability", "(@)!'hello'")

    assert caught.value.status == 409


def test_a_503_that_the_engine_did_not_write_is_fatal() -> None:
    # INVARIANT (review fix 1): only the Engine's own refusal (problem+json + Retry-After)
    # says "nothing was scheduled". An edge proxy's 503 may hide a start the Engine took.
    plans = {url4_of("edge"): RunPlan(admission=[(503, None)])}
    with isolation_engine(plans) as engine:
        transport = _sync(engine)
        try:
            with pytest.raises(ExecutionError) as caught:
                transport.run(candidate("edge"), None)
        finally:
            transport.close()

    assert caught.value.status == 503
    assert caught.value.code != "engine_at_capacity"
    assert engine.state.start_attempts[url4_of("edge")] == 1


@pytest.mark.asyncio
async def test_async_a_503_that_the_engine_did_not_write_is_fatal() -> None:
    plans = {url4_of("edge"): RunPlan(admission=[(503, None)])}
    with isolation_engine(plans) as engine:
        transport = _async(engine)
        try:
            with pytest.raises(ExecutionError) as caught:
                await transport.run(candidate("edge"), None)
        finally:
            await transport.close()

    assert caught.value.status == 503
    assert caught.value.code != "engine_at_capacity"
    assert engine.state.start_attempts[url4_of("edge")] == 1


def test_a_queue_outage_past_the_budget_does_not_claim_capacity() -> None:
    # WHY (review, LOW): the Engine also refuses with 503 when its run queue is down
    # (#1098). Telling the researcher "capacity stayed full" would send them the wrong way.
    plans = {url4_of("queued"): RunPlan(admission=[_BUSY] * 1000, refusal_detail=QUEUE_DETAIL)}
    with isolation_engine(plans) as engine:
        transport = _sync(engine, budget_s=0.3)
        try:
            with pytest.raises(ExecutionError) as caught:
                transport.run(candidate("queued"), None)
        finally:
            transport.close()

    assert caught.value.code == "engine_not_admitted"
    assert caught.value.retryable is True
    assert "capacity" not in caught.value.message
    assert QUEUE_DETAIL in caught.value.message


# --- Review round 1: the waiting socket stays alive --------------------------------------


def test_the_socket_sends_keepalive_pings_while_the_start_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INVARIANT (review fix 6): an edge closes an idle WebSocket (Cloudflare: ~100 s), and a
    # capacity wait may last 900 s. The client's keepalive pings are traffic that keeps it
    # open; this proves they flow while the worker thread is blocked in the start loop.
    monkeypatch.setattr(transport_module, "_KEEPALIVE_PING_S", 0.05)
    plans = {url4_of("queued"): RunPlan(admission=[(503, "1")])}
    with isolation_engine(plans) as engine:
        transport = _sync(engine)
        try:
            outcome = transport.run(candidate("queued"), None)
        finally:
            transport.close()

    token = engine.state.capability_of(url4_of("queued"))
    assert outcome.result_body == result_body(url4_of("queued"))
    assert token is not None
    assert engine.state.pings.get(token, 0) >= 3


@pytest.mark.asyncio
async def test_async_the_socket_sends_keepalive_pings_while_the_start_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transport_module, "_KEEPALIVE_PING_S", 0.05)
    plans = {url4_of("queued"): RunPlan(admission=[(503, "1")])}
    with isolation_engine(plans) as engine:
        transport = _async(engine)
        try:
            outcome = await transport.run(candidate("queued"), None)
        finally:
            await transport.close()

    token = engine.state.capability_of(url4_of("queued"))
    assert outcome.result_body == result_body(url4_of("queued"))
    assert token is not None
    assert engine.state.pings.get(token, 0) >= 3
