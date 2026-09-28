"""A stub engine that serves SEVERAL Runs at once, for run-isolation scenarios.

Spec: `docs/spec/2026-09-28-sdk-run-isolation.md`. The stub models the engine facts that
isolation depends on:

- every `POST /token` mints a capability for a NEW topic, and `DELETE /` stops only the
  topic of the capability it carries (spec E1) — so the stub records WHICH capability each
  stop named;
- a `503` on `GET /?q=` schedules nothing (spec E3), so a start may be sent again.

Each Run follows the `RunPlan` of its Candidate URL4. The first stream either completes
(optionally held open on an event, so a test can fail a sibling while this Run is still
mid-stream) or drops with 1012. Every later handshake takes the next step of the plan's
`reconnects` script: an HTTP status to refuse it with, `"drop"` to accept and close 1012 at
once, or `"accept"` to resume from the client's cursor and complete.
"""

from __future__ import annotations

import base64
import hashlib
import json
import select
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from _websocket_wire import cloudevent
from _websocket_wire import read_client_text_frame as _read_client_text_frame
from _websocket_wire import send_server_close as _send_close
from _websocket_wire import send_server_text_frame as _send_text

from screamingface._evaluation.model import Candidate, _compiled_candidate, _compiled_operation

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
# WHY bounded: a stub thread that waits forever turns a failing test into a hung CI job.
_WAIT_S = 10.0

type Step = int | Literal["accept", "drop"]


@dataclass
class RunPlan:
    first: Literal["complete", "drop"] = "complete"
    reconnects: list[Step] = field(default_factory=list)
    # Answers to `GET /?q=` before the 202: (status, Retry-After header or None).
    admission: list[tuple[int, str | None]] = field(default_factory=list)
    # A completing stream sends frames 1..2, then waits for this event before 3..5.
    hold: threading.Event | None = None
    # The result travels as an artifact claim ticket; its fetch waits for `artifact_hold`.
    artifact: bool = False
    artifact_hold: threading.Event | None = None


@dataclass
class StubState:
    plans: dict[str, RunPlan]
    lock: threading.Lock = field(default_factory=threading.Lock)
    topics: dict[str, str] = field(default_factory=dict)  # capability -> topic
    started: dict[str, str] = field(default_factory=dict)  # topic -> Candidate URL4
    start_attempts: dict[str, int] = field(default_factory=dict)  # URL4 -> GET /?q= count
    handshakes: dict[str, int] = field(default_factory=dict)  # capability -> count
    deleted: list[str] = field(default_factory=list)  # capabilities named by DELETE /
    delete_status: HTTPStatus = HTTPStatus.NO_CONTENT
    artifact_requested: threading.Event = field(default_factory=threading.Event)
    # Capabilities whose client sent an in-band `ai.url4.stop` after the terminal frame.
    stop_frames: list[str] = field(default_factory=list)

    def mint(self) -> str:
        with self.lock:
            token = f"cap-{len(self.topics) + 1}"
            self.topics[token] = f"topic-{len(self.topics) + 1}"
            return token

    def capability_of(self, url4: str) -> str | None:
        """The capability that STARTED the Run of `url4`, once it started."""
        with self.lock:
            for token, topic in self.topics.items():
                if self.started.get(topic) == url4:
                    return token
        return None


