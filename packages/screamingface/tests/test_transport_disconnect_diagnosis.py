"""Why a Run stream drops, and the two drops the Client used to cause itself.

Every cause of a lost Run stream reaches the researcher as one message — an oversized
result frame, a proxy draining a listener, a rolled Pod, a refused capability. These pin
the two the Client is responsible for, plus the diagnostic that tells the other two apart.

Self-contained by design (sdlc rule 5): the Engine stub here serves only these three
scenarios rather than extending the shared protocol server.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

import screamingface as sf
from screamingface._engine.auth_base import _TransportAuth
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface._evaluation.model import (
    Candidate,
    _compiled_candidate,
    _compiled_operation,
)

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_CANDIDATE_URL4 = "(@)!'hello'"

ENGINE_RESULT_CAP_BYTES = 1_048_576
"""`screamingface_engine.runner.executor.Url4Executor.result_cap` — the largest body the Engine
emits.

The Engine truncates a result body to exactly this, then wraps it in a CloudEvent envelope,
so the frame on the wire is ALWAYS larger than the cap. A Client whose frame limit equals
the cap can therefore never receive a capped result.
"""

Mode = Literal["oversize_result", "access_challenge", "abrupt_disconnect"]


@dataclass
class EngineState:
    mode: Mode
    attached: threading.Event = field(default_factory=threading.Event)
    started: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    minted_tokens: list[str] = field(default_factory=list)
    handshakes: int = 0
    challenged_tokens: list[str] = field(default_factory=list)
    """Capabilities that already existed when Access challenged.

    url4-cloud refuses these on the retry: `iat_window_s` is 60s while `reauthenticate()`
    runs a browser login worth up to 300s, so a capability minted before the challenge is
    always expired by the time the retry presents it. Modelled by identity rather than a
    clock — the retry must present a capability that did not exist at challenge time.
    """

    def mint(self) -> str:
        with self.lock:
            token = f"diag-capability-{len(self.minted_tokens) + 1}"
            self.minted_tokens.append(token)
            return token


@dataclass(frozen=True)
class Engine:
    url: str
    state: EngineState


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: EngineState) -> None:
        self.state = state
        super().__init__(address, _Handler)


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_POST(self) -> None:  # noqa: N802 — stdlib handler API
        if urlsplit(self.path).path != "/token":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._json(HTTPStatus.OK, {"token": self.server.state.mint()})

    def do_DELETE(self) -> None:  # noqa: N802 — stdlib handler API
        self._no_content(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802 — stdlib handler API
        if self.headers.get("Upgrade", "").casefold() == "websocket":
            self._websocket()
        else:
            self._start()

    def _start(self) -> None:
        state = self.server.state
        if not state.attached.is_set():
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
        self.send_response(HTTPStatus.ACCEPTED)
        self.send_header("Preference-Applied", "respond-async")
        self.send_header("Location", "/?topic=run_diag")
        self.send_header("Content-Length", "0")
        self.end_headers()
        state.started.set()

    def _websocket(self) -> None:
        if self.server.state.mode == "access_challenge" and self._refuse_handshake():
            return
        if not self._accept_websocket():
            return
        if not self._read_attach():
            return
        self.server.state.attached.set()
        if self.server.state.started.wait(timeout=5):
            self._stream()

    def _refuse_handshake(self) -> bool:
        """The two ways url4-cloud refuses a WebSocket before ever accepting it."""
        state = self.server.state
        state.handshakes += 1
        if state.handshakes == 1:
            # Cloudflare Access challenges an unauthenticated handshake.
            with state.lock:
                state.challenged_tokens = list(state.minted_tokens)
            self._no_content(HTTPStatus.FORBIDDEN, {"cf-access-aud": "a" * 32})
            return True
        ticket = parse_qs(urlsplit(self.path).query).get("ticket", [""])[0]
        if ticket in state.challenged_tokens:
            # ws/endpoint.py: an unverifiable ticket is close(1008) before accept, which
            # reaches the Client as a plain handshake refusal.
            self._no_content(HTTPStatus.FORBIDDEN)
            return True
        return False

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

    def _read_attach(self) -> bool:
        try:
            event = json.loads(_read_client_text_frame(self.rfile))
        except (AssertionError, IndexError, json.JSONDecodeError):
            return False
        return isinstance(event, dict) and event.get("type") == "ai.url4.attach"

    def _stream(self) -> None:
        if self.server.state.mode == "abrupt_disconnect":
            # The socket vanishes mid-Run with no close handshake, exactly as a drained
            # proxy listener or an evicted Pod leaves it.
            _send_server_text_frame(self.wfile, json.dumps(_run_frames("unused")[0]))
            return
        body = (
            "x" * ENGINE_RESULT_CAP_BYTES
            if self.server.state.mode == "oversize_result"
            else "[diag] done"
        )
        for frame in _run_frames(body):
            _send_server_text_frame(self.wfile, json.dumps(frame))

    def _json(self, status: HTTPStatus, value: object, *, media_type: str = "application/json"):
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


def _frame(kind: str, data: dict[str, object], sequence: int) -> dict[str, object]:
    return {
        "specversion": "1.0",
        "id": f"event_{sequence}",
        "source": "/trace/run_diag/node/root",
        "subject": "run_diag",
        "time": datetime.now(UTC).isoformat(),
        "type": kind,
        "datacontenttype": "application/json",
        "sequence": str(sequence),
        "sequencetype": "Integer",
        "data": data,
    }


def _run_frames(body: str) -> tuple[dict[str, object], ...]:
    return (
        _frame("ai.url4.started", {"url4": _CANDIDATE_URL4}, 1),
        _frame("ai.url4.result", {"body": body, "media_type": "application/json"}, 2),
        _frame("ai.url4.terminated", {"status": "succeeded", "error": None}, 3),
    )


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


@contextmanager
def engine(*, mode: Mode) -> Iterator[Engine]:
    state = EngineState(mode=mode)
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


class _StubAccessAuth(_TransportAuth):
    """Caller auth whose reauthentication always succeeds, counting its invocations.

    Stands in for the Cloudflare Access browser flow. What decides the contract below is
    not how long that flow takes but which capability the Client presents afterwards.
    """

    def __init__(self) -> None:
        self.reauthentications = 0

    def auth_flow(self, request: httpx.Request):  # type: ignore[override]
        yield request

    def reauthenticate(self, *, timeout: float = 300.0) -> None:
        self.reauthentications += 1

    async def reauthenticate_async(self, *, timeout: float = 300.0) -> None:
        self.reauthentications += 1

    def websocket_headers(self) -> dict[str, str]:
        return {}

    async def websocket_headers_async(self) -> dict[str, str]:
        return {}

    def close(self) -> None:
        return None


def test_a_result_at_the_engine_cap_reaches_the_researcher() -> None:
    # STORY: as a researcher evaluating a few hundred Cases, my Report is large and it
    # arrives. Before this the Client's frame limit was EXACTLY the Engine's body cap, so
    # the envelope around a capped body always overflowed it: the Client refused the frame
    # with close 1009 and every large Evaluation died as `websocket_disconnected`.
    with engine(mode="oversize_result") as stub:
        with closing(Url4CloudTransport(stub.url, reconnect_budget_s=0.2, reconnect_base_delay_s=0.01)) as transport:
            outcome = transport.run(_candidate(), None)

    assert outcome.result_body is not None
    assert len(outcome.result_body.encode()) == ENGINE_RESULT_CAP_BYTES


@pytest.mark.asyncio
async def test_a_result_at_the_engine_cap_reaches_an_async_researcher() -> None:
    with engine(mode="oversize_result") as stub:
        transport = AsyncUrl4CloudTransport(stub.url, reconnect_budget_s=0.2, reconnect_base_delay_s=0.01)
        try:
            outcome = await transport.run(_candidate(), None)
        finally:
            await transport.close()

    assert outcome.result_body is not None
    assert len(outcome.result_body.encode()) == ENGINE_RESULT_CAP_BYTES


def test_an_access_challenge_retries_with_a_freshly_minted_capability() -> None:
    # STORY: as a researcher on a hosted Engine, my Run survives being asked to log in
    # again. Before this the retry re-presented the capability minted BEFORE the challenge;
    # a 60s capability cannot outlive a 300s browser login, so the Engine refused the
    # handshake and the whole Evaluation failed on a successful login.
    auth = _StubAccessAuth()
    with engine(mode="access_challenge") as stub:
        with closing(Url4CloudTransport(stub.url, auth, reconnect_budget_s=0.2, reconnect_base_delay_s=0.01)) as transport:
            outcome = transport.run(_candidate(), None)

    assert auth.reauthentications == 1
    assert len(stub.state.minted_tokens) == 2
    assert outcome.result_body == "[diag] done"


@pytest.mark.asyncio
async def test_an_access_challenge_retries_with_a_fresh_capability_when_async() -> None:
    auth = _StubAccessAuth()
    with engine(mode="access_challenge") as stub:
        transport = AsyncUrl4CloudTransport(stub.url, auth, reconnect_budget_s=0.2, reconnect_base_delay_s=0.01)
        try:
            outcome = await transport.run(_candidate(), None)
        finally:
            await transport.close()

    assert auth.reauthentications == 1
    assert len(stub.state.minted_tokens) == 2
    assert outcome.result_body == "[diag] done"


def test_a_dropped_stream_reports_its_close_code_and_elapsed_time() -> None:
    # STORY: as the engineer on call, the error tells me WHICH drop this was. An oversized
    # frame (1009), a drained proxy (1006), a rolled Pod (1001) and a refused capability
    # all read identically otherwise, which is what made these causes indistinguishable in
    # production for weeks.
    with engine(mode="abrupt_disconnect") as stub:
        with closing(Url4CloudTransport(stub.url, reconnect_budget_s=0.2, reconnect_base_delay_s=0.01)) as transport:
            with pytest.raises(sf.ExecutionError) as caught:
                transport.run(_candidate(), None)

    assert caught.value.code == "websocket_disconnected"
    assert caught.value.permanent is False
    assert "1006" in str(caught.value)
    assert "after" in str(caught.value)
