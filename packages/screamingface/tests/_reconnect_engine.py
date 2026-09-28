"""A scripted stub engine for reconnect-handshake scenarios (OME-1016 gaps).

The stub models the two engine facts a reconnect depends on:

- every `POST /token` mints a capability for a NEW topic (`rest/routes.py`:
  `codec.sign(new_topic(), ...)`), so only the capability that STARTED the Run can
  attach to its frames;
- a resume attach replays the topic's frames from `from_sequence`.

The first stream delivers frames 1..2 and then closes 1012 (a deploy). Every later
handshake takes the next entry of `reconnect_script`: an HTTP status to refuse the
handshake with, `"access"` for a Cloudflare Access challenge, or `"accept"`.
"""

from __future__ import annotations

import base64
import hashlib
import json
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

CANDIDATE_URL4 = "(@)!'hello'"
RESULT_BODY = "resumed-result"
_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_ACCESS_AUDIENCE = "a" * 32

type HandshakeStep = int | Literal["access", "accept"]


@dataclass
class StubState:
    reconnect_script: list[HandshakeStep]
    # How many times the accepted stream drops with 1012 before it completes the Run.
    drops: int = 1
    # The FIRST handshake's answer; "accept" starts the scenario.
    first_handshake: HandshakeStep = "accept"
    lock: threading.Lock = field(default_factory=threading.Lock)
    topics: dict[str, str] = field(default_factory=dict)
    started_topic: str | None = None
    handshake_tickets: list[str] = field(default_factory=list)
    resume_cursors: list[int | None] = field(default_factory=list)
    deletes: int = 0

    def mint(self) -> str:
        with self.lock:
            token = f"cap-{len(self.topics) + 1}"
            self.topics[token] = f"topic-{len(self.topics) + 1}"
            return token


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
        body = json.dumps({"token": self.server.state.mint()}).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        with self.server.state.lock:
            self.server.state.deletes += 1
        self._empty(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.headers.get("Upgrade", "").casefold() == "websocket":
            self._websocket()
            return
        state = self.server.state
        state.started_topic = state.topics[self.headers["URL4-Capability"]]
        self.send_response(HTTPStatus.ACCEPTED)
        self.send_header("Preference-Applied", "respond-async")
        self.send_header("Location", "/?topic=reconnect")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _websocket(self) -> None:
        state = self.server.state
        ticket = parse_qs(urlsplit(self.path).query)["ticket"][0]
        with state.lock:
            first = not state.handshake_tickets
            state.handshake_tickets.append(ticket)
            if first:
                step: HandshakeStep = state.first_handshake
            else:
                step = state.reconnect_script.pop(0) if state.reconnect_script else "accept"
        if step == "access":
            self._empty(HTTPStatus.FORBIDDEN, {"cf-access-aud": _ACCESS_AUDIENCE})
        elif isinstance(step, int):
            self._empty(HTTPStatus(step))
        else:
            self._accept()
            attach = json.loads(_read_client_text_frame(self.rfile))
            if first:
                self._serve_first_stream()
            else:
                self._serve_resume(ticket, attach["data"].get("from_sequence"))

    def _serve_first_stream(self) -> None:
        # The Run starts only after the first attach; wait for `GET /?q=`.
        for _ in range(500):
            if self.server.state.started_topic is not None:
                break
            threading.Event().wait(0.01)
        self._send_frames(1, 2)
        _send_close(self.wfile, 1012)

    def _serve_resume(self, ticket: str, cursor: int | None) -> None:
        state = self.server.state
        state.resume_cursors.append(cursor)
        if state.topics.get(ticket) != state.started_topic:
            # A capability for another topic sees none of this Run's frames: the real
            # engine would stream heartbeats forever. Refusing is the testable stand-in.
            _send_close(self.wfile, 1008)
            return
        with state.lock:
            state.drops -= 1
            drop_again = state.drops > 0
        if drop_again:
            _send_close(self.wfile, 1012)
        else:
            self._send_frames(cursor or 1, 5)

    def _send_frames(self, first: int, last: int) -> None:
        for sequence in range(first, last + 1):
            _send_text(self.wfile, json.dumps(_FRAMES[sequence](sequence)))

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

    def _empty(self, status: HTTPStatus, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _Server(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], state: StubState) -> None:
        super().__init__(address, _Handler)
        self.state = state


def _frame(kind: str, data: dict[str, object], sequence: int) -> dict[str, object]:
    return cloudevent(kind, data, sequence, subject="reconnect")


def _log(body: str) -> Any:
    return lambda sequence: _frame(
        "ai.url4.log",
        {"severity_text": "INFO", "severity_number": 9, "body": body},
        sequence,
    )


_FRAMES: dict[int, Any] = {
    1: lambda sequence: _frame("ai.url4.started", {"url4": CANDIDATE_URL4}, sequence),
    2: _log("before the deploy"),
    3: _log("after the deploy"),
    4: lambda sequence: _frame(
        "ai.url4.result", {"body": RESULT_BODY, "media_type": "application/json"}, sequence
    ),
    5: lambda sequence: _frame(
        "ai.url4.terminated", {"status": "succeeded", "error": None}, sequence
    ),
}


@contextmanager
def stub_engine(
    *reconnect_script: HandshakeStep, drops: int = 1, first: HandshakeStep = "accept"
) -> Iterator[StubEngine]:
    state = StubState(reconnect_script=list(reconnect_script), drops=drops, first_handshake=first)
    server = _Server(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        yield StubEngine(url=f"http://{host!s}:{port}", state=state)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def candidate() -> Candidate:
    return _compiled_candidate(
        name="opus",
        kind="model",
        models=("provider/opus",),
        url4=CANDIDATE_URL4,
        operations=(
            _compiled_operation(id="op_opus", kind="model", label="opus answer", depends_on=()),
        ),
    )
