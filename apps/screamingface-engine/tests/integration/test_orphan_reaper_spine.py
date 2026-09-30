"""End to end: a dead client's run is stopped, a reconnecting client's run is not.

FEATURE: tie a run's lifetime to its audience (OME-890).

STORY: as a researcher whose notebook kernel died mid-evaluation, I stop paying for a run nobody
can receive, and the next evaluation gets its concurrency slot back.

WHY this file exists beside the unit tests: `test_reaper.py` proves the policy against fakes and
`test_reaper_wiring.py` proves the composition. Neither proves the SPINE — that a REAL WebSocket
disconnect reaches the reaper through the real registry, and that the reaper's `stop` reaches a
real in-process run and ends it as `Terminated(stopped)`. That is what these cover, on the same
local-mode App `test_local_spine.py` uses.

AIDEV-NOTE: these tests wait on CONDITIONS with a deadline, never on a fixed sleep. The reaper's
sweep runs on the App's own event loop inside `TestClient`'s portal, so the test thread cannot
await it directly; the observable it polls instead is `/metrics`, which is the surface an operator
uses for exactly this question. `orphan_grace_s` is set small so a sweep tick actually lands
during the test — `_TICKS_PER_GRACE` floors the tick at 1s, so budget just over a second per reap.
"""

import json
import time
from collections.abc import AsyncIterator, Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import LogData

SECRET = "s" * 32

# Small enough that a 1s sweep tick closes the window during the test, large enough that it is not
# already closed the instant the socket drops.
SHORT_GRACE_S = 0.25
# Long enough that no sweep can close the window while the test reconnects, so a run that survives
# proves the DISARM and not merely that the clock had not run out.
LONG_GRACE_S = 300.0

_WAIT_TIMEOUT_S = 10.0
_POLL_S = 0.02


class _SpendingExecutor(Executor):
    """Never finishes on its own, and counts what it "spent" — the shape of an abandoned run.

    Each loop stands for one paid model call. A real orphan keeps issuing these for up to
    `job_deadline_s`; the counter is how a test proves the spending actually stopped rather than
    merely that a frame said so.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        import asyncio

        while True:
            self.calls += 1
            yield LogData.at("INFO", f"model call {self.calls}")
            await asyncio.sleep(0.01)


def _shared_grading(
    *, grace_s: float, max_concurrent_runs: int = 32
) -> Iterator[tuple[TestClient, _SpendingExecutor]]:
    """A local-mode App whose run never ends by itself, assembled as `create_local_app` does."""
    executor = _SpendingExecutor()
    settings = Settings(
        jwt_secret=SECRET,
        orphan_grace_s=grace_s,
        # WHY: the run never completes, so a sync hold would block for the full default 30s.
        # Every test here starts its run with `Prefer: respond-async`; this is the safety net.
        sync_max_wait_s=0.2,
    )
    stream = InMemoryEventStream()
    runner = InProcessJobRunner(
        stream,
        lambda _env: executor,
        base_env={},
        max_concurrent_runs=max_concurrent_runs,
    )
    app = create_app(settings, stream=stream, job_runner=runner)
    app.router.on_shutdown.append(runner.aclose)
    with TestClient(app) as client:
        yield client, executor


@pytest.fixture
def abandoned() -> Iterator[tuple[TestClient, _SpendingExecutor]]:
    yield from _shared_grading(grace_s=SHORT_GRACE_S)


@pytest.fixture
def patient() -> Iterator[tuple[TestClient, _SpendingExecutor]]:
    yield from _shared_grading(grace_s=LONG_GRACE_S)


@pytest.fixture
def single_slot() -> Iterator[tuple[TestClient, _SpendingExecutor]]:
    yield from _shared_grading(grace_s=SHORT_GRACE_S, max_concurrent_runs=1)


def _cap(token: str) -> dict[str, str]:
    return {"URL4-Capability": token}


def _async_start(token: str) -> dict[str, str]:
    """Start headers: the capability plus RFC 7240 `respond-async`, because the run never ends."""
    return {"URL4-Capability": token, "Prefer": "respond-async"}


def _token(client: TestClient) -> str:
    response = client.post("/token")
    assert response.status_code == 200
    return str(response.json()["token"])


def _attach(ws: object, ident: str, from_sequence: int | None = None) -> None:
    data: dict[str, object] = {} if from_sequence is None else {"from_sequence": from_sequence}
    ws.send_text(  # type: ignore[attr-defined]
        json.dumps(
            {
                "specversion": "1.0",
                "id": ident,
                "source": "/test",
                "type": "ai.url4.attach",
                "data": data,
            }
        )
    )


def _metric(client: TestClient, name: str) -> float:
    """One metric's current value, read from the real `/metrics` surface."""
    for line in client.get("/metrics").text.splitlines():
        if line.startswith(f"{name} "):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


def _reaped(client: TestClient) -> float:
    return _metric(client, "screamingface_engine_orphan_runs_reaped_total")


def _armed(client: TestClient) -> float:
    return _metric(client, "screamingface_engine_orphan_runs_armed")


def _wait_until(predicate: Callable[[], bool], what: str) -> None:
    """Poll ``predicate`` until true or the deadline passes.

    AIDEV-NOTE: a deadline-bounded condition wait, never a bare sleep — the reap lands one sweep
    tick after the window closes, and pinning that to a fixed sleep is how a suite becomes flaky.
    """
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(_POLL_S)
    raise AssertionError(f"timed out after {_WAIT_TIMEOUT_S}s waiting for {what}")


