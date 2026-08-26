"""Run-resume behavior: characterization (OME-1017) flipped by the OME-1020 reconnect loop.

History of this file:

- OME-1017 pinned the INCIDENT behavior: close 1012 mid-Run was fatal
  (`websocket_disconnected`, one connection attempt) and the abort sweep's `DELETE /`
  401'd on a capability older than 60 s, orphaning paid Runs.
- OME-1018 made the capability live for the whole Run (16 h + 1 h).
- OME-1020 (spec §6 S3) added the reconnect state machine. The 1012 pin FLIPS here: a
  Service Restart is now a recoverable disconnect — the client backs off (full jitter,
  bounded budget) and resumes from the stream cursor; only budget exhaustion or a typed
  `stream_reclaimed` ends the Run.

Self-contained by design (sdlc rule 5): the stub serves exactly these scenarios.
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
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

import pytest

from screamingface._evaluation.model import (
    Candidate,
    _compiled_candidate,
    _compiled_operation,
)
from screamingface._evaluation.runner import _run_candidates_sync
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface.errors import AuthenticationError, ExecutionError

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_CANDIDATE_URL4 = "(@)!'hello'"

Mode = Literal["restart", "reclaim_after_restart", "always_1012"]


@dataclass
class EngineState:
    mode: Mode
    delete_rejected: bool = False
    attached: threading.Event = field(default_factory=threading.Event)
    started: threading.Event = field(default_factory=threading.Event)
    handshakes: int = 0
    deletes: int = 0
    minted_tokens: list[str] = field(default_factory=list)
    resume_from: int | None = None


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
        self.server.state.deletes += 1
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
        state = self.server.state
        state.handshakes += 1
        if not self._accept_websocket():
            return
        attach = self._read_attach()
        if attach is None:
            return
        from_sequence = attach.get("from_sequence")
        if not state.started.wait(timeout=5):
            return
        if state.handshakes == 1:
            # First connection: deliver frames 1..2, then the deploy-style restart (1012).
            _send_server_text_frame(
                self.wfile, json.dumps(_frame("ai.url4.started", {"url4": _CANDIDATE_URL4}, 1))
            )
            _send_server_text_frame(
                self.wfile, json.dumps(_frame("ai.url4.log", {"severity_text": "INFO", "severity_number": 9, "body": "working"}, 2))
            )
            _send_server_close(self.wfile, 1012)
            return
        # Reconnect: record the resume cursor the client asked for.
        state.resume_from = from_sequence
        if state.mode == "reclaim_after_restart":
            _send_server_text_frame(
                self.wfile,
                json.dumps(_error_frame("stream_reclaimed", "the run's stream was reclaimed")),
            )
            return
        if state.mode == "always_1012":
            _send_server_text_frame(
                self.wfile, json.dumps(_frame("ai.url4.log", {"severity_text": "INFO", "severity_number": 9, "body": "still going"}, 3))
            )
            _send_server_close(self.wfile, 1012)
            return
        # restart: complete the run from the resume point.
        _send_server_text_frame(
            self.wfile,
            json.dumps(
                _frame("ai.url4.result", {"body": "restart-result", "media_type": "application/json"}, 3)
            ),
        )
        _send_server_text_frame(
            self.wfile,
            json.dumps(_frame("ai.url4.terminated", {"status": "succeeded", "error": None}, 4)),
        )

    def _accept_websocket(self) -> bool:
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

    def _read_attach(self) -> dict[str, object] | None:
        """Parse the client's attach frame; None ONLY on an unparseable frame.

        A FRESH attach (`from_sequence` absent/None) is a valid attach — returning it as a
        dict is what distinguishes it from a parse failure.
        """
        try:
            event = json.loads(_read_client_text_frame(self.rfile))
        except (AssertionError, IndexError, json.JSONDecodeError):
            return None
        if not isinstance(event, dict) or event.get("type") != "ai.url4.attach":
            return None
        data = event.get("data")
        return data if isinstance(data, dict) else {}

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


def _frame(kind: str, data: dict[str, object], sequence: int) -> dict[str, object]:
    return {
        "specversion": "1.0",
        "id": f"event_{sequence}",
        "source": "/trace/run_resume/node/root",
        "subject": "run_resume",
        "time": datetime.now(UTC).isoformat(),
        "type": kind,
        "datacontenttype": "application/json",
        "sequence": str(sequence),
        "sequencetype": "Integer",
        "data": data,
    }


def _error_frame(code: str, message: str) -> dict[str, object]:
    # Advisory frames carry no broker sequence (spec §6 S2, OME-1019).
    return {
        "specversion": "1.0",
        "id": "err_reclaimed",
        "source": "/trace/run_resume/node/root",
        "subject": "run_resume",
        "time": datetime.now(UTC).isoformat(),
        "type": "ai.url4.error",
        "datacontenttype": "application/json",
        "data": {"code": code, "message": message},
    }


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


def _send_server_text_frame(stream: Any, value: str) -> None:
    payload = value.encode()
    if len(payload) < 126:
        header = bytes((0x81, len(payload)))
    elif len(payload) < 65536:
        header = bytes((0x81, 126)) + struct.pack("!H", len(payload))
    else:
        header = bytes((0x81, 127)) + struct.pack("!Q", len(payload))
    stream.write(header + payload)
    stream.flush()


def _send_server_close(stream: Any, code: int) -> None:
    # RFC 6455 close frame: FIN + opcode 8, two-byte status. Server frames are unmasked.
    payload = struct.pack("!H", code)
    stream.write(bytes((0x88, len(payload))) + payload)
    stream.flush()


@contextmanager
def _engine(
    *, mode: Mode, delete_rejected: bool = False
) -> Iterator[Engine]:
    state = EngineState(mode=mode, delete_rejected=delete_rejected)
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


def test_restart_resumes_from_cursor_and_completes() -> None:
    """OME-1020 (spec §6 S3): a deploy-style restart is RECOVERABLE.

    First connection receives frames 1..2, then the server closes 1012 (Service Restart).
    The client re-attaches with `from_sequence = 3` (last accepted 2 + 1) on a NEW socket,
    replays the missed frames, and returns the normal Report.
    """
    with _engine(mode="restart") as eng:
        transport = Url4CloudTransport(eng.url)
        try:
            outcome = transport.run(_candidate(), None)
        finally:
            transport.close()
    assert outcome.result_body == "restart-result"
    assert eng.state.handshakes == 2
    assert eng.state.resume_from == 3


def test_reclaimed_stream_after_restart_is_run_result_lost() -> None:
    """OME-1019+1020: a stream reclaimed while we were away is FINAL.

    The Run finished and the Runner deleted the stream (grace elapsed). The engine answers
    the resume attach with `stream_reclaimed`; the client raises `run_result_lost`,
    permanent — reconnecting cannot change that.
    """
    with _engine(mode="reclaim_after_restart") as eng:
        transport = Url4CloudTransport(eng.url)
        try:
            with pytest.raises(ExecutionError) as caught:
                transport.run(_candidate(), None)
        finally:
            transport.close()
    assert caught.value.code == "run_result_lost"
    assert caught.value.permanent is True
    assert eng.state.resume_from == 3


def test_reconnect_budget_exhaustion_sweeps_then_fails() -> None:
    """FLIP of the OME-1017 pin: a persistently-restarting engine is not fatal at once.

    The client backs off and retries within its budget, then — with the budget spent —
    stops every Run it owns (the `DELETE /` sweep, which the long-lived token makes
    succeed) and surfaces `websocket_disconnected`.
    """
    with _engine(mode="always_1012") as eng:
        transport = Url4CloudTransport(
            eng.url, reconnect_budget_s=0.3, reconnect_base_delay_s=0.01
        )
        try:
            with pytest.raises(ExecutionError) as caught:
                transport.run(_candidate(), None)
        finally:
            transport.close()
    assert caught.value.code == "websocket_disconnected"
    assert eng.state.handshakes >= 2  # it tried to reconnect, not one-shot fatal
    assert eng.state.deletes >= 1  # the sweep's DELETE reached the engine


@pytest.mark.asyncio
async def test_async_restart_resumes_from_cursor_and_completes() -> None:
    """The async twin resumes identically from the stream cursor."""
    with _engine(mode="restart") as eng:
        transport = AsyncUrl4CloudTransport(eng.url)
        try:
            outcome = await transport.run(_candidate(), None)
        finally:
            await transport.close()
    assert outcome.result_body == "restart-result"
    assert eng.state.resume_from == 3


def test_cancel_active_raises_when_delete_is_rejected() -> None:
    """PIN (OME-1017, still true): the sweep raises when the server rejects the DELETE.

    R2 makes this impossible for real long runs (the token now lives for the whole Run),
    so this pins the RESULT the sweep must not produce: an un-stoppable Run surfaces as
    an error, not as silent continued spend.
    """
    with _engine(mode="always_1012", delete_rejected=True) as eng:
        transport = Url4CloudTransport(eng.url)
        try:
            transport._active_tokens.add("stale-capability")  # noqa: SLF001
            with pytest.raises(ExceptionGroup) as caught:
                transport.cancel_active()
        finally:
            transport.close()
    group = caught.value
    assert any(isinstance(error, AuthenticationError) for error in group.exceptions)


def test_abort_sweep_records_note_when_stop_rejected() -> None:
    """PIN (OME-1017, still honored): the evaluation abort path records a failed sweep
    as a note on the original error."""

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
