"""Controlled SF Engine protocol server for public Client contract tests."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


@dataclass
class ProtocolState:
    """Observable protocol behavior, independent from Client internals."""

    attached: threading.Event = field(default_factory=threading.Event)
    started: threading.Event = field(default_factory=threading.Event)
    two_started: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    inbound_events: list[dict[str, Any]] = field(default_factory=list)
    minted_tokens: list[str] = field(default_factory=list)
    started_tokens: list[str] = field(default_factory=list)
    deleted_tokens: list[str] = field(default_factory=list)
    stop_events: dict[str, threading.Event] = field(default_factory=dict)
    http_auth_schemes: list[str | None] = field(default_factory=list)
    websocket_auth_scheme: str | None = None
    start_attempts: int = 0
    # OME-967: the `traceparent` observed on each inbound leg, as (phase, value) with phase
    # one of "mint" | "start" | "websocket". Observable protocol behavior like the auth
    # schemes above — the client is meant to originate trace context, and only the wire can
    # say whether it did.
    traceparents: list[tuple[str, str | None]] = field(default_factory=list)
    mode: Literal[
        "success",
        "advisory_error",
        "heartbeat",
        "unsequenced_log",
        "http_stop",
        "delayed_attach",
        "stop",
        "gap",
        "disconnect",
        "token_invalid_json",
        "token_malformed",
        "missing_preference",
        "missing_location",
        "start_error",
        "start_auth_error",
        "stream_failed",
        "artifact_result",
    ] = "success"
    # OME-892 artifact mode: the result frame carries a claim ticket for `artifact_body`;
    # `/artifacts/{id}` serves `artifact_served` when set (corruption seam), else the true
    # bytes, or 404 when `artifact_missing`. Fetches are recorded as (path, capability).
    artifact_body: str = "[test] " + "A" * 2048
    artifact_served: bytes | None = None
    artifact_missing: bool = False
    artifact_fail_first: int = 0
    artifact_requests: list[tuple[str, str | None]] = field(default_factory=list)
    # OME-892 incident seam: real capability tokens live ~60 s while a run takes an hour,
    # so every token minted BEFORE the result frame streamed is expired by redemption
    # time. With this flag on, streaming the result expires all tokens minted so far and
    # `/artifacts/{id}` 401s them — redemption succeeds only with a freshly minted token.
    artifact_token_expiry: bool = False
    expired_tokens: list[str] = field(default_factory=list)

    def mint_token(self) -> str:
        with self.lock:
            token = f"test-capability-{len(self.minted_tokens) + 1}"
            self.minted_tokens.append(token)
            self.stop_events[token] = threading.Event()
            return token

    def record_traceparent(self, phase: str, value: str | None) -> None:
        with self.lock:
            self.traceparents.append((phase, value))

    def trace_ids(self) -> set[str]:
        """The distinct trace ids seen on the wire — the middle field of a `traceparent`."""
        with self.lock:
            return {value.split("-")[1] for _, value in self.traceparents if value}

    def mark_started(self, token: str) -> None:
        with self.lock:
            self.started_tokens.append(token)
            if len(self.started_tokens) >= 2:
                self.two_started.set()

    def mark_deleted(self, token: str) -> None:
        with self.lock:
            self.deleted_tokens.append(token)
            stopped = self.stop_events.get(token)
        if stopped is not None:
            stopped.set()

    def wait_until_deleted(self, token: str, timeout: float) -> bool:
        with self.lock:
            stopped = self.stop_events.get(token)
        return stopped.wait(timeout) if stopped is not None else False


@dataclass(frozen=True)
class ProtocolServer:
    url: str
    state: ProtocolState


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: ProtocolState) -> None:
        self.state = state
        super().__init__(address, _Handler)


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 — stdlib handler API
        self.server.state.http_auth_schemes.append(_authorization_scheme(self.headers))
        self.server.state.record_traceparent("mint", self.headers.get("traceparent"))
        if self.path != "/token":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.server.state.mode == "token_invalid_json":
            self._raw(HTTPStatus.OK, b"not-json", media_type="application/json")
            return
        if self.server.state.mode == "token_malformed":
            self._json(HTTPStatus.OK, {"ticket": "not-a-token"})
            return
        self._json(HTTPStatus.OK, {"token": self.server.state.mint_token()})

    def do_GET(self) -> None:  # noqa: N802 — stdlib handler API
        if self.headers.get("Upgrade", "").casefold() == "websocket":
            self._websocket()
        elif urlsplit(self.path).path.startswith("/artifacts/"):
            self._artifact()
        else:
            self._start()

    def _artifact(self) -> None:
        state = self.server.state
        with state.lock:
            state.artifact_requests.append((self.path, self.headers.get("URL4-Capability")))
            transient_failure = state.artifact_fail_first > 0
            if transient_failure:
                state.artifact_fail_first -= 1
        if transient_failure:
            # A mid-transfer reset, not a clean HTTP error: shut the socket down hard so
            # the client sees the drop IMMEDIATELY (close() alone leaves httpx waiting
            # out its read timeout), then close — the transient the retry must survive.
            import socket as _socket

            self.connection.shutdown(_socket.SHUT_RDWR)
            self.connection.close()
            return
        with state.lock:
            expired = (
                state.artifact_token_expiry
                and self.headers.get("URL4-Capability") in state.expired_tokens
            )
        if expired:
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {
                    "type": "about:blank",
                    "title": "Unauthorized",
                    "status": HTTPStatus.UNAUTHORIZED,
                    "detail": "missing, invalid, or expired capability token",
                },
                media_type="application/problem+json",
            )
            return
        if state.artifact_missing:
            self._json(
                HTTPStatus.NOT_FOUND,
                {
                    "type": "about:blank",
                    "title": "Unknown artifact",
                    "status": HTTPStatus.NOT_FOUND,
                    "detail": "no artifact is stored under that id",
                },
                media_type="application/problem+json",
            )
            return
        payload = (
            state.artifact_served
            if state.artifact_served is not None
            else state.artifact_body.encode("utf-8")
        )
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _start(self) -> None:
        self.server.state.start_attempts += 1
        query = parse_qs(urlsplit(self.path).query)
        if urlsplit(self.path).path != "/" or "q" not in query:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not self.server.state.attached.is_set():
            self._json(
                HTTPStatus.PRECONDITION_REQUIRED,
                {
                    "type": "about:blank",
                    "title": "Precondition Required",
                    "status": HTTPStatus.PRECONDITION_REQUIRED,
                    "detail": "Attach a WebSocket to the topic before starting the run.",
                },
                media_type="application/problem+json",
            )
            return
        self.server.state.record_traceparent("start", self.headers.get("traceparent"))
        if self._reject_start():
            return
        self.send_response(HTTPStatus.ACCEPTED)
        if self.server.state.mode != "missing_preference":
            self.send_header("Preference-Applied", "respond-async")
        if self.server.state.mode != "missing_location":
            self.send_header("Location", "/?topic=run_1")
        self.send_header("Content-Length", "0")
        self.end_headers()
        self.server.state.started.set()
        token = self.headers.get("URL4-Capability")
        if token is not None:
            self.server.state.mark_started(token)

    def _reject_start(self) -> bool:
        if self.server.state.mode == "start_error":
            self._json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "type": "runner_unavailable",
                    "title": "Runner unavailable",
                    "status": HTTPStatus.BAD_GATEWAY,
                    "detail": "The test runner is unavailable.",
                },
                media_type="application/problem+json",
            )
            return True
        if self.server.state.mode == "start_auth_error":
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {
                    "type": "capability_expired",
                    "title": "Capability expired",
                    "status": HTTPStatus.UNAUTHORIZED,
                    "detail": "The execution capability expired.",
                },
                media_type="application/problem+json",
            )
            return True
        return False

    def do_DELETE(self) -> None:  # noqa: N802 — stdlib handler API
        token = self.headers.get("URL4-Capability")
        if token is not None:
            self.server.state.mark_deleted(token)
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _json(
        self,
        status: HTTPStatus,
        value: object,
        *,
        media_type: str = "application/json",
    ) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _raw(self, status: HTTPStatus, body: bytes, *, media_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _websocket(self) -> None:
        if not self._accept_websocket():
            return
        event = self._receive_event()
        if event is None:
            return
        self.server.state.inbound_events.append(event)
        if event.get("type") != "ai.url4.attach":
            return
        if self.server.state.mode == "delayed_attach":
            time.sleep(0.05)
        self.server.state.attached.set()
        if self.server.state.started.wait(timeout=2):
            query = parse_qs(urlsplit(self.path).query)
            token = query.get("ticket", [""])[0]
            self._stream_run(token)

    def _accept_websocket(self) -> bool:
        self.server.state.websocket_auth_scheme = _authorization_scheme(self.headers)
        self.server.state.record_traceparent("websocket", self.headers.get("traceparent"))
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

    def _receive_event(self) -> dict[str, Any] | None:
        try:
            value = json.loads(_read_client_text_frame(self.rfile))
        except (AssertionError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _stream_run(self, token: str) -> None:
        mode = self.server.state.mode
        handlers: dict[str, Callable[[], None]] = {
            "stop": self._stream_stop,
            "http_stop": lambda: self._stream_http_stop(token),
            "disconnect": self._stream_disconnect,
            "gap": self._stream_gap,
            "stream_failed": self._stream_failed,
        }
        handler = handlers.get(mode)
        if handler is not None:
            handler()
        else:
            self._stream_events(mode)

    def _stream_disconnect(self) -> None:
        _send_server_text_frame(self.wfile, json.dumps(_run_frames()[0]))

    def _stream_events(self, mode: str) -> None:
        if mode == "heartbeat":
            _send_server_text_frame(self.wfile, json.dumps(_heartbeat()))
        elif mode == "advisory_error":
            _send_server_text_frame(self.wfile, json.dumps(_advisory_error()))
        elif mode == "unsequenced_log":
            _send_server_text_frame(self.wfile, json.dumps(_unsequenced_log()))
        frames = (
            _artifact_run_frames(self.server.state.artifact_body)
            if mode == "artifact_result"
            else _run_frames()
        )
        for frame in frames:
            _send_server_text_frame(self.wfile, json.dumps(frame))
        state = self.server.state
        if state.artifact_token_expiry:
            # The run is over: every token minted so far is now older than the real
            # engine's 60 s capability TTL — redemption must present a fresh mint.
            with state.lock:
                state.expired_tokens.extend(state.minted_tokens)

    def _stream_stop(self) -> None:
        _send_server_text_frame(self.wfile, json.dumps(_run_frames()[0]))
        event = self._receive_event()
        if event is not None:
            self.server.state.inbound_events.append(event)

    def _stream_http_stop(self, token: str) -> None:
        _send_server_text_frame(self.wfile, json.dumps(_run_frames()[0]))
        self.server.state.wait_until_deleted(token, timeout=0.5)
        _send_server_text_frame(
            self.wfile,
            json.dumps(
                _frame(
                    "ai.url4.terminated",
                    {"status": "stopped", "error": None},
                    2,
                )
            ),
        )

    def _stream_gap(self) -> None:
        frames = _gap_frames()
        for frame in frames[:2]:
            _send_server_text_frame(self.wfile, json.dumps(frame))
        event = self._receive_event()
        if event is not None:
            self.server.state.inbound_events.append(event)
        for frame in frames[2:]:
            _send_server_text_frame(self.wfile, json.dumps(frame))

    def _stream_failed(self) -> None:
        for _ in range(4):
            _send_server_text_frame(self.wfile, json.dumps(_stream_failed()))
            event = self._receive_event()
            if event is not None:
                self.server.state.inbound_events.append(event)


def _read_client_text_frame(stream: Any) -> str:
    first, second = stream.read(2)
    if first & 0x0F != 1 or not second & 0x80:
        raise AssertionError("expected one masked WebSocket text frame")
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", stream.read(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", stream.read(8))[0]
    mask = stream.read(4)
    payload = stream.read(length)
    return bytes(value ^ mask[index % 4] for index, value in enumerate(payload)).decode()


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


def _run_frames() -> tuple[dict[str, object], ...]:
    return (
        _frame("ai.url4.started", {"url4": "(@)!'hello'"}, 1),
        _frame(
            "ai.url4.cost.usage",
            {
                "scope": "subtree",
                "gen_ai.provider.name": "test",
                "gen_ai.response.model": "provider/opus",
                "pricing_version": "test",
                "usage": {
                    "gen_ai.usage.input_tokens": 10,
                    "gen_ai.usage.output_tokens": 2,
                    "gen_ai.usage.cache_read_tokens": 0,
                    "gen_ai.usage.cache_creation_tokens": 0,
                    "gen_ai.usage.reasoning_tokens": 0,
                },
                "cost": {
                    "input_usd": "0.01",
                    "output_usd": "0.02",
                    "cache_read_usd": "0",
                    "cache_creation_usd": "0",
                    "reasoning_usd": "0",
                    "total_usd": "0.03",
                },
            },
            2,
        ),
        _frame(
            "ai.url4.result",
            {"body": "[test] done", "media_type": "text/plain"},
            3,
        ),
        _frame(
            "ai.url4.terminated",
            {"status": "succeeded", "error": None},
            4,
        ),
    )


def _artifact_run_frames(artifact_body: str) -> tuple[dict[str, object], ...]:
    """The success run, but the result frame carries a claim ticket (OME-892)."""
    encoded = artifact_body.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    frames = list(_run_frames())
    frames[2] = _frame(
        "ai.url4.result",
        {
            "body": None,
            "media_type": None,
            "artifact": {"id": digest, "size_bytes": len(encoded), "sha256": digest},
        },
        3,
    )
    return tuple(frames)


def _gap_frames() -> tuple[dict[str, object], ...]:
    success = _run_frames()
    usage = dict(success[1])
    usage["sequence"] = "3"
    usage["id"] = "event_3"
    result = dict(success[2])
    result["sequence"] = "4"
    result["id"] = "event_4"
    terminated = dict(success[3])
    terminated["sequence"] = "5"
    terminated["id"] = "event_5"
    replayed = _frame(
        "ai.url4.log",
        {
            "severity_number": 9,
            "severity_text": "INFO",
            "body": "replayed",
            "attributes": {},
        },
        2,
    )
    return success[0], usage, replayed, usage, result, terminated


def _frame(kind: str, data: dict[str, object], sequence: int) -> dict[str, object]:
    return {
        "specversion": "1.0",
        "id": f"event_{sequence}",
        "source": "/trace/run_1/node/root",
        "subject": "run_1",
        "time": datetime.now(UTC).isoformat(),
        "type": kind,
        "datacontenttype": "application/json",
        "sequence": str(sequence),
        "sequencetype": "Integer",
        "data": data,
    }


def _heartbeat() -> dict[str, object]:
    return {
        "specversion": "1.0",
        "id": "heartbeat",
        "source": "/trace/run_1",
        "subject": "run_1",
        "time": datetime.now(UTC).isoformat(),
        "type": "ai.url4.heartbeat",
        "datacontenttype": "application/json",
        "data": {},
    }


def _unsequenced_log() -> dict[str, object]:
    """An out-of-band control-plane notice, in the shape url4-cloud really emits.

    Reproduced from ``screamingface_engine.notices.warn`` through ``url4.streaming.codec.encode``:
    both emitters (the re-attach cache-policy warning in ``ws/bridge.py`` and the
    cache-control override in ``rest/routes.py``) bypass the broker sequencer, and ``encode``
    does not pass ``exclude_none`` — so the sequence keys are PRESENT and null rather than
    omitted, which a hand-written fixture would get wrong.
    """

    return {
        "specversion": "1.0",
        "id": "notice_1",
        "source": "/trace/run_1",
        "subject": "run_1",
        "time": datetime.now(UTC).isoformat(),
        "datacontenttype": "application/json",
        "dataschema": None,
        "sequence": None,
        "sequencetype": None,
        "traceparent": None,
        "tracestate": None,
        "type": "ai.url4.log",
        "data": {
            "severity_number": 13,
            "severity_text": "WARN",
            "body": "the run's cache policy is fixed by its first attach",
            "attributes": {"cache.declared": "not stated", "cache.effective": "not stated"},
        },
    }


def _advisory_error() -> dict[str, object]:
    return {
        "specversion": "1.0",
        "id": "advisory_error",
        "source": "/trace/run_1",
        "subject": "run_1",
        "time": datetime.now(UTC).isoformat(),
        "type": "ai.url4.error",
        "datacontenttype": "application/json",
        "data": {
            "code": "invalid_frame",
            "message": "ignored malformed client frame",
            "ref_id": None,
        },
    }


def _stream_failed() -> dict[str, object]:
    frame = _advisory_error()
    frame["id"] = "stream_failed"
    frame["data"] = {
        "code": "stream_failed",
        "message": "the topic subscription failed (ServerError); re-attach to resume",
        "ref_id": None,
    }
    return frame


def _authorization_scheme(headers: Any) -> str | None:
    value = headers.get("Authorization")
    if value:
        return value.split(" ", 1)[0]
    return "Cf-Access-Token" if headers.get("Cf-Access-Token") else None


@contextmanager
def protocol_server(
    *,
    mode: Literal[
        "success",
        "advisory_error",
        "heartbeat",
        "unsequenced_log",
        "http_stop",
        "delayed_attach",
        "stop",
        "gap",
        "disconnect",
        "token_invalid_json",
        "token_malformed",
        "missing_preference",
        "missing_location",
        "start_error",
        "start_auth_error",
        "stream_failed",
        "artifact_result",
    ] = "success",
    artifact_body: str | None = None,
    artifact_served: bytes | None = None,
    artifact_missing: bool = False,
    artifact_fail_first: int = 0,
    artifact_token_expiry: bool = False,
) -> Iterator[ProtocolServer]:
    state = ProtocolState(
        mode=mode,
        artifact_served=artifact_served,
        artifact_missing=artifact_missing,
        artifact_fail_first=artifact_fail_first,
        artifact_token_expiry=artifact_token_expiry,
    )
    if artifact_body is not None:
        state.artifact_body = artifact_body
    server = _Server(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host = str(server.server_address[0])
        port = int(server.server_address[1])
        yield ProtocolServer(url=f"http://{host}:{port}", state=state)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
