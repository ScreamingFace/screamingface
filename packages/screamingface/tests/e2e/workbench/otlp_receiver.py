"""A loopback OTLP/HTTP span receiver for the workbench (spec §3.6; unit 6 plan, Task 2).

The engine and aigateway export spans only to an OTLP endpoint, over HTTP/protobuf. The
workbench runs this receiver for a session, points both at it through
``OTEL_EXPORTER_OTLP_ENDPOINT``, and copies the spans of a run's trace ids into that run's
bundle with :meth:`OtlpReceiver.spans_for`.

INVARIANT: redaction happens BEFORE a span touches disk. Every string in a span (name,
attribute keys and values, status message) goes through ``workbench.redaction``; an attribute
whose NAME is secret-shaped (``http.request.header.x-api-key``) has its value masked whole,
because an opaque value carries no shape the token patterns could recognise. A ``bytes``
attribute is never written, not even as hex: only its size (``"<N bytes>"``).

INVARIANT: strict JSON. A non-finite double is written as the string ``"NaN"``,
``"Infinity"`` or ``"-Infinity"``; every line passes ``json.dumps(..., allow_nan=False)``.

INVARIANT: loopback only. Binds ``127.0.0.1`` on a free port; accepts only
``POST /v1/traces`` with ``application/x-protobuf`` (identity or gzip); refuses a body over
``MAX_BODY_BYTES`` — by ``Content-Length`` before reading it, and after inflating a gzip body
(a bomb is refused, never inflated past the cap). ``Content-Length`` must be ASCII digits
(``"²"`` passes ``str.isdigit`` but not ``int``) or the request is refused with 411. A
request that stalls mid-body times out after ``read_timeout_s`` and its connection is dropped,
so a slow or hostile client never holds a handler thread.

WHY stdlib ``http.server``: dev-only test tooling, one route, no new dependency. Decoding uses
``opentelemetry-proto`` (a dev-group dependency; also pulled in by the ``runtime`` extra).

Output: one JSON object per line, appended under a lock in a single ``write`` + flush, so a
reader that takes only newline-terminated lines never sees half a span. Shape::

    {trace_id, span_id, parent_span_id, name, kind, start_ns, end_ns, status, service,
     attributes}
"""

from __future__ import annotations

import json
import math
import threading
import zlib
from collections.abc import Callable, Iterable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final

from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span, Status

from workbench.redaction import MASK, is_secret_name, redact

MAX_BODY_BYTES: Final = 16 * 1024 * 1024
#: Per-socket-operation timeout: a stalled request line, header or body is dropped after this.
READ_TIMEOUT_S: Final = 10.0
TRACES_PATH: Final = "/v1/traces"
_PROTOBUF: Final = "application/x-protobuf"


class _Refused(Exception):
    def __init__(self, status: HTTPStatus) -> None:
        super().__init__(status)
        self.status = status


def _double(value: float) -> float | str:
    """A finite double as is; NaN/±inf as the strict-JSON-safe strings ``JSON.parse`` users know."""
    if math.isfinite(value):
        return value
    if math.isnan(value):
        return "NaN"
    return "Infinity" if value > 0 else "-Infinity"


_SCALARS: Final[dict[str, Callable[[AnyValue], Any]]] = {
    "string_value": lambda v: redact(v.string_value),
    "bool_value": lambda v: v.bool_value,
    "int_value": lambda v: v.int_value,
    "double_value": lambda v: _double(v.double_value),
    # WHY size only: bytes have no shape the redactor can read, and hex is the content.
    "bytes_value": lambda v: f"<{len(v.bytes_value)} bytes>",
}


def _any_value(value: AnyValue) -> Any:
    kind = value.WhichOneof("value")
    if kind == "array_value":
        out: Any = [_any_value(v) for v in value.array_value.values]
    elif kind == "kvlist_value":
        out = _attributes(value.kvlist_value.values)
    else:
        read = _SCALARS.get(kind or "")
        out = read(value) if read else None
    return out


def _attributes(pairs: Iterable[KeyValue]) -> dict[str, Any]:
    return {
        redact(kv.key): MASK if is_secret_name(kv.key) else _any_value(kv.value) for kv in pairs
    }


def _kind(span: Span) -> str:
    return Span.SpanKind.Name(span.kind).removeprefix("SPAN_KIND_").lower()


def _status(status: Status) -> dict[str, str]:
    code = Status.StatusCode.Name(status.code).removeprefix("STATUS_CODE_").lower()
    return {"code": code, "message": redact(status.message)}


def normalize(request: ExportTraceServiceRequest) -> list[dict[str, Any]]:
    """Every span in ``request`` as a redacted JSON-ready dict, in wire order."""
    out: list[dict[str, Any]] = []
    for resource_spans in request.resource_spans:
        resource = _attributes(resource_spans.resource.attributes)
        service = resource.get("service.name")
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                out.append(
                    {
                        "trace_id": span.trace_id.hex(),
                        "span_id": span.span_id.hex(),
                        "parent_span_id": span.parent_span_id.hex() or None,
                        "name": redact(span.name),
                        "kind": _kind(span),
                        "start_ns": span.start_time_unix_nano,
                        "end_ns": span.end_time_unix_nano,
                        "status": _status(span.status),
                        "service": service if isinstance(service, str) else None,
                        "attributes": _attributes(span.attributes),
                    }
                )
    return out


