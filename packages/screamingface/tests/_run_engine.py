"""A stub Engine that drives Runs, for the Client's follow path (E5 P2 spec §4.1, §4.2).

It serves `POST /runs`, `GET /runs/{id}/events` (a WebSocket that plays a script), each
Candidate's result route and `DELETE /runs/{id}`, and records what the Client asked. A script is
one list of frames per connection; an int in it closes the socket with that code.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from _websocket_wire import cloudevent
from _websocket_wire import send_server_close as _send_close
from _websocket_wire import send_server_text_frame as _send_text

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
RUN_ID = "run_" + "f" * 32


@dataclass
class RunEngineState:
    connections: list[list[str | int]]
    results: dict[int, bytes]
    lock: threading.Lock = field(default_factory=threading.Lock)
    registered: list[dict[str, Any]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    followed: list[str] = field(default_factory=list)
    fetched: list[str] = field(default_factory=list)
    # Result fetches: the headers each carried, and how many to drop before answering.
    fetch_headers: list[dict[str, str]] = field(default_factory=list)
    drop_fetches: int = 0
    # A "hold" step sets `holding` and waits for `release` (bounded), keeping the stream open.
    holding: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    # A problem `POST /runs` answers with instead of registering: (status, code or None).
    refuse_create: tuple[int, str | None] | None = None
    # The headers each `POST /runs` and each events upgrade carried.
    post_headers: list[dict[str, str]] = field(default_factory=list)
    # `GET /runs/{id}`: the Run's state, and each Candidate's settled frame, by index, which the
    # read reports as the Candidate's state, attempt, error code and record.
    run_state: str = "complete"
    settled_by_index: dict[int, dict[str, Any]] = field(default_factory=dict)
    # The context `GET /runs/{id}/context` serves instead of the one sent, to test the check.
    served_context: str | None = None
    follow_headers: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class RunEngine:
    url: str
    state: RunEngineState


def run_id_of(registration: int) -> str:
    """The id of the stub's nth Run: the first is `RUN_ID`."""
    return RUN_ID if registration == 0 else f"run_{registration:032x}"


def topic(index: int) -> str:
    return f"url4-cloud.{index:032x}"


def event(index: int, sequence: int, body: str = "working") -> str:
    data = {"severity_text": "INFO", "severity_number": 9, "body": body}
    payload = cloudevent("ai.url4.log", data, sequence, subject=topic(index))
    return json.dumps({"type": "candidate.event", "index": index, "event": payload})


def state(index: int, value: str) -> str:
    return json.dumps({"type": "candidate.state", "index": index, "state": value})


