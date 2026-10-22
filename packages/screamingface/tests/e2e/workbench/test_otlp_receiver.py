"""The workbench's loopback OTLP/HTTP span receiver (unit 6 plan, Task 2; spec §3.6).

WHY a real ``OTLPSpanExporter``: the receiver's contract is "what the engine and gateway
export lands here", and both export with this exporter over HTTP/protobuf. A hand-built
request would test our idea of the wire format, not the wire format.

WHY the fake secrets are assembled at runtime: a literal token in the repo trips secret
scanners, and these are never real.
"""

from __future__ import annotations

import gzip
import http.client
import json
import socket
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

from workbench.otlp_receiver import MAX_BODY_BYTES, OtlpReceiver
from workbench.redaction import MASK

SK = "sk-or-v1-" + "abcdefghijklmnop0123"
OPAQUE = "op4que-V4lue-zz9"


@pytest.fixture
def receiver(tmp_path: Path) -> Iterator[OtlpReceiver]:
    rx = OtlpReceiver(tmp_path / "spans.jsonl")
    rx.start()
    try:
        yield rx
    finally:
        rx.stop()


def _provider(
    endpoint: str, service: str, compression: Compression = Compression.NoCompression
) -> TracerProvider:
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    exporter = OTLPSpanExporter(endpoint=endpoint, compression=compression)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider


def _trace_id_hex(span_context_trace_id: int) -> str:
    return f"{span_context_trace_id:032x}"


def _post(endpoint: str, body: bytes, headers: dict[str, str], method: str = "POST") -> int:
    parts = urlsplit(endpoint)
    conn = http.client.HTTPConnection(parts.hostname or "", parts.port, timeout=5)
    try:
        conn.request(method, parts.path, body=body, headers=headers)
        return conn.getresponse().status
    finally:
        conn.close()


def test_start_returns_a_loopback_traces_endpoint(receiver: OtlpReceiver) -> None:
    endpoint = receiver.endpoint
    parts = urlsplit(endpoint)
    assert parts.scheme == "http"
    assert parts.hostname == "127.0.0.1"
    assert parts.port and parts.port > 0
    assert parts.path == "/v1/traces"


def _export_root_and_child(receiver: OtlpReceiver) -> list[dict[str, Any]]:
    provider = _provider(receiver.endpoint, "screamingface-engine")
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("url4.run", kind=SpanKind.INTERNAL) as root:
        with tracer.start_as_current_span("chat gpt-x", kind=SpanKind.CLIENT) as child:
            child.set_attribute("gen_ai.request.model", "openai/gpt-x")
            child.set_attribute("gen_ai.usage.input_tokens", 12)
            child.set_attribute("cache.hit", True)
            child.set_attribute("cost.usd", 0.25)
            child.set_attribute("stages", ["a", "b"])
            child.set_status(Status(StatusCode.ERROR, "upstream 502"))
    provider.shutdown()
    return receiver.spans_for({_trace_id_hex(root.get_span_context().trace_id)})


def test_real_exporter_spans_land_as_a_tree(receiver: OtlpReceiver) -> None:
    spans = _export_root_and_child(receiver)

    assert [s["name"] for s in spans] == ["chat gpt-x", "url4.run"]
    child_json, root_json = spans
    assert set(child_json) == {
        "trace_id",
        "span_id",
        "parent_span_id",
        "name",
        "kind",
        "start_ns",
        "end_ns",
        "status",
        "service",
        "attributes",
    }
    assert root_json["trace_id"] == child_json["trace_id"]
    assert len(root_json["trace_id"]) == 32
    assert len(root_json["span_id"]) == 16
    assert root_json["parent_span_id"] is None
    assert child_json["parent_span_id"] == root_json["span_id"]
    assert (child_json["kind"], root_json["kind"]) == ("client", "internal")
    assert child_json["start_ns"] <= child_json["end_ns"]
    # Every line on disk is one complete JSON object.
    lines = receiver.out.read_text().splitlines()
    assert len(lines) == 2
    assert all(isinstance(json.loads(line), dict) for line in lines)


def test_real_exporter_span_fields_are_normalized(receiver: OtlpReceiver) -> None:
    child_json, root_json = _export_root_and_child(receiver)

    assert child_json["service"] == "screamingface-engine"
    assert child_json["status"] == {"code": "error", "message": "upstream 502"}
    assert root_json["status"] == {"code": "unset", "message": ""}
    assert child_json["attributes"] == {
        "gen_ai.request.model": "openai/gpt-x",
        "gen_ai.usage.input_tokens": 12,
        "cache.hit": True,
        "cost.usd": 0.25,
        "stages": ["a", "b"],
    }


