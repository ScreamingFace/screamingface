"""ST-8: a real client disconnect during a streamed chat answer stops the run and deletes the blob.

FEATURE: OpenAI-compatible Engine API, unit U5 (prd/streaming.md ST-S8, test-plan ST-8).

WHY a real server: Starlette's StreamingResponse reads `receive()` to see the disconnect, so the
route must have no second reader of `receive()`. A fake disconnect flag cannot fail for that
reason; a real uvicorn server, a real HTTP client and a real TCP close can. The server runs in its
own thread on a free port of 127.0.0.1. No network beyond 127.0.0.1, no provider call: the
runner is a recording fake and the model is a URL4 recipe, so no model lookup runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
import uvicorn

from screamingface_engine.app import create_app
from screamingface_engine.artifacts.chat_inputs import chat_input_store
from screamingface_engine.chat.result import (
    CHAT_RESULT_MEDIA_TYPE,
    ChatResult,
    encode_chat_result,
)
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.protocol import (
    CostUsageEvent,
    ResultData,
    ResultEvent,
    TerminatedData,
    TerminatedEvent,
)
from url4.streaming.protocol.envelope import source_for
from url4.streaming.protocol.signals import CostUsageData
from url4.streaming.protocol.taxonomy import CostBreakdown, TokenUsage

SECRET = "chat-stream-disconnect-secret-0000000"
HEADERS = {"X-User-Email": "dev@example.com"}
# Plan D4 form: a URL4 recipe as `model`, so the route runs no model lookup.
RECIPE = "(model_1:0.0:/prov/a($input)!'')!'$model_1'"
BOUND_S = 10.0
KEEP_ALIVE = ": keep-alive"


class LockedObjects:
    """A thread-safe put/get blob backend in a dict, with a delete."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        with self._lock:
            self._objects[key] = data

    def get(self, key: str) -> bytes | None:
        with self._lock:
            return self._objects.get(key)

    def sweep(self, ttl_seconds: float, *, now: float | None = None) -> int:
        return 0

    def delete(self, key: str) -> None:
        with self._lock:
            self._objects.pop(key, None)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._objects)


class RecordingRunner:
    """Records each schedule and stop; it publishes nothing, so a run never ends by itself.

    The route stops a chat run with the bound stop inside a start attempt (review round 2, RR-S1),
    so the fake has both, as `tests/unit/_chat_app.py::ScriptedRunner` has.
    """

    def __init__(self) -> None:
        self.scheduled: list[str] = []
        self.stopped: list[str] = []
        self.loop: asyncio.AbstractEventLoop | None = None

    async def schedule(self, topic: str, url4: str, deadline_s: int, **kwargs: Any) -> str:
        self.loop = asyncio.get_running_loop()
        self.scheduled.append(topic)
        return f"job-{topic}"

    async def stop(self, topic: str) -> None:
        self.stopped.append(topic)

    async def stop_bound(self, topic: str) -> None:
        self.stopped.append(topic)

    @contextlib.contextmanager
    def start_attempt(self, topic: str) -> Iterator[None]:
        yield

    async def exists(self, topic: str) -> bool:
        return False

    async def status(self, topic: str) -> str:
        return "running"


@dataclass
class Served:
    """A running server, the fakes under its App, and the URL of the chat route."""

    url: str
    runner: RecordingRunner
    objects: LockedObjects
    stream: InMemoryEventStream


def _wait_until(check: Callable[[], bool]) -> bool:
    """Polls `check` every 0.02 s for up to BOUND_S; whether it became true."""
    end = time.monotonic() + BOUND_S
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return check()


@pytest.fixture
def served() -> Iterator[Served]:
    """The App on a real uvicorn server in its own thread, on a free port of 127.0.0.1."""
    runner, objects, stream = RecordingRunner(), LockedObjects(), InMemoryEventStream()
    app = create_app(
        Settings(jwt_secret=SECRET, chat_max_wait_s=60.0, chat_keepalive_s=0.05),
        stream=stream,
        job_runner=cast(Any, runner),
    )
    app.state.chat_input_store = chat_input_store(objects)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(
        app, lifespan="off", log_level="warning", http="h11", timeout_graceful_shutdown=5
    )
    server = uvicorn.Server(config)
    # WHY its own thread: uvicorn installs no signal handlers outside the main thread, so the
    # pytest main thread keeps its own.
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        assert _wait_until(lambda: server.started), "the server did not start"
        yield Served(f"http://127.0.0.1:{port}/v1/chat/completions", runner, objects, stream)
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        sock.close()
        assert not thread.is_alive(), "the server did not shut down"