def settled(
    index: int,
    body: bytes,
    *,
    state: str = "succeeded",
    error: object = None,
    attempt: str | None = None,
    **record_fields: object,
) -> str:
    """A settled frame; ``record_fields`` set the record's own fields (``capture_replay``…)."""
    record: dict[str, Any] = {
        "trace_id": f"{index:032x}",
        "started_at": "2026-11-14T09:00:00+00:00",
        "completed_at": "2026-11-14T09:00:04+00:00",
        "usage": None,
        "cache_hits": 0,
        "cache_unpriced_hits": None,
        "cache_saved_cost_usd": None,
        "cache_saved_cost_archive_usd": None,
        "frozen_copy_id": None,
        "capture_status": None,
        "capture_replay": None,
        "capture_partial_reasons": [],
        "client_version": None,
    }
    record.update(record_fields)
    if error is None:
        record["result"] = {
            "media_type": "application/json",
            "size_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
    else:
        record["error"] = error
    return json.dumps(
        {
            "type": "candidate.settled",
            "index": index,
            "state": state,
            "attempt_id": attempt or topic(index),
            "error_code": None,
            "record": record,
        }
    )


def ended(value: str = "complete") -> str:
    return json.dumps({"type": "run.ended", "state": value, "stopped_by": None})


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: object) -> None:  # noqa: ARG002 - stdlib handler API
        pass

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        state = self.server.state
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with state.lock:
            state.post_headers.append(dict(self.headers))
        if state.refuse_create is not None:
            status, code = state.refuse_create
            problem = {"type": "about:blank", "title": "refused", "status": status}
            if code is not None:
                problem["code"] = code
            payload = json.dumps(problem).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/problem+json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        with state.lock:
            state.registered.append(body)
            run_id = run_id_of(len(state.registered) - 1)
        self._json(
            HTTPStatus.CREATED,
            {
                "id": run_id,
                "state": "running",
                "created_at": "2026-11-14T09:00:00Z",
                "finished_at": None,
                "benchmark": body["benchmark"],
                "case_count": body["case_count"],
                "detached": body["detach"],
                "deadline_at": None,
                "stopped_by": None,
                "context": None,
                "candidates": [
                    {
                        "index": index,
                        "name": start["name"],
                        "state": "pending",
                        "attempt_id": None,
                        "started_at": None,
                        "finished_at": None,
                        "cost_usd": None,
                        "error_code": None,
                    }
                    for index, start in enumerate(body["candidates"])
                ],
            },
        )

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        with self.server.state.lock:
            self.server.state.deleted.append(urlsplit(self.path).path)
        self._json(HTTPStatus.ACCEPTED, {})

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlsplit(self.path).path
        if self.headers.get("Upgrade", "").casefold() == "websocket":
            self._follow(path)
        elif path.endswith("/context") or path.count("/") == 2:
            self._read_run(path)
        else:
            self._result(path)

    def _follow(self, path: str) -> None:
        state = self.server.state
        with state.lock:
            state.followed.append(path)
            state.follow_headers.append(dict(self.headers))
            script: Sequence[str | int] = state.connections.pop(0) if state.connections else [1011]
        self._accept()
        self._play(script)

    def _result(self, path: str) -> None:
        state = self.server.state
        with state.lock:
            state.fetched.append(path)
            state.fetch_headers.append(dict(self.headers))
            drop = state.drop_fetches > 0
            state.drop_fetches -= 1 if drop else 0
        if drop:
            # A reset: the connection ends with no answer.
            self.close_connection = True
            return
        body = state.results.get(int(path.rsplit("/", 2)[-2]))
        if body is None:
            self._json(HTTPStatus.NOT_FOUND, {"code": "result_not_found"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_run(self, path: str) -> None:
        state = self.server.state
        with state.lock:
            state.fetched.append(self.path)
            sent = state.registered[-1] if state.registered else None
        if sent is None:
            self._json(HTTPStatus.NOT_FOUND, {"code": "run_not_found"})
            return
        if path.endswith("/context"):
            body = (state.served_context or sent["context"] or "").encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        full = "view=summary" not in self.path
        context = sent["context"].encode() if sent["context"] else None
        candidates = []
        for index, start in enumerate(sent["candidates"]):
            frame = state.settled_by_index.get(index)
            candidate: dict[str, Any] = {
                "index": index,
                "name": start["name"],
                "state": "pending" if frame is None else frame["state"],
                "attempt_id": None if frame is None else frame["attempt_id"],
                "started_at": None,
                "finished_at": None,
                "cost_usd": None,
                "error_code": None if frame is None else frame["error_code"],
            }
            if full:
                candidate["start"] = start
                candidate["record"] = None if frame is None else frame["record"]
            candidates.append(candidate)
        self._json(
            HTTPStatus.OK,
            {
                "id": path.split("/")[2],
                "state": state.run_state,
                "created_at": "2026-11-14T09:00:00Z",
                "finished_at": None,
                "benchmark": sent["benchmark"],
                "case_count": sent["case_count"],
                "detached": sent["detach"],
                "deadline_at": None,
                "stopped_by": None,
                "context": None
                if context is None
                else {"sha256": hashlib.sha256(context).hexdigest(), "size_bytes": len(context)},
                "candidates": candidates,
            },
        )

    def _play(self, script: Sequence[str | int]) -> None:
        for item in script:
            if item == "hold":
                self.server.state.holding.set()
                self.server.state.release.wait(timeout=10)
                return
            if isinstance(item, int):
                _send_close(self.wfile, item)
                return
            if '"run.ended"' in item:
                self.server.state.run_state = json.loads(item)["state"]
            _send_text(self.wfile, item)
        _send_close(self.wfile, 1000)

    def _accept(self) -> None:
        key = self.headers["Sec-WebSocket-Key"]
        accept = base64.b64encode(hashlib.sha1(f"{key}{_WEBSOCKET_GUID}".encode()).digest())
        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept.decode())
        self.end_headers()
        self.close_connection = True

    def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: RunEngineState) -> None:
        super().__init__(address, _Handler)
        self.state = state


@contextmanager
def run_engine(
    connections: Sequence[Sequence[str | int]],
    results: dict[int, bytes],
    *,
    drop_fetches: int = 0,
    refuse_create: tuple[int, str | None] | None = None,
) -> Iterator[RunEngine]:
    # WHY copied: the stub pops each connection's script, and tests share module-level scripts.
    settled_frames = {
        frame["index"]: frame
        for script in connections
        for item in script
        if isinstance(item, str)
        and item.startswith("{")
        and (frame := json.loads(item)).get("type") == "candidate.settled"
    }
    state = RunEngineState(
        settled_by_index=settled_frames,
        connections=[list(script) for script in connections],
        results=dict(results),
        drop_fetches=drop_fetches,
        refuse_create=refuse_create,
    )
    server = _Server(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        yield RunEngine(url=f"http://{host!s}:{port}", state=state)
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()


class CollectingSink:
    """A `_RunSink` that keeps each Candidate's outcome, by index."""

    def __init__(self) -> None:
        self.outcomes: dict[int, Any] = {}
        self.events: list[tuple[int, Any]] = []

    def state(self, index: int, state: str) -> None:
        pass

    def event(self, index: int, event: Any) -> None:
        self.events.append((index, event))

    def settled(self, index: int, state: str, outcome: Any) -> None:
        self.outcomes[index] = outcome

    def connection(self, notice: Any) -> None:
        pass


class AsyncCollectingSink:
    """The async twin of ``CollectingSink``."""

    def __init__(self) -> None:
        self.outcomes: dict[int, Any] = {}
        self.events: list[tuple[int, Any]] = []

    async def state(self, index: int, state: str) -> None:
        pass

    async def event(self, index: int, event: Any) -> None:
        self.events.append((index, event))

    async def settled(self, index: int, state: str, outcome: Any) -> None:
        self.outcomes[index] = outcome

    def connection(self, notice: Any) -> None:
        pass


def one_candidate(body: bytes) -> tuple[list[list[str | int]], dict[int, bytes]]:
    """The script and results of a Run whose one Candidate succeeds with ``body``."""
    return [[state(0, "scheduled"), event(0, 1), settled(0, body), ended()]], {0: body}
