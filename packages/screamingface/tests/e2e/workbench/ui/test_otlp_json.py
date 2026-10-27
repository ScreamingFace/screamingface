"""OTLP/JSON export of a bundle's spans (u8 plan, Task 4; spec §3.8 item 6).

The round trip goes through ``opentelemetry.proto``'s ``TracesData``: OTLP/JSON writes ids as
hex (not proto3 JSON's base64), so the test re-encodes the three id fields the way an OTLP/JSON
receiver must, then checks the ids, times, kinds, statuses and typed attributes survive.
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.protobuf import json_format
from opentelemetry.proto.trace.v1.trace_pb2 import Span, Status, TracesData

from workbench.ui import trace_story as ts
from workbench.ui.app import create_app
from workbench.ui.otlp_json import to_otlp_json
from workbench.ui.runs import RunManager

TID = "4bf92f3577b34da6a3ce929d0e0e4736"
CLIENT = "00f067aa0ba902b7"  # the notebook's traceparent span id: in no span file
PORT = 9141
TOKEN = "t0k3n-for-otlp-tests"
_IDS = ("traceId", "spanId", "parentSpanId")


def span(span_id: str, parent: str | None, name: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "trace_id": TID,
        "span_id": span_id,
        "parent_span_id": parent,
        "name": name,
        "kind": "internal",
        "start_ns": 1_000,
        "end_ns": 2_000,
        "status": {"code": "ok", "message": ""},
        "service": "screamingface-engine",
        "attributes": {},
    }
    return row | extra


def _b64(value: str) -> str:
    return base64.b64encode(bytes.fromhex(value)).decode()


def parse(otlp: dict[str, Any]) -> TracesData:
    """Strict JSON, then ``TracesData`` with the hex ids re-encoded as proto3 JSON's base64."""
    data = json.loads(json.dumps(otlp, allow_nan=False))
    for resource in data.get("resourceSpans", []):
        for scope in resource["scopeSpans"]:
            for row in scope["spans"]:
                for field in _IDS:
                    if field in row:
                        row[field] = _b64(row[field])
    return json_format.ParseDict(data, TracesData())


def _spans(traces: TracesData) -> dict[str, tuple[str, Span]]:
    out: dict[str, tuple[str, Span]] = {}
    for resource in traces.resource_spans:
        service = {kv.key: kv.value.string_value for kv in resource.resource.attributes}
        for scope in resource.scope_spans:
            for row in scope.spans:
                out[row.name] = (service.get("service.name", ""), row)
    return out


def test_a_round_trip_through_traces_data_keeps_ids_times_kinds_and_typed_attributes() -> None:
    attrs = {
        "s": "text",
        "b": True,
        "i": 42,
        "f": 0.5,
        "nan": "NaN",
        "list": [1, "two"],
        "map": {"k": "v"},
        "none": None,
    }
    rows = [
        span("aaaaaaaaaaaaaaaa", CLIENT, "url4.run", kind="server", attributes=attrs),
        span(
            "bbbbbbbbbbbbbbbb",
            "aaaaaaaaaaaaaaaa",
            "POST /v1/chat/completions",
            service="aigateway",
            kind="server",
            status={"code": "error", "message": "boom"},
        ),
        span("cccccccccccccccc", None, "root", kind="client", start_ns=5, end_ns=9),
    ]
    traces = parse(to_otlp_json(rows))
    assert len(traces.resource_spans) == 2  # grouped by service
    got = _spans(traces)
    service, run = got["url4.run"]
    assert service == "screamingface-engine"
    assert run.trace_id == bytes.fromhex(TID)
    assert run.span_id == bytes.fromhex("aaaaaaaaaaaaaaaa")
    assert run.parent_span_id == bytes.fromhex(CLIENT)
    assert (run.start_time_unix_nano, run.end_time_unix_nano) == (1_000, 2_000)
    assert run.kind == Span.SPAN_KIND_SERVER
    typed = {kv.key: kv.value for kv in run.attributes}
    assert typed["s"].string_value == "text"
    assert typed["b"].bool_value is True
    assert typed["i"].int_value == 42
    assert typed["f"].double_value == 0.5
    assert typed["nan"].string_value == "NaN"
    assert [v.WhichOneof("value") for v in typed["list"].array_value.values] == [
        "int_value",
        "string_value",
    ]
    assert typed["map"].kvlist_value.values[0].key == "k"
    assert typed["none"].WhichOneof("value") is None
    service, chat = got["POST /v1/chat/completions"]
    assert service == "aigateway"
    assert chat.status.code == Status.STATUS_CODE_ERROR and chat.status.message == "boom"
    _, root = got["root"]
    assert root.parent_span_id == b"" and root.kind == Span.SPAN_KIND_CLIENT


