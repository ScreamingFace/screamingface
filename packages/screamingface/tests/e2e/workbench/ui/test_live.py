"""Live telemetry on the run page (unit 6 plan, Task 6; Review Focus 2 and 4).

``/runs/{id}/telemetry`` tails the run's ``spans.jsonl`` (the session receiver's) and every
notebook's ``events.jsonl`` while the run executes. These tests pin the three promises of the
plan: a half-written line is never shown, a disconnect releases the file handles, and the end of
the run ends the stream. Secrets on disk never reach the stream.
"""

from __future__ import annotations

import asyncio
import fcntl
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from workbench.ui import pages
from workbench.ui.app import create_app
from workbench.ui.live import JsonlTail, LiveTelemetry, model_call, stream
from workbench.ui.runs import Run, RunManager, RunRequest

KEY = "sk-or-v1-" + "a1b2c3d4" * 6  # token-shaped: the redactor masks it whole
TOKEN = "t0k3n-for-tests"
MODEL = "openrouter/microsoft/phi-4"


def _span(
    span_id: str,
    *,
    model: str | None = MODEL,
    input_tokens: int | None = 12,
    output_tokens: int | None = 3,
    cache: str | None = "hit",
    start: int = 1_000_000_000,
    end: int = 1_250_000_000,
    status: str = "ok",
    message: str = "",
    service: str = "screamingface-engine",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {"gen_ai.operation.name": "RelUrlNode"}
    if model is not None:
        attributes["gen_ai.request.model"] = model
    if input_tokens is not None:
        attributes["gen_ai.usage.input_tokens"] = input_tokens
    if output_tokens is not None:
        attributes["gen_ai.usage.output_tokens"] = output_tokens
    if cache is not None:
        attributes["url4.cache_status"] = cache
    return {
        "trace_id": "a" * 32,
        "span_id": span_id,
        "parent_span_id": None,
        "name": "/benchmarks/candidate",
        "kind": "internal",
        "start_ns": start,
        "end_ns": end,
        "status": {"code": status, "message": message},
        "service": service,
        "attributes": attributes | (extra or {}),
    }


def _usage(cost: str | None, scope: str = "self") -> dict[str, Any]:
    return {"kind": "usage", "scope": scope, "model": MODEL, "usage": {"cost_usd": cost}}


def _line(row: dict[str, Any]) -> str:
    return json.dumps(row) + "\n"


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


# --- JsonlTail: complete lines only ----------------------------------------------------------


def test_a_half_written_line_is_held_back_until_its_newline(tmp_path: Path) -> None:
    path = tmp_path / "spans.jsonl"
    whole = _line({"n": 1})
    tail = JsonlTail(path)
    try:
        assert tail.read() == []  # no file yet: nothing, no error
        for cut in (3, 7, len(whole) - 1):  # the writer flushes the line in pieces
            path.write_text(whole[:cut])
            assert tail.read() == []
        path.write_text(whole)
        assert tail.read() == [{"n": 1}]
        assert tail.read() == []
        assert tail.unreadable == 0
    finally:
        tail.close()


def test_a_torn_tail_is_never_shown_even_at_eof(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(_line({"n": 1}) + '{"n": 2, "body": "cut')
    tail = JsonlTail(path)
    try:
        assert tail.read() == [{"n": 1}]
        assert tail.read() == []
    finally:
        tail.close()


def test_unparseable_and_non_object_lines_are_skipped_and_counted(tmp_path: Path) -> None:
    path = tmp_path / "spans.jsonl"
    path.write_text("not json\n[1, 2]\n" + _line({"ok": True}) + "\n")
    tail = JsonlTail(path)
    try:
        assert tail.read() == [{"ok": True}]
        assert tail.unreadable == 2  # a blank line is not a line
    finally:
        tail.close()


def test_a_replaced_file_is_read_again_from_the_start(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(_line({"run": "old", "pad": "x" * 64}))
    tail = JsonlTail(path)
    try:
        assert tail.read() == [{"run": "old", "pad": "x" * 64}]
        path.unlink()  # prepare_bundle removes a previous run's file before the rerun
        path.write_text(_line({"run": "new"}))
        assert tail.read() == [{"run": "new"}]
    finally:
        tail.close()


def test_a_symlink_is_not_followed(tmp_path: Path) -> None:
    secret = tmp_path / "elsewhere.jsonl"
    secret.write_text(_line({"leak": True}))
    (tmp_path / "spans.jsonl").symlink_to(secret)
    tail = JsonlTail(tmp_path / "spans.jsonl")
    try:
        assert tail.read() == []
        assert not tail.opened
    finally:
        tail.close()


def test_an_overlong_line_is_skipped_counted_and_the_next_one_read(tmp_path: Path) -> None:
    path = tmp_path / "spans.jsonl"
    path.write_text('{"big": "' + "x" * 400 + '"}\n' + _line({"n": 2}))
    tail = JsonlTail(path, chunk=64, line_cap=128)
    try:
        rows: list[dict[str, Any]] = []
        for _ in range(20):
            rows += tail.read()
        assert rows == [{"n": 2}]
        assert tail.unreadable == 1
    finally:
        tail.close()


def test_reads_are_chunked_and_say_more_is_waiting(tmp_path: Path) -> None:
    path = tmp_path / "spans.jsonl"
    path.write_text("".join(_line({"n": i}) for i in range(50)))
    tail = JsonlTail(path, chunk=64)
    try:
        first = tail.read()
        assert 0 < len(first) < 50
        assert tail.more
        rows = list(first)
        while tail.more:
            rows += tail.read()
        assert [r["n"] for r in rows] == list(range(50))
    finally:
        tail.close()


def test_rows_beyond_the_cap_are_counted_never_silently_lost(tmp_path: Path) -> None:
    path = tmp_path / "spans.jsonl"
    path.write_text("".join(_line({"n": i}) for i in range(7)))
    tail = JsonlTail(path, rows_cap=5)
    try:
        assert len(tail.read()) == 5
        assert tail.over_cap == 2
    finally:
        tail.close()


def test_a_secret_on_disk_is_redacted_on_read(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(_line({"kind": "log", "body": f"provider said: bad key {KEY}"}))
    tail = JsonlTail(path)
    try:
        (row,) = tail.read()
        assert KEY not in json.dumps(row)
    finally:
        tail.close()


# --- model calls -----------------------------------------------------------------------------


def test_a_model_span_becomes_a_call_row() -> None:
    call = model_call(_span("1"))
    assert call is not None
    assert call.as_json() == {
        "service": "screamingface-engine",
        "name": "/benchmarks/candidate",
        "model": MODEL,
        "input_tokens": 12,
        "output_tokens": 3,
        "cache": "hit",
        "duration_ms": 250.0,
        "error": None,
    }


def test_a_span_without_a_model_is_not_a_call() -> None:
    assert model_call(_span("1", model=None)) is None


def test_unknown_fields_stay_unknown_never_zero() -> None:
    call = model_call(_span("1", input_tokens=None, output_tokens=None, cache=None, end=None))  # type: ignore[arg-type]
    assert call is not None
    row = call.as_json()
    assert (row["input_tokens"], row["output_tokens"], row["cache"], row["duration_ms"]) == (
        None,
        None,
        None,
        None,
    )


def test_a_long_span_name_is_shortened() -> None:
    span = _span("1") | {"name": "x" * 1000}
    call = model_call(span)
    assert call is not None
    assert len(call.name) <= 121


def test_a_failed_call_carries_its_error() -> None:
    call = model_call(_span("1", status="error", message="upstream 500"))
    assert call is not None
    assert call.error == "upstream 500"


# --- LiveTelemetry: a run's out dir ------------------------------------------------------------


def _out(tmp_path: Path) -> Path:
    out = tmp_path / "runs" / "20261022-120000-abcd"
    out.mkdir(parents=True)
    return out


def test_poll_reads_the_session_spans_and_every_notebook_events(tmp_path: Path) -> None:
    out = _out(tmp_path)
    _append(out / "spans.jsonl", _line(_span("1")) + _line(_span("2", model=None)))
    _append(out / "replay" / "quickstart" / "events.jsonl", _line(_usage("0.25")))
    live = LiveTelemetry(out, "replay")
    try:
        first = live.poll()
        assert [c.model for c in first.calls] == [MODEL]
        _append(out / "replay" / "judge-panel" / "events.jsonl", _line(_usage("0.5")))
        _append(
            out / "spans.jsonl", _line(_span("3", input_tokens=5, output_tokens=1, cache="miss"))
        )
        second = live.poll()
        assert [c.cache for c in second.calls] == ["miss"]
        counts = second.counts
        assert counts["events"] == 2
        assert counts["spans"] == 3
        assert counts["calls"] == 2
        assert (counts["input_tokens"], counts["output_tokens"]) == (17, 4)
        assert counts["cache_hits"] == 1
        assert counts["errors"] == 0
        assert counts["cost_usd"] == "0.75"
    finally:
        live.close()


def test_an_unknown_part_makes_a_total_unknown(tmp_path: Path) -> None:
    out = _out(tmp_path)
    _append(out / "spans.jsonl", _line(_span("1")) + _line(_span("2", input_tokens=None)))
    _append(
        out / "replay" / "quickstart" / "events.jsonl", _line(_usage("0.1")) + _line(_usage(None))
    )
    live = LiveTelemetry(out, "replay")
    try:
        counts = live.poll().counts
        assert counts["input_tokens"] is None
        assert counts["output_tokens"] == 6
        assert counts["cost_usd"] is None
    finally:
        live.close()


def test_a_subtree_usage_rollup_is_not_counted_twice(tmp_path: Path) -> None:
    out = _out(tmp_path)
    events = _line(_usage("0.25")) + _line(_usage("0.25", scope="subtree"))
    _append(out / "replay" / "quickstart" / "events.jsonl", events)
    live = LiveTelemetry(out, "replay")
    try:
        assert live.poll().counts["cost_usd"] == "0.25"
    finally:
        live.close()


def test_a_symlinked_notebook_dir_is_not_followed(tmp_path: Path) -> None:
    out = _out(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    _append(elsewhere / "events.jsonl", _line(_usage("9")))
    (out / "replay").mkdir()
    (out / "replay" / "quickstart").symlink_to(elsewhere)
    live = LiveTelemetry(out, "replay")
    try:
        assert live.poll().counts["events"] == 0
    finally:
        live.close()


# --- the SSE stream ----------------------------------------------------------------------------


def _frames(text: str) -> list[tuple[str, Any]]:
    """(event, data) of each SSE frame that has data; a frame without ``event:`` is message."""
    frames: list[tuple[str, Any]] = []
    for block in text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "data" in fields:
            frames.append((fields.get("event", "message"), json.loads(fields["data"])))
    return frames


async def _collect(chunks: AsyncIterator[str]) -> str:
    return "".join([chunk async for chunk in chunks])


@pytest.mark.asyncio
async def test_the_stream_ends_with_the_run_and_releases_its_files(tmp_path: Path) -> None:
    out = _out(tmp_path)
    _append(out / "spans.jsonl", _line(_span("1")))
    _append(out / "replay" / "quickstart" / "events.jsonl", _line(_usage("0.5")))
    live = LiveTelemetry(out, "replay")
    ended = False

    def is_ended() -> bool:
        return ended

    async def finish_soon() -> None:
        nonlocal ended
        await asyncio.sleep(0.05)
        _append(out / "spans.jsonl", _line(_span("2", cache="miss")))  # written before the end
        ended = True

    finisher = asyncio.create_task(finish_soon())
    text = await asyncio.wait_for(_collect(stream(live, is_ended, interval=0.01)), 5)
    await finisher
    frames = _frames(text)
    assert frames[0] == ("reset", {})
    assert [d["cache"] for e, d in frames if e == "call"] == ["hit", "miss"]  # none lost at the end
    assert frames[-1][0] == "end"
    counts = [d for e, d in frames if e == "counts"][-1]
    assert (counts["calls"], counts["events"], counts["cost_usd"]) == (2, 1, "0.5")
    assert live.open_files == 0


@pytest.mark.asyncio
async def test_a_half_written_line_never_reaches_the_stream(tmp_path: Path) -> None:
    out = _out(tmp_path)
    spans = out / "spans.jsonl"
    whole = _line(_span("1", extra={"note": "y" * 300}))
    live = LiveTelemetry(out, "replay")
    ended = False
    agen = stream(live, lambda: ended, interval=0.01)
    seen: list[str] = []
    try:
        seen.append(await agen.__anext__())  # retry
        seen.append(await agen.__anext__())  # reset
        seen.append(await agen.__anext__())  # the opening (all-zero) counts
        _append(spans, whole[:150])  # the receiver is mid-write
        pump = asyncio.ensure_future(agen.__anext__())
        done, _ = await asyncio.wait({pump}, timeout=0.2)
        assert not done, f"a torn line produced output: {pump.result() if done else ''}"
        _append(spans, whole[150:])
        seen.append(await asyncio.wait_for(pump, 5))
        ended = True
        seen += [chunk async for chunk in agen]
    finally:
        await agen.aclose()
    frames = _frames("".join(seen))
    calls = [d for e, d in frames if e == "call"]
    assert len(calls) == 1 and calls[0]["model"] == MODEL
    assert frames[-1][0] == "end"


@pytest.mark.asyncio
async def test_closing_the_stream_mid_run_releases_its_files(tmp_path: Path) -> None:
    out = _out(tmp_path)
    _append(out / "spans.jsonl", _line(_span("1")))
    _append(out / "replay" / "quickstart" / "events.jsonl", _line(_usage("0.5")))
    live = LiveTelemetry(out, "replay")
    agen = stream(live, lambda: False, interval=0.01)
    async for chunk in agen:
        if chunk.startswith("event: counts"):
            break
    assert live.open_files == 2  # both files are being followed
    await agen.aclose()  # what a server does when the browser goes away
    assert live.open_files == 0


@pytest.mark.asyncio
async def test_a_cancelled_stream_releases_its_files(tmp_path: Path) -> None:
    """Starlette cancels the streaming task on ``http.disconnect`` (ASGI spec < 2.4)."""
    out = _out(tmp_path)
    _append(out / "spans.jsonl", _line(_span("1")))
    live = LiveTelemetry(out, "replay")
    agen = stream(live, lambda: False, interval=10)

    async def drain() -> None:
        async for _ in agen:
            pass

    task = asyncio.create_task(drain())
    for _ in range(100):
        if live.open_files:
            break
        await asyncio.sleep(0.01)
    assert live.open_files == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert live.open_files == 0


@pytest.mark.asyncio
async def test_a_quiet_stream_sends_keepalives(tmp_path: Path) -> None:
    live = LiveTelemetry(_out(tmp_path), "replay")
    agen = stream(live, lambda: False, interval=0.01, keepalive=0.05)
    try:
        chunks = [await asyncio.wait_for(agen.__anext__(), 5) for _ in range(4)]
    finally:
        await agen.aclose()
    assert any(c.startswith(":") for c in chunks)


@pytest.mark.asyncio
async def test_no_secret_reaches_the_stream(tmp_path: Path) -> None:
    out = _out(tmp_path)
    leaky = _span("1", status="error", message=f"401 for key {KEY}", extra={"x": KEY})
    leaky["name"] = f"POST /v1?api_key={KEY}"
    _append(out / "spans.jsonl", _line(leaky))
    log = {"kind": "log", "body": f"retrying with {KEY}"}
    _append(out / "replay" / "quickstart" / "events.jsonl", _line(log))
    live = LiveTelemetry(out, "replay")
    text = await asyncio.wait_for(_collect(stream(live, lambda: True, interval=0.01)), 5)
    assert KEY not in text
    assert "[REDACTED]" in text  # the call row is still shown, masked


@pytest.mark.asyncio
async def test_frames_cannot_be_forged_by_a_value(tmp_path: Path) -> None:
    out = _out(tmp_path)
    _append(out / "spans.jsonl", _line(_span("1", model="m\n\nevent: end\ndata: {}")))
    live = LiveTelemetry(out, "replay")
    text = await asyncio.wait_for(_collect(stream(live, lambda: True, interval=0.01)), 5)
    assert [e for e, _ in _frames(text)].count("end") == 1


# --- the route and the run page -----------------------------------------------------------------

_LIVE_SCRIPT = """
import json, os, pathlib, sys, time
out = pathlib.Path(os.environ["SCREAMINGFACE_WORKBENCH_OUT"])
span = json.loads(sys.argv[1])
(out / "spans.jsonl").write_text(json.dumps(span) + "\\n")
nb = out / "replay" / "quickstart"
nb.mkdir(parents=True)
(nb / "events.jsonl").write_text(json.dumps({"kind": "usage", "scope": "self",
    "model": "m", "usage": {"cost_usd": "0.5"}}) + "\\n")
print("wrote", flush=True)
time.sleep(float(sys.argv[2]))
"""


def _spawner(sleep: float) -> Callable[[list[str], dict[str, str], Path], subprocess.Popen[str]]:
    def spawn(argv: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen[str]:
        script = [sys.executable, "-c", _LIVE_SCRIPT, json.dumps(_span("1")), str(sleep)]
        return subprocess.Popen(
            script,
            env=env,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

    return spawn


def _manager(tmp_path: Path, sleep: float) -> RunManager:
    root = tmp_path / "out"
    root.mkdir(exist_ok=True)
    return RunManager(
        root, workdir=tmp_path, environ={}, spawn=_spawner(sleep), interrupt_grace=5.0
    )


def _wait_for(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.02)


def test_the_route_streams_a_live_run_to_its_end(tmp_path: Path) -> None:
    manager = _manager(tmp_path, sleep=0.3)
    app = create_app(
        root=tmp_path / "out", manager=manager, token=TOKEN, port=9187, notebooks=("quickstart",),
        default_data_dir=tmp_path, telemetry_interval=0.02,
    )  # fmt: skip
    client = TestClient(app, base_url="http://127.0.0.1:9187")
    run = manager.start(RunRequest("replay", ()))
    try:
        _wait_for(lambda: (run.out_dir / "replay" / "quickstart" / "events.jsonl").exists())
        with client.stream("GET", f"/runs/{run.id}/telemetry") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-store"
            frames = _frames("".join(response.iter_text()))
        assert [d["model"] for e, d in frames if e == "call"] == [MODEL]
        assert frames[-1][0] == "end"
        assert run.returncode is not None
    finally:
        manager.shutdown()


def test_the_route_is_404_for_an_unknown_or_past_run(tmp_path: Path) -> None:
    manager = _manager(tmp_path, sleep=0)
    app = create_app(
        root=tmp_path / "out", manager=manager, token=TOKEN, port=9187, notebooks=(),
        default_data_dir=tmp_path,
    )  # fmt: skip
    client = TestClient(app, base_url="http://127.0.0.1:9187")
    (tmp_path / "out" / "runs" / "20261022-120000-abcd").mkdir(parents=True)
    assert client.get("/runs/20261022-120000-abcd/telemetry").status_code == 404
    assert client.get("/runs/../../etc/telemetry").status_code == 404


def test_the_running_page_has_the_live_telemetry_table(tmp_path: Path) -> None:
    run = Run("20261022-120000-abcd", RunRequest("replay", ()), tmp_path)
    page = pages.run_page(run, [], token=None)
    assert 'data-telemetry="/runs/20261022-120000-abcd/telemetry"' in page
    assert re.search(r"<th>model</th>.*<th>in</th>.*<th>out</th>.*<th>cache</th>", page)
    assert "<th>duration</th>" in page
    for key in ("calls", "input_tokens", "output_tokens", "cache_hits", "cost_usd", "spans"):
        assert f'data-k="{key}"' in page
    assert "innerHTML" not in page  # rows are built with textContent only


def test_a_finished_run_page_has_no_live_telemetry(tmp_path: Path) -> None:
    run = Run("20261022-120000-abcd", RunRequest("replay", ()), tmp_path, returncode=0)
    page = pages.run_page(run, [], token=None)
    assert "data-telemetry" not in page
    assert "Telemetry section" in page  # points at the bundles for the full picture


# --- a real server: the browser goes away --------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    assert port not in {9105, 9106, 9108, 9112}
    return port


def _fds_on(path: Path) -> int:
    """Open descriptors of THIS process on ``path`` (macOS F_GETPATH, Linux /proc)."""
    target, count = os.path.realpath(path), 0
    for name in os.listdir("/dev/fd"):
        try:
            if sys.platform == "darwin":
                raw = fcntl.fcntl(int(name), fcntl.F_GETPATH, bytes(1024))  # pyright: ignore[reportAttributeAccessIssue]
                where = raw.rstrip(b"\0").decode()
            else:
                where = os.readlink(f"/proc/self/fd/{name}")
        except (OSError, ValueError):
            continue
        count += os.path.realpath(where) == target
    return count


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[int, RunManager]]:
    port = _free_port()
    manager = _manager(tmp_path, sleep=60)
    app = create_app(
        root=tmp_path / "out", manager=manager, token=TOKEN, port=port, notebooks=(),
        default_data_dir=tmp_path, telemetry_interval=0.02,
    )  # fmt: skip
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_for(lambda: server.started)
    try:
        yield port, manager
    finally:
        manager.shutdown()
        server.should_exit = True
        thread.join(10)


def test_a_browser_that_goes_away_releases_the_file_handles(
    served: tuple[int, RunManager],
) -> None:
    port, manager = served
    run = manager.start(RunRequest("replay", ()))
    spans = run.out_dir / "spans.jsonl"
    _wait_for(lambda: (run.out_dir / "replay" / "quickstart" / "events.jsonl").exists())
    baseline = _fds_on(spans)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", f"/runs/{run.id}/telemetry")
    response = conn.getresponse()
    assert response.status == 200
    seen = b""
    while b"event: call" not in seen:
        seen += response.read1(4096)
    _wait_for(lambda: _fds_on(spans) == baseline + 1)  # the stream follows the file
    response.close()
    conn.close()  # the browser tab closes
    _wait_for(lambda: _fds_on(spans) == baseline, timeout=5)
    assert run.returncode is None  # the run itself goes on