def _inflate(body: bytes) -> bytes:
    inflater = zlib.decompressobj(wbits=31)  # gzip framing only
    data = inflater.decompress(body, MAX_BODY_BYTES + 1)
    if len(data) > MAX_BODY_BYTES or inflater.unconsumed_tail:
        raise _Refused(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    return data


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, receiver: OtlpReceiver) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.receiver = receiver


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _Server  # pyright: ignore[reportIncompatibleVariableOverride]

    def setup(self) -> None:
        # WHY a socket timeout: a stalled read then raises TimeoutError, which
        # `handle_one_request` turns into a dropped connection instead of a handler thread
        # blocked forever. Set on the socket (the class-level `timeout` is per class, not
        # per receiver).
        self.request.settimeout(self.server.receiver.read_timeout_s)
        super().setup()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # WHY silent: request lines on stderr would interleave with test output

    def _reply(self, status: HTTPStatus, body: bytes = b"", ctype: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if status >= HTTPStatus.BAD_REQUEST:
            # WHY: an unread request body would be parsed as the next request.
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._reply(HTTPStatus.METHOD_NOT_ALLOWED)

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_GET  # noqa: N815

    def do_POST(self) -> None:  # noqa: N802
        try:
            request = self._read_request()
        except _Refused as refused:
            self._reply(refused.status)
            return
        self.server.receiver.append(normalize(request))
        self._reply(HTTPStatus.OK, ExportTraceServiceResponse().SerializeToString(), _PROTOBUF)

    def _encoding(self) -> str:
        return self.headers.get("Content-Encoding", "identity").strip().lower()

    def _refusal(self) -> HTTPStatus | None:
        """Why the request is refused from its line and headers alone, before reading a byte."""
        ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        length = self.headers.get("Content-Length", "")
        # WHY isascii: `"²".isdigit()` is True but `int("²")` raises in the handler thread.
        numeric = length.isascii() and length.isdigit()
        checks = (
            (self.path.split("?", 1)[0] != TRACES_PATH, HTTPStatus.NOT_FOUND),
            (
                ctype != _PROTOBUF or self._encoding() not in {"identity", "gzip"},
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            ),
            (not numeric, HTTPStatus.LENGTH_REQUIRED),
            (
                numeric and int(length) > MAX_BODY_BYTES,
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            ),
        )
        return next((status for failed, status in checks if failed), None)

    def _read_request(self) -> ExportTraceServiceRequest:
        refusal = self._refusal()
        if refusal is not None:
            raise _Refused(refusal)
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        try:
            data = _inflate(raw) if self._encoding() == "gzip" else raw
            return ExportTraceServiceRequest.FromString(data)
        except (DecodeError, zlib.error) as exc:
            raise _Refused(HTTPStatus.BAD_REQUEST) from exc


class OtlpReceiver:
    """``OtlpReceiver(out).start()`` -> endpoint URL; ``.spans_for(trace_ids)``; ``.stop()``."""

    def __init__(self, out: Path, *, read_timeout_s: float = READ_TIMEOUT_S) -> None:
        self.out = out
        self.read_timeout_s = read_timeout_s
        self._lock = threading.Lock()
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> str:
        if self._server is None:
            raise RuntimeError("OtlpReceiver is not started")
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}{TRACES_PATH}"

    def start(self) -> str:
        if self._server is not None:
            raise RuntimeError("OtlpReceiver is already started")
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self._server = _Server(self)
        # WHY a short poll: `shutdown()` waits up to one poll interval (0.5 s by default).
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="workbench-otlp-receiver",
            daemon=True,
        )
        self._thread.start()
        return self.endpoint

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)

    def spans_for(self, trace_ids: Iterable[str]) -> list[dict[str, Any]]:
        """The received spans whose trace id is exactly one of ``trace_ids`` (hex, any case)."""
        wanted = {t.lower() for t in trace_ids}
        if not wanted or not self.out.exists():
            return []
        with self._lock:
            text = self.out.read_text(encoding="utf-8")
        spans: list[dict[str, Any]] = []
        for line in text.splitlines(keepends=True):
            if not line.endswith("\n"):
                break  # an unterminated tail is a write in progress, never half-parsed
            span = json.loads(line)
            if span.get("trace_id") in wanted:
                spans.append(span)
        return spans

    def append(self, spans: list[dict[str, Any]]) -> None:
        """Append already-normalized spans: one locked ``write`` + flush, whole lines only."""
        if not spans:
            return
        payload = "".join(json.dumps(s, sort_keys=True, allow_nan=False) + "\n" for s in spans)
        with self._lock, self.out.open("a", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