def test_gzip_export_is_accepted(receiver: OtlpReceiver) -> None:
    provider = _provider(receiver.endpoint, "aigateway", Compression.Gzip)
    with provider.get_tracer("t").start_as_current_span("chat.completions openrouter") as s:
        pass
    provider.shutdown()

    spans = receiver.spans_for({_trace_id_hex(s.get_span_context().trace_id)})

    assert [(x["name"], x["service"]) for x in spans] == [
        ("chat.completions openrouter", "aigateway")
    ]


def test_secrets_in_attributes_names_and_status_are_redacted(receiver: OtlpReceiver) -> None:
    provider = _provider(receiver.endpoint, "aigateway")
    with provider.get_tracer("t").start_as_current_span(f"call {SK}") as span:
        span.set_attribute("error.message", f"401 from provider: invalid key {SK}")
        span.set_attribute("http.request.header.x-api-key", OPAQUE)
        span.set_attribute("url.full", f"https://h/v1?api_key={OPAQUE}")
        span.set_attribute("headers", [f"Authorization: Bearer {OPAQUE}"])
        span.set_status(Status(StatusCode.ERROR, f"OPENROUTER_API_KEY={OPAQUE}"))
    provider.shutdown()

    (got,) = receiver.spans_for({_trace_id_hex(span.get_span_context().trace_id)})

    raw = receiver.out.read_text()
    assert SK not in raw
    assert OPAQUE not in raw
    assert got["name"] == f"call {MASK}"
    assert got["attributes"]["http.request.header.x-api-key"] == MASK
    assert MASK in got["attributes"]["error.message"]
    assert MASK in got["status"]["message"]


def test_spans_for_selects_by_exact_trace_id(receiver: OtlpReceiver) -> None:
    provider = _provider(receiver.endpoint, "screamingface-engine")
    tracer = provider.get_tracer("t")
    with tracer.start_as_current_span("mine") as mine:
        pass
    with tracer.start_as_current_span("other run") as other:
        pass
    provider.shutdown()
    mine_id = _trace_id_hex(mine.get_span_context().trace_id)
    other_id = _trace_id_hex(other.get_span_context().trace_id)

    assert [s["name"] for s in receiver.spans_for({mine_id})] == ["mine"]
    assert [s["name"] for s in receiver.spans_for([other_id])] == ["other run"]
    # A prefix, or a differently-cased id, is not the same trace.
    assert receiver.spans_for({mine_id[:16]}) == []
    assert [s["name"] for s in receiver.spans_for({mine_id.upper()})] == ["mine"]
    assert receiver.spans_for(set()) == []


def test_spans_for_before_any_export_is_empty(tmp_path: Path) -> None:
    rx = OtlpReceiver(tmp_path / "nested" / "spans.jsonl")
    assert rx.spans_for({"0" * 32}) == []


@pytest.mark.parametrize(
    ("method", "path", "headers", "body", "status"),
    [
        ("POST", "/v1/metrics", {"Content-Type": "application/x-protobuf"}, b"", 404),
        ("GET", "/v1/traces", {}, b"", 405),
        ("POST", "/v1/traces", {"Content-Type": "application/json"}, b"{}", 415),
        ("POST", "/v1/traces", {"Content-Type": "application/x-protobuf"}, b"\xff\xff", 400),
        (
            "POST",
            "/v1/traces",
            {"Content-Type": "application/x-protobuf", "Content-Encoding": "br"},
            b"",
            415,
        ),
    ],
)
def test_rejects_anything_but_a_protobuf_traces_post(
    receiver: OtlpReceiver,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes,
    status: int,
) -> None:
    base = receiver.endpoint.removesuffix("/v1/traces")
    assert _post(base + path, body, headers, method) == status
    assert receiver.spans_for({"0" * 32}) == []


def test_rejects_an_oversized_body_by_content_length(receiver: OtlpReceiver) -> None:
    parts = urlsplit(receiver.endpoint)
    conn = http.client.HTTPConnection(parts.hostname or "", parts.port, timeout=5)
    try:
        conn.putrequest("POST", parts.path)
        conn.putheader("Content-Type", "application/x-protobuf")
        conn.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
        conn.endheaders()  # no body sent: the receiver must refuse on the header alone
        assert conn.getresponse().status == 413
    finally:
        conn.close()


def test_rejects_a_gzip_bomb_past_the_cap(receiver: OtlpReceiver) -> None:
    bomb = gzip.compress(b"\x00" * (MAX_BODY_BYTES + 1))
    headers = {"Content-Type": "application/x-protobuf", "Content-Encoding": "gzip"}
    assert _post(receiver.endpoint, bomb, headers) == 413