def _terminal_of(client: TestClient, token: str) -> dict[str, object]:
    """Replay the topic from the start and return its terminal frame's data."""
    with client.websocket_connect(f"/ws?ticket={token}") as ws:
        _attach(ws, "replay", from_sequence=1)
        while True:
            frame = json.loads(ws.receive_text())
            if frame["type"] == "ai.url4.terminated":
                return dict(frame["data"])


def test_an_abandoned_run_is_stopped_and_stops_spending(
    abandoned: tuple[TestClient, _SpendingExecutor],
) -> None:
    client, executor = abandoned
    token = _token(client)

    with client.websocket_connect(f"/ws?ticket={token}") as ws:
        _attach(ws, "attach-1")
        response = client.get("/?q=hello", headers=_async_start(token))
        assert response.status_code == 202
        # The run must actually be spending before it is abandoned, or this proves nothing.
        _wait_until(lambda: executor.calls > 0, "the run to issue its first model call")

    # The socket is closed: the audience is empty and the grace window is open.
    _wait_until(lambda: _armed(client) == 1.0, "the topic to be armed")
    _wait_until(lambda: _reaped(client) >= 1.0, "the abandoned run to be reaped")

    # INVARIANT: no further paid work after the stop. The executor bills once per 10ms, so a
    # window this wide would add dozens of calls if the run were still going.
    settled = executor.calls
    time.sleep(0.3)

    assert executor.calls == settled
    assert _armed(client) == 0.0
    assert _terminal_of(client, token)["status"] == "stopped"


def test_a_client_that_reconnects_inside_the_window_keeps_its_run(
    patient: tuple[TestClient, _SpendingExecutor],
) -> None:
    # STORY: as a researcher whose wifi blipped, my reconnected notebook keeps its evaluation.
    client, executor = patient
    token = _token(client)

    with client.websocket_connect(f"/ws?ticket={token}") as ws:
        _attach(ws, "attach-1")
        assert client.get("/?q=hello", headers=_async_start(token)).status_code == 202
        _wait_until(lambda: executor.calls > 0, "the run to issue its first model call")

    assert _armed(client) == 1.0  # armed by the disconnect

    with client.websocket_connect(f"/ws?ticket={token}") as ws:
        _attach(ws, "attach-2", from_sequence=1)
        # INVARIANT: the reconnect DISARMS. Asserted against a 300s window so a surviving run
        # cannot be explained by the clock simply not having run out yet.
        assert _armed(client) == 0.0

        replayed = json.loads(ws.receive_text())
        while replayed["type"] == "ai.url4.heartbeat":
            replayed = json.loads(ws.receive_text())
        assert replayed["type"] == "ai.url4.started"

        # The run is still spending, which is the point: it was never stopped.
        spending = executor.calls
        _wait_until(lambda: executor.calls > spending, "the resumed run to keep working")

    assert _reaped(client) == 0.0


def test_an_explicit_delete_is_unchanged_and_is_not_reaped_afterwards(
    abandoned: tuple[TestClient, _SpendingExecutor],
) -> None:
    client, executor = abandoned
    token = _token(client)

    with client.websocket_connect(f"/ws?ticket={token}") as ws:
        _attach(ws, "attach-1")
        assert client.get("/?q=hello", headers=_async_start(token)).status_code == 202
        _wait_until(lambda: executor.calls > 0, "the run to issue its first model call")
        # Unchanged behaviour: still 204, still idempotent.
        assert client.delete("/", headers=_cap(token)).status_code == 204
        assert client.delete("/", headers=_cap(token)).status_code == 204

    # INVARIANT: the reaper does not double-stop an already-stopped run. The topic is armed by
    # the disconnect, the window closes, and the `exists()` guard declines to act — so nothing is
    # counted as reaped and no second terminal frame is produced.
    _wait_until(lambda: _armed(client) == 1.0, "the topic to be armed")
    _wait_until(lambda: _armed(client) == 0.0, "the window to close")

    assert _reaped(client) == 0.0


def test_reaping_releases_the_concurrency_slot(
    single_slot: tuple[TestClient, _SpendingExecutor],
) -> None:
    # WHY this test: the capacity symptom is what actually got noticed in the field — orphaned
    # Evaluations filled every local slot and the next eval looked frozen until the whole stack
    # was restarted. Freeing the slot is half of what OME-890 buys.
    client, executor = single_slot
    first = _token(client)

    with client.websocket_connect(f"/ws?ticket={first}") as ws:
        _attach(ws, "attach-1")
        assert client.get("/?q=hello", headers=_async_start(first)).status_code == 202
        _wait_until(lambda: executor.calls > 0, "the run to issue its first model call")

        second = _token(client)
        with client.websocket_connect(f"/ws?ticket={second}") as ws2:
            _attach(ws2, "attach-2")
            # The single slot is taken by a run nobody is watching any more.
            assert client.get("/?q=hello", headers=_async_start(second)).status_code == 503

    _wait_until(lambda: _reaped(client) >= 1.0, "the abandoned run to be reaped")

    third = _token(client)
    with client.websocket_connect(f"/ws?ticket={third}") as ws3:
        _attach(ws3, "attach-3")
        recovered = client.get("/?q=hello", headers=_async_start(third))

    assert recovered.status_code == 202