@dataclass
class StubEngine:
    url: str
    state: StubState


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"  # websockets refuses an HTTP/1.0 handshake

    def log_message(self, *_args: object) -> None:  # noqa: ARG002 - stdlib handler API
        pass

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if urlsplit(self.path).path != "/token":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._json(HTTPStatus.OK, {"token": self.server.state.mint()})

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        with self.server.state.lock:
            self.server.state.deleted.append(self.headers["URL4-Capability"])
        self._empty(self.server.state.delete_status)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.headers.get("Upgrade", "").casefold() == "websocket":
            self._websocket()
            return
        path = urlsplit(self.path).path
        if path.startswith("/artifacts/"):
            self._artifact()
            return
        self._start()

    def _start(self) -> None:
        state = self.server.state
        url4 = parse_qs(urlsplit(self.path).query)["q"][0]
        plan = state.plans[url4]
        with state.lock:
            state.start_attempts[url4] = state.start_attempts.get(url4, 0) + 1
            answer = plan.admission.pop(0) if plan.admission else None
        if answer is not None:
            status, retry_after = answer
            headers = {} if retry_after is None else {"Retry-After": retry_after}
            self._json(
                HTTPStatus(status),
                {
                    "type": "about:blank",
                    "title": "Service Unavailable",
                    "status": status,
                    "detail": "the runner is at capacity — retry shortly",
                },
                content_type="application/problem+json",
                headers=headers,
            )
            return
        with state.lock:
            state.started[state.topics[self.headers["URL4-Capability"]]] = url4
        self.send_response(HTTPStatus.ACCEPTED)
        self.send_header("Preference-Applied", "respond-async")
        self.send_header("Location", "/?topic=isolation")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _artifact(self) -> None:
        state = self.server.state
        state.artifact_requested.set()
        plan = next(plan for plan in state.plans.values() if plan.artifact)
        if plan.artifact_hold is not None:
            plan.artifact_hold.wait(_WAIT_S)
        body = ARTIFACT_BODY.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _websocket(self) -> None:
        state = self.server.state
        ticket = parse_qs(urlsplit(self.path).query)["ticket"][0]
        with state.lock:
            state.handshakes[ticket] = state.handshakes.get(ticket, 0) + 1
            first = state.handshakes[ticket] == 1
        if first:
            self._accept()
            _read_client_text_frame(self.rfile)
            self._serve_first_stream(ticket)
            return
        plan = state.plans[state.started[state.topics[ticket]]]
        with state.lock:
            step: Step = plan.reconnects.pop(0) if plan.reconnects else "accept"
        if isinstance(step, int):
            self._empty(HTTPStatus(step))
            return
        self._accept()
        attach = json.loads(_read_client_text_frame(self.rfile))
        if step == "drop":
            _send_close(self.wfile, 1012)
        else:
            self._send_frames(ticket, attach["data"].get("from_sequence") or 1, 5)

    def _serve_first_stream(self, ticket: str) -> None:
        # The Run starts only after the first attach (and after any admission refusals).
        state = self.server.state
        topic = state.topics[ticket]
        for _ in range(int(_WAIT_S / 0.01)):
            if topic in state.started:
                break
            # A client that gives up before the start (an owner abort) closes the socket;
            # answer its close at once, as the engine does, instead of sitting on it.
            readable, _, _ = select.select([self.connection], [], [], 0.01)
            if readable:
                _send_close(self.wfile, 1000)
                return
        else:
            _send_close(self.wfile, 1011)
            return
        plan = state.plans[state.started[topic]]
        self._send_frames(ticket, 1, 2)
        if plan.first == "drop":
            _send_close(self.wfile, 1012)
            return
        if plan.hold is not None:
            plan.hold.wait(_WAIT_S)
        self._send_frames(ticket, 3, 5)
        self._record_client_reply(ticket)

    def _record_client_reply(self, ticket: str) -> None:
        """Read what the client sends after the terminal frame: a stop, or its close."""
        self.connection.settimeout(_WAIT_S)
        try:
            header = self.rfile.read(2)
            length = header[1] & 0x7F
            if length == 126:
                length = int.from_bytes(self.rfile.read(2), "big")
            elif length == 127:
                length = int.from_bytes(self.rfile.read(8), "big")
            mask = self.rfile.read(4) if header[1] & 0x80 else b""
            payload = bytes(
                byte ^ mask[index % 4] for index, byte in enumerate(self.rfile.read(length))
            )
        except (OSError, IndexError):
            return
        if header[0] & 0x0F == 0x1 and b"ai.url4.stop" in payload:
            with self.server.state.lock:
                self.server.state.stop_frames.append(ticket)

    def _send_frames(self, ticket: str, first: int, last: int) -> None:
        state = self.server.state
        topic = state.topics[ticket]
        url4 = state.started[topic]
        plan = state.plans[url4]
        for sequence in range(first, last + 1):
            frame = _frame_for(sequence, topic=topic, url4=url4, artifact=plan.artifact)
            _send_text(self.wfile, json.dumps(frame))

    def _accept(self) -> None:
        key = self.headers["Sec-WebSocket-Key"]
        accept = base64.b64encode(hashlib.sha1(f"{key}{_WEBSOCKET_GUID}".encode()).digest())
        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept.decode())
        self.send_header("Sec-WebSocket-Protocol", "cloudevents.json")
        self.end_headers()
        self.close_connection = True

    def _json(
        self,
        status: HTTPStatus,
        payload: dict[str, object],
        *,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: StubState) -> None:
        super().__init__(address, _Handler)
        self.state = state


ARTIFACT_BODY = '{"artifact": "complete"}'


def result_body(url4: str) -> str:
    """The inline result a completing Run of `url4` returns."""
    return f"result of {url4}"


def _frame_for(sequence: int, *, topic: str, url4: str, artifact: bool) -> dict[str, Any]:
    kinds: dict[int, tuple[str, dict[str, object]]] = {
        1: ("ai.url4.started", {"url4": url4}),
        2: ("ai.url4.log", {"severity_text": "INFO", "severity_number": 9, "body": "working"}),
        3: ("ai.url4.log", {"severity_text": "INFO", "severity_number": 9, "body": "more"}),
        4: ("ai.url4.result", _result_data(url4, artifact=artifact)),
        5: ("ai.url4.terminated", {"status": "succeeded", "error": None}),
    }
    kind, data = kinds[sequence]
    return cloudevent(kind, data, sequence, subject=topic)


def _result_data(url4: str, *, artifact: bool) -> dict[str, object]:
    if not artifact:
        return {"body": result_body(url4), "media_type": "text/plain"}
    payload = ARTIFACT_BODY.encode()
    digest = hashlib.sha256(payload).hexdigest()
    ticket = {"id": digest, "sha256": digest, "size_bytes": len(payload)}
    return {"artifact": ticket, "media_type": "application/json"}


@contextmanager
def isolation_engine(
    plans: dict[str, RunPlan], *, delete_status: HTTPStatus = HTTPStatus.NO_CONTENT
) -> Iterator[StubEngine]:
    state = StubState(plans=plans, delete_status=delete_status)
    server = _Server(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        yield StubEngine(url=f"http://{host!s}:{port}", state=state)
    finally:
        # Release every held stream so no handler thread outlives the test.
        for plan in plans.values():
            for event in (plan.hold, plan.artifact_hold):
                if event is not None:
                    event.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def candidate(name: str) -> Candidate:
    """A compiled Candidate whose URL4 selects its `RunPlan` (`url4_of(name)`)."""
    return _compiled_candidate(
        name=name,
        kind="model",
        models=("provider/opus",),
        url4=url4_of(name),
        operations=(
            _compiled_operation(id=f"op_{name}", kind="model", label="answer", depends_on=()),
        ),
    )


def url4_of(name: str) -> str:
    return f"(@)!'{name}'"
