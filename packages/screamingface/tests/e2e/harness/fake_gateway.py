"""FakeGateway — the failure-injection replay backend (OME-962, parent R7).

Mental model: a scripted stand-in actor. The cache-seeded gateway (OME-961) can only
replay good news — a failed provider call never stores a cache row — so the bad-news
paths are REHEARSED: this backend stands where the AI Gateway stands (the
``ports.ReplayBackend`` seam) and plays back a hand-authored ``Tape`` of failure
exchanges verbatim: the 429, the 503, the intercepted HTML page, the token-starved
blank turn, the truncated judge verdict.

Stages of one rehearsal, in execution order:

1. **Load** — the constructor indexes the tape's exchanges BY MODEL and refuses two
   tapes outright: one not marked ``provenance.authored=True`` (a rehearsal instrument
   must never replay something claiming to be a real recording — recordings belong to
   the cache-seeded gateway), and one holding two exchanges for a single model (row
   order would then decide which failure injects; ambiguity fails at load, mirroring
   the tape's own duplicate-identity rule).
2. **Serve** — ``start()`` binds a stdlib threaded HTTP server to ``127.0.0.1`` port 0
   and returns the base URL; the engine is pointed at it and never learns more (the
   seam contract). ``POST /v1/chat/completions`` answers from the tape with the
   recorded status, media type, and RAW bytes — never re-encoded. ``GET /healthz``
   answers 200 so the stand-in boots like the real gateway, and ``GET /v1/models``
   answers the OpenAI-style listing of EXACTLY the tape's models — the SDK's run
   planning reads the engine's catalogue (which proxies this route) before any model
   call, and a projection of the tape is still the tape, not an improvised answer.
3. **Refuse loudly** — anything else gets a named 404 and a row in ``refusals``:
   an untaped model is ``fake_gateway_unmatched_request`` (the Tape contract —
   ``lookup`` returns the exchange or ``None``, and ``None`` surfaces as a loud error,
   deliberately no default response), any other route is ``fake_gateway_unroutable``.
   Failure injection ONLY: the stand-in never invents an answer and never falls back
   to anything.

WHY match by MODEL and not by the tape fingerprint: the fingerprint is the gateway's
own cache ``key_hash`` over the exact request body, and an authored failure tape cannot
pre-compute it for bodies the ENGINE will compose at run time. The model is the one
dimension of a scripted failure scenario that is deterministic (the candidate model and
the board's pinned judge), so an authored tape's fingerprint serves only as the row's
unique identity, never as a lookup key here.

INVARIANT — zero egress by construction: this module holds no HTTP client at all and
binds loopback only, so it cannot spend even in a shell with real provider keys
exported. The strongest form of the harness's clean-environment rule: there is no code
path that could make an outbound request.
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal
from urllib.parse import quote

from .tape import RecordedExchange, Tape

_COMPLETIONS_PATH = "/v1/chat/completions"
_HEALTH_PATH = "/healthz"
_MODELS_PATH = "/v1/models"


@dataclass(frozen=True, slots=True)
class RefusedRequest:
    """One request the stand-in refused to answer — the rehearsal's off-script record.

    ``reason`` says which contract the request broke: ``unmatched_model`` is a
    completions call for a model the tape does not hold; ``unroutable`` is any request
    outside the taped surface (completions, the health probe, the catalog projection).
    """

    reason: Literal["unmatched_model", "unroutable"]
    path: str
    model: str | None


class FakeGateway:
    """``ReplayBackend`` adapter: an in-process loopback server scripted by one Tape.

    Args:
        tape: the authored failure tape to play. Must carry
            ``provenance.authored=True`` and at most one exchange per model —
            anything else raises ``ValueError`` here, at load, never mid-scenario.
    """

    def __init__(self, tape: Tape) -> None:
        self._by_model = _index_by_model(tape)
        self._refusals: list[RefusedRequest] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- the ReplayBackend seam ------------------------------------------------------
    async def start(self) -> str:
        return await asyncio.to_thread(self.start_sync)

    async def stop(self) -> None:
        await asyncio.to_thread(self.stop_sync)

    # The sync twins mirror CacheSeededGateway: the SDK under test is synchronous and
    # pytest fixtures compose these more honestly than event loops.
    def start_sync(self) -> str:
        if self._server is not None:
            raise RuntimeError("FakeGateway is already started")
        # Port 0: the OS assigns a free loopback port; the bound address is the truth.
        server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        thread = threading.Thread(
            target=server.serve_forever,
            name="fake-gateway",
            daemon=True,  # a leaked thread must never hold a test process open
        )
        thread.start()
        self._server = server
        self._thread = thread
        host, port = server.server_address[0], server.server_address[1]
        return f"http://{host}:{port}"

    def stop_sync(self) -> None:
        """Tear the server down; idempotent, and safe after a failed start."""
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=10)

    # -- scenario control ------------------------------------------------------------
    def swap(self, tape: Tape) -> None:
        """Load the next scenario's tape and clear the refusal record.

        The served base URL stays the same, so one engine boot rehearses every
        scenario. Validation is identical to construction — a bad tape fails here,
        before the scenario runs.
        """
        by_model = _index_by_model(tape)
        with self._lock:
            self._by_model = by_model
            self._refusals.clear()

    @property
    def refusals(self) -> tuple[RefusedRequest, ...]:
        """Every off-script request served the loud error, in arrival order."""
        with self._lock:
            return tuple(self._refusals)

    # -- handler callbacks (each request runs on its own server thread) ---------------
    def _lookup_model(self, model: str | None) -> RecordedExchange | None:
        with self._lock:
            return self._by_model.get(model) if model is not None else None

    def _catalog_projection(self) -> bytes:
        # EXACTLY the tape's models, in the real gateway's locked row shape (aigateway
        # core/model_capabilities.py::model_row — the SDK's planning requires `id` and
        # `owned_by`): the discovery half of the seam, derived from the tape's own
        # normalized identities — never invented.
        with self._lock:
            rows = [
                {
                    "id": model,
                    "object": "model",
                    "owned_by": exchange.normalized.provider,
                    "supported_parameters": [],
                    "supported_tools": [],
                    "unsupported_parameter_behavior": "reject",
                    "parameter_contract_url": f"/v1/model-parameters?model={quote(model, safe='')}",
                }
                for model, exchange in self._by_model.items()
            ]
        return json.dumps({"object": "list", "data": rows}).encode()

    def _record_refusal(self, refusal: RefusedRequest) -> None:
        with self._lock:
            self._refusals.append(refusal)


def _index_by_model(tape: Tape) -> dict[str, RecordedExchange]:
    # WHY authored is required (not defaulted): a rehearsal must announce itself.
    # Serving a REAL recording from the stand-in would let a happy-path replay bypass
    # the cache-seeded gateway's revision guards — the exact fallback R7 forbids.
    if tape.provenance.authored is not True:
        raise ValueError(
            "FakeGateway only plays authored tapes (provenance.authored=True); a real "
            "recording must replay through the cache-seeded gateway"
        )
    by_model: dict[str, RecordedExchange] = {}
    for exchange in tape.exchanges():
        model = exchange.normalized.model
        if model in by_model:
            raise ValueError(
                f"tape holds two exchanges for model {model!r} — the fake matches by "
                f"model, so one model must have exactly one scripted answer"
            )
        by_model[model] = exchange
    return by_model


class _Handler(BaseHTTPRequestHandler):
    """The stand-in's HTTP surface; ``gateway`` is bound per server by ``_handler_for``."""

    gateway: FakeGateway

    # HTTP/1.1 keeps httpx connection reuse working; every reply carries an
    # explicit Content-Length below, which the protocol version requires.
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler naming
        if self.path == _HEALTH_PATH:
            self._reply(200, b'{"status":"ok"}', "application/json")
            return
        if self.path == _MODELS_PATH:
            self._reply(200, self.gateway._catalog_projection(), "application/json")
            return
        self._refuse_unroutable()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
        if self.path != _COMPLETIONS_PATH:
            self._refuse_unroutable()
            return
        model = self._request_model()
        exchange = self.gateway._lookup_model(model)
        if exchange is None:
            self._refuse_unmatched(model)
            return
        self._reply(
            exchange.response.status,
            bytes(exchange.response.body),
            exchange.response.media_type,
        )

    # -- plumbing -------------------------------------------------------------------
    def _request_model(self) -> str | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length)) if length else None
        except (ValueError, OSError):
            return None
        model = body.get("model") if isinstance(body, dict) else None
        return model if isinstance(model, str) else None

    def _refuse_unmatched(self, model: str | None) -> None:
        # The Tape contract surfacing as HTTP: lookup returned None, so the answer is
        # a loud named error — deliberately NO default response.
        self.gateway._record_refusal(
            RefusedRequest(reason="unmatched_model", path=self.path, model=model)
        )
        self._reply_detail(
            404,
            code="fake_gateway_unmatched_request",
            message=(
                f"the failure tape holds no exchange for model {model!r} — "
                f"the FakeGateway never invents an answer"
            ),
        )

    def _refuse_unroutable(self) -> None:
        self.gateway._record_refusal(
            RefusedRequest(reason="unroutable", path=self.path, model=None)
        )
        self._reply_detail(
            404,
            code="fake_gateway_unroutable",
            message=f"the FakeGateway serves only {_COMPLETIONS_PATH} from its tape",
        )

    def _reply_detail(self, status: int, *, code: str, message: str) -> None:
        payload = json.dumps({"detail": {"code": code, "message": message}}).encode()
        # WHY close on every refusal: an off-script POST's body may never have been
        # read (the unroutable branch refuses before touching rfile), and on a
        # kept-alive connection those leftover bytes would be parsed as the NEXT
        # request — garbling it and masking the real refusal. Closing the connection
        # is simpler than draining and also covers bodies Content-Length cannot
        # measure (chunked); the client just reconnects.
        self._reply(status, payload, "application/json", close=True)

    def _reply(self, status: int, body: bytes, media_type: str, *, close: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        if close:
            # stdlib's send_header("Connection", "close") also sets close_connection,
            # so the socket really is torn down after this reply.
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        # Quiet by design: the refusal record is the observable, not stderr.
        return


def _handler_for(gateway: FakeGateway) -> type[BaseHTTPRequestHandler]:
    """Bind the handler class to one gateway instance (stdlib's class-based wiring)."""
    return type("_BoundHandler", (_Handler,), {"gateway": gateway})


__all__ = ["FakeGateway", "RefusedRequest"]
