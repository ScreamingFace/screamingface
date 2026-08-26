"""Characterization (OME-1017): today's run-control failures, pinned before R2–R4.

These tests record the INCIDENT behavior this epic removes:

1. An Engine that closes the run stream with WS close 1012 (Service Restart — exactly
   what a deployment rollout sends) kills the Run on the client: fatal
   `websocket_disconnected`, one connection attempt, no resume.
2. `cancel_active()` cannot stop a Run whose capability token the server rejects — the
   abort sweep's `DELETE /` 401s and the engine keeps spending (the orphan mechanism of
   the 2026-08-26 incident).
3. The evaluation-level abort path records that sweep failure as a note on the original
   error and the server-side Run continues.

R4 flips the first; R2 flips the second and third (the token then lives for the whole
Run, so the sweep's `DELETE /` succeeds).

Self-contained by design (sdlc rule 5): this stub serves only the scenarios above.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from screamingface._evaluation.model import (
    Candidate,
    _compiled_candidate,
    _compiled_operation,
)
from screamingface._evaluation.runner import _run_candidates_sync
from screamingface._engine.transport import Url4CloudTransport
from screamingface.errors import AuthenticationError, ExecutionError

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_CANDIDATE_URL4 = "(@)!'hello'"


@dataclass
class EngineState:
    close_code: int | None
    delete_rejected: bool = False
    attached: threading.Event = field(default_factory=threading.Event)
    started: threading.Event = field(default_factory=threading.Event)
    handshakes: int = 0
    minted_tokens: list[str] = field(default_factory=list)


@dataclass
class Engine:
    url: str
    state: EngineState


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # websockets refuses an HTTP/1.0 handshake

    def log_message(self, *_args: object) -> None:  # noqa: ARG002 - stdlib handler API
        pass

    def do_POST(self) -> None:  # noqa: N802 — stdlib handler API
        if urlsplit(self.path).path != "/token":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        state = self.server.state
        token = "tok_" + str(len(state.minted_tokens))
        state.minted_tokens.append(token)
        self._json(HTTPStatus.OK, {"token": token})

    def do_DELETE(self) -> None:  # noqa: N802 — stdlib handler API
        if self.server.state.delete_rejected:
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {
                    "type": "run_control",
                    "title": "Unauthorized",
                    "status": 401,
                    "detail": "missing, invalid, or expired capability token",
                },
                media_type="application/problem+json",
            )
            return
        self._no_content(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802 — stdlib handler API
        if self.headers.get("Upgrade", "").casefold() == "websocket":
            self._websocket()
        else:
            self._start()

    def _start(self) -> None:
        self.send_response(HTTPStatus.ACCEPTED)
        self.send_header("Preference-Applied", "respond-async")
        self.send_header("Location", "/?topic=run_resume")
        self.send_header("Content-Length", "0")
        self.end_headers()
        self.server.state.started.set()

    def _websocket(self) -> None:
        if not self._accept_websocket():
            return
        if not self._read_attach():
            return
        self.server.state.attached.set()
        if self.server.state.started.wait(timeout=5):
            self._send_close(self.server.state.close_code)

    def _accept_websocket(self) -> bool:
        self.server.state.handshakes += 1
        key = self.headers.get("Sec-WebSocket-Key")
        if key is None:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return False
        accept = base64.b64encode(
            hashlib.sha1(f"{key}{_WEBSOCKET_GUID}".encode()).digest()
        ).decode()
        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.send_header("Sec-WebSocket-Protocol", "cloudevents.json")
        self.end_headers()
        self.close_connection = True
        return True

    def _read_attach(self) -> bool:
        try:
            event = json.loads(_read_client_text_frame(self.rfile))
        except (AssertionError, IndexError, json.JSONDecodeError):
            return False
        return isinstance(event, dict) and event.get("type") == "ai.url4.attach"

    def _send_close(self, code: int) -> None:
        _send_server_close(self.wfile, code)

    def _json(
        self, status: HTTPStatus, value: object, *, media_type: str = "application/json"
    ) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _no_content(self, status: HTTPStatus, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _Server(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], state: EngineState) -> None:
        super().__init__(address, _Handler)
        self.state = state


def _read_client_text_frame(stream: Any) -> str:
    header = stream.read(2)
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", stream.read(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", stream.read(8))[0]
    mask = stream.read(4) if header[1] & 0x80 else b""
    payload = stream.read(length)
    if mask:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return payload.decode()


def _send_server_close(stream: Any, code: int) -> None:
    # RFC 6455 close frame: FIN + opcode 8, two-byte status. Server frames are unmasked.
    payload = struct.pack("!H", code)
    stream.write(bytes((0x88, len(payload))) + payload)
    stream.flush()


@contextmanager
def _engine(*, close_code: int | None, delete_rejected: bool = False) -> Iterator[Engine]:
    state = EngineState(close_code=close_code, delete_rejected=delete_rejected)
    server = _Server(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host = str(server.server_address[0])
        port = int(server.server_address[1])
        yield Engine(url=f"http://{host}:{port}", state=state)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _candidate() -> Candidate:
    return _compiled_candidate(
        name="opus",
        kind="model",
        models=("provider/opus",),
        url4=_CANDIDATE_URL4,
        operations=(
            _compiled_operation(id="op_opus", kind="model", label="opus answer", depends_on=()),
        ),
    )


def test_close_1012_mid_run_is_fatal_today() -> None:
    """PIN: an engine Service Restart (close 1012) kills the Run today.

    The client makes ONE connection attempt, surfaces `websocket_disconnected`, and never
    re-attaches. R4 flips this: the Run resumes from the JetStream cursor on a new socket.
    """
    with _engine(close_code=1012) as eng:
        transport = Url4CloudTransport(eng.url)
        try:
            with pytest.raises(ExecutionError) as caught:
                transport.run(_candidate(), None)
        finally:
            transport.close()
    assert caught.value.code == "websocket_disconnected"
    assert "1012" in str(caught.value)
    # One connection attempt, no resume: the fatal behavior R4 replaces.
    assert eng.state.handshakes == 1


def test_cancel_active_raises_when_delete_is_rejected() -> None:
    """PIN: the abort sweep cannot stop a Run whose capability the server rejects.

    `DELETE /` 401s — the capability is older than its 60 s window for a real long run —
    so `cancel_active()` raises and the engine keeps spending. R2 (long-lived capability)
    makes this `DELETE /` succeed for the whole Run life.
    """
    with _engine(close_code=1012, delete_rejected=True) as eng:
        transport = Url4CloudTransport(eng.url)
        try:
            # R4 changes this surface; today the sweep stops whatever is registered.
            transport._active_tokens.add("stale-capability")  # noqa: SLF001
            with pytest.raises(ExceptionGroup) as caught:
                transport.cancel_active()
        finally:
            transport.close()
    group = caught.value
    assert any(isinstance(error, AuthenticationError) for error in group.exceptions)


def test_abort_sweep_records_note_when_stop_rejected() -> None:
    """PIN: the evaluation abort path swallows a failed sweep as a note.

    Today's orphan mechanism: `_run_candidates_sync` catches any Run failure, calls
    `cancel_active()`, and — because the sweep itself raised (server rejected the stale
    capability) — records it as a note and re-raises the original error. The engine-side
    Run continues spending with no consumer.
    """

    class _FakeTransport:
        def __init__(self) -> None:
            self.cancel_calls = 0

        def run(self, candidate: Candidate, on_event: object = None) -> object:
            raise ExecutionError("Run stream lost", code="websocket_disconnected")

        def cancel_active(self) -> None:
            self.cancel_calls += 1
            raise RuntimeError("DELETE / failed with 401")

    fake = _FakeTransport()
    with pytest.raises(ExecutionError) as caught:
        _run_candidates_sync(fake, (_candidate(), _candidate()), None)  # type: ignore[arg-type]
    assert caught.value.code == "websocket_disconnected"
    assert any(
        "Stopping active SF Engine runs also failed" in note
        for note in getattr(caught.value, "__notes__", ())
    )
    assert fake.cancel_calls == 1