def test_times_are_strings_and_ids_hex_as_otlp_json_requires() -> None:
    out = to_otlp_json([span("aaaaaaaaaaaaaaaa", None, "x")])
    (row,) = out["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert row["traceId"] == TID and row["spanId"] == "aaaaaaaaaaaaaaaa"
    assert "parentSpanId" not in row
    assert (row["startTimeUnixNano"], row["endTimeUnixNano"]) == ("1000", "2000")


def test_a_synthetic_span_is_not_exported(tmp_path: Path) -> None:
    rows = [span("aaaaaaaaaaaaaaaa", CLIENT, ts.RUN_SPAN)]
    (tmp_path / "spans.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "recorder.json").write_text('{"first_event_ns": 500, "last_event_ns": 3000}')
    story = ts.build(tmp_path)
    (root,) = story.roots
    assert root.synthetic  # the view derived a client span ...
    exported = _spans(parse(to_otlp_json([root.span, *rows])))
    assert ts.CLIENT_SPAN not in exported  # ... which the export leaves out
    assert set(exported) == {ts.RUN_SPAN}


def test_hostile_values_still_give_strict_json_that_parses() -> None:
    deep: Any = "leaf"
    for _ in range(200):
        deep = [deep]
    rows = [
        span(
            "aaaaaaaaaaaaaaaa",
            None,
            "<script>",
            kind="weird",
            status="nope",
            start_ns="soon",
            end_ns=-1,
            attributes={
                "inf": float("inf"),
                "nan": float("nan"),
                "big": 1 << 70,
                "deep": deep,
                7: "x",
            },
        ),
        span("not-hex", None, "bad id"),
        span("aaaaaaaaaaaaaaaa", None, "bad trace", trace_id="zz"),
        span("bbbbbbbbbbbbbbbb", "nope", "bad parent"),
        span("cccccccccccccccc", None, "no service", service=None),
    ]
    traces = parse(to_otlp_json(rows))
    got = _spans(traces)
    assert set(got) == {"<script>", "bad parent", "no service"}  # bad ids are skipped
    _, hostile = got["<script>"]
    assert hostile.kind == Span.SPAN_KIND_UNSPECIFIED
    assert hostile.status.code == Status.STATUS_CODE_UNSET
    assert hostile.start_time_unix_nano == 0 and hostile.end_time_unix_nano == 0
    typed = {kv.key: kv.value for kv in hostile.attributes}
    assert typed["inf"].double_value == float("inf")
    assert typed["big"].string_value == str(1 << 70)  # outside int64: kept as text
    assert "7" in typed
    _, orphan = got["bad parent"]
    assert orphan.parent_span_id == b""  # an invalid parent id is dropped, not guessed


def test_no_spans_is_an_empty_export() -> None:
    assert to_otlp_json([]) == {"resourceSpans": []}


# --- route ------------------------------------------------------------------------------------


def _never_spawn(argv: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen[str]:
    raise AssertionError("the export route must not start a run")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    root = tmp_path / "out"
    bundle = root / "replay" / "quickstart"
    (bundle / "logs").mkdir(parents=True)
    (bundle / "trace.json").write_text(json.dumps({"passed": True, "trace_ids": [TID]}))
    rows = [span("aaaaaaaaaaaaaaaa", CLIENT, ts.RUN_SPAN)]
    (bundle / "spans.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (bundle / "recorder.json").write_text('{"first_event_ns": 500, "last_event_ns": 3000}')
    manager = RunManager(root, workdir=tmp_path, environ={}, spawn=_never_spawn)
    app = create_app(root=root, manager=manager, token=TOKEN, port=PORT, notebooks=())
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


URL = "/bundles/replay/quickstart/trace.otlp.json"


@pytest.mark.parametrize("how", ["query", "header"])
def test_the_route_downloads_the_spans_as_otlp_json(client: TestClient, how: str) -> None:
    if how == "query":
        response = client.get(URL, params={"token": TOKEN})
    else:
        response = client.get(URL, headers={"x-workbench-token": TOKEN})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json"
    disposition = response.headers["content-disposition"]
    assert disposition == f'attachment; filename="{TID}.otlp.json"'
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert set(_spans(parse(response.json()))) == {ts.RUN_SPAN}  # no synthetic sdk.evaluate


@pytest.mark.parametrize("params", [{}, {"token": "forged"}])
def test_the_route_without_the_token_is_forbidden(
    client: TestClient, params: dict[str, str]
) -> None:
    response = client.get(URL, params=params)
    assert response.status_code == 403
    assert TID not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/bundles/..%2F..%2Fetc/trace.otlp.json",
        "/bundles/%2Fetc%2Fpasswd/trace.otlp.json",
        "/bundles/replay/..%2F..%2Fx/trace.otlp.json",
        "/bundles/replay/trace.otlp.json",
        "/bundles/nope/trace.otlp.json",
    ],  # fmt: skip
)
def test_a_path_traversal_key_is_404(client: TestClient, path: str) -> None:
    assert client.get(path, params={"token": TOKEN}).status_code == 404


def test_the_bundle_page_still_serves_beside_the_export(client: TestClient) -> None:
    assert client.get("/bundles/replay/quickstart").status_code == 200