def _request() -> dict[str, Any]:
    return {"model": RECIPE, "messages": [{"role": "user", "content": "Hi"}], "stream": True}


def _first_keep_alive(lines: Iterator[str]) -> bool:
    """Reads lines until the first keep-alive comment; whether one came."""
    return any(line == KEEP_ALIVE for line in lines)


def test_real_asgi_disconnect_during_stream_stops_run_and_deletes_blob(served: Served) -> None:
    """ST-8 (ST-S8): the client closes its connection mid-stream; the run stops, the blob goes."""
    with httpx.Client(timeout=BOUND_S) as client:
        with client.stream("POST", served.url, json=_request(), headers=HEADERS) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            assert _first_keep_alive(resp.iter_lines()), "the stream sent no keep-alive line"
            assert served.objects.keys(), "the chat input was not stored while the run works"
        # INVARIANT: leaving both blocks closes the unfinished response and the TCP connection.

    runner = served.runner
    assert len(runner.scheduled) == 1, "the route did not schedule exactly one run"
    topic = runner.scheduled[0]
    stopped = _wait_until(lambda: topic in runner.stopped)
    deleted = _wait_until(lambda: not served.objects.keys())

    assert stopped, "the run was not stopped after the client disconnected"
    assert deleted, f"the chat input was not deleted: {served.objects.keys()}"
    assert runner.stopped.count(topic) == 1, f"the run was stopped {runner.stopped.count(topic)}x"


def _answer_frames(topic: str) -> list[Any]:
    """The frames of an answered run: a subtree cost frame, the result, a succeeded end."""
    cost = CostUsageEvent(
        id=f"cost-{topic}",
        source=source_for(topic),
        subject=topic,
        data=CostUsageData(
            scope="subtree",
            provider="test",
            model="test-model",
            pricing_version="v1",
            usage=TokenUsage(input_tokens=10, output_tokens=4),
            cost=CostBreakdown(total_usd=Decimal("0.001")),
        ),
    )
    body = encode_chat_result(
        ChatResult(status="answered", content="Paris", finish_reason="stop")
    ).decode("utf-8")
    result = ResultEvent(
        id=f"res-{topic}",
        source=source_for(topic),
        subject=topic,
        data=ResultData(body=body, media_type=CHAT_RESULT_MEDIA_TYPE),
    )
    end = TerminatedEvent(
        id=f"term-{topic}",
        source=source_for(topic),
        subject=topic,
        data=TerminatedData(status="succeeded"),
    )
    return [cost, result, end]


def _publish_answer(served: Served) -> None:
    """Publishes the answered run's frames on the server's loop, from the test thread."""
    runner = served.runner
    loop = runner.loop
    assert loop is not None, "the run was not scheduled"
    topic = runner.scheduled[0]

    async def publish() -> None:
        for frame in _answer_frames(topic):
            await served.stream.publish(topic, frame)

    asyncio.run_coroutine_threadsafe(publish(), loop).result(timeout=BOUND_S)


def test_real_stream_ends_with_done_when_the_run_answers(served: Served) -> None:
    """ST-S8 control: a run that answers after the stream started ends with [DONE], blob gone."""
    data: list[str] = []
    with httpx.Client(timeout=BOUND_S) as client:
        with client.stream("POST", served.url, json=_request(), headers=HEADERS) as resp:
            assert resp.status_code == 200
            lines = resp.iter_lines()
            assert _first_keep_alive(lines), "the stream sent no keep-alive line"
            _publish_answer(served)
            data = [line for line in lines if line.startswith("data: ")]

    assert data, "the stream sent no data line"
    assert data[-1] == "data: [DONE]"
    assert any('"Paris"' in line for line in data), "the answer is not in the stream"
    assert _wait_until(lambda: not served.objects.keys()), "the chat input was not deleted"
    assert served.runner.stopped == [], "a run that ended was stopped"