def test_stop_frees_the_port(tmp_path: Path) -> None:
    rx = OtlpReceiver(tmp_path / "spans.jsonl")
    endpoint = rx.start()
    rx.stop()
    with pytest.raises(OSError):
        _post(endpoint, b"", {"Content-Type": "application/x-protobuf"})


# Unit 6 hardening (security review): bytes, a non-ASCII length, non-finite doubles, dotted
# secret names, and a stalled body.


def _request(*attributes: KeyValue) -> bytes:
    span = Span(trace_id=bytes.fromhex(TID), span_id=b"\x01" * 8, name="s", attributes=attributes)
    request = ExportTraceServiceRequest(
        resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=[span])])]
    )
    return request.SerializeToString()


TID = "4bf92f3577b34da6a3ce929d0e0e4736"
_PB = {"Content-Type": "application/x-protobuf"}


def test_a_bytes_attribute_is_recorded_by_size_never_by_content(receiver: OtlpReceiver) -> None:
    secret = b"\x00raw-secret-bytes" + OPAQUE.encode()
    body = _request(KeyValue(key="payload", value=AnyValue(bytes_value=secret)))
    assert _post(receiver.endpoint, body, _PB) == 200

    (got,) = receiver.spans_for({TID})
    raw = receiver.out.read_text()
    assert secret.hex() not in raw and OPAQUE not in raw
    assert got["attributes"]["payload"] == f"<{len(secret)} bytes>"


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-strict JSON constant {name}")


def test_non_finite_doubles_are_written_as_strict_json(receiver: OtlpReceiver) -> None:
    body = _request(
        KeyValue(key="a", value=AnyValue(double_value=float("nan"))),
        KeyValue(key="b", value=AnyValue(double_value=float("inf"))),
        KeyValue(key="c", value=AnyValue(double_value=float("-inf"))),
        KeyValue(key="d", value=AnyValue(double_value=0.5)),
    )
    assert _post(receiver.endpoint, body, _PB) == 200

    lines = receiver.out.read_text().splitlines()
    assert len(lines) == 1
    for line in lines:
        span = json.loads(line, parse_constant=_reject_constant)
        json.dumps(span, allow_nan=False)
    assert span["attributes"] == {"a": "NaN", "b": "Infinity", "c": "-Infinity", "d": 0.5}


@pytest.mark.parametrize("key", ["llm.api.key", "db.password.key", "http.request.header.cookie"])
def test_a_dotted_secret_name_ending_in_bare_key_is_masked(
    receiver: OtlpReceiver, key: str
) -> None:
    body = _request(KeyValue(key=key, value=AnyValue(string_value=OPAQUE)))
    assert _post(receiver.endpoint, body, _PB) == 200
    (got,) = receiver.spans_for({TID})
    assert got["attributes"][key] == MASK
    assert OPAQUE not in receiver.out.read_text()


def _raw_exchange(endpoint: str, head: bytes, *, wait_s: float = 5.0) -> bytes:
    parts = urlsplit(endpoint)
    with socket.create_connection((parts.hostname or "", parts.port or 0), timeout=wait_s) as s:
        s.sendall(head)
        chunks: list[bytes] = []
        while chunk := s.recv(65536):
            chunks.append(chunk)
        return b"".join(chunks)


def test_a_non_ascii_digit_content_length_is_refused_411(receiver: OtlpReceiver) -> None:
    head = (
        b"POST /v1/traces HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-protobuf\r\n"
        b"Content-Length: \xb2\r\n\r\n"  # '²': str.isdigit() is True, int() raises
    )
    reply = _raw_exchange(receiver.endpoint, head)
    assert reply.startswith(b"HTTP/1.1 411 ")


def test_a_stalled_body_never_holds_a_handler_thread(tmp_path: Path) -> None:
    rx = OtlpReceiver(tmp_path / "spans.jsonl", read_timeout_s=0.3)
    endpoint = rx.start()
    try:
        head = (
            b"POST /v1/traces HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-protobuf\r\n"
            b"Content-Length: 100\r\n\r\nonly-a-few-bytes"
        )
        started = time.monotonic()
        _raw_exchange(endpoint, head, wait_s=5.0)  # socket.timeout here = the thread is held
        assert time.monotonic() - started < 3.0
    finally:
        rx.stop()


def test_the_default_read_timeout_is_bounded(tmp_path: Path) -> None:
    assert 0 < OtlpReceiver(tmp_path / "s.jsonl").read_timeout_s <= 30
