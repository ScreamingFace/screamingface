"""The verdict records telemetry into the bundle (unit 6 plan, Task 4), on a real kernel.

A real notebook runs through the real runner and verdict: its recorder writes the events into
``EVENTS_PATH`` (which the verdict sets to ``<bundle>/events.jsonl``), and the verdict copies
the run's spans in at bundle time. No live target: the chain has no sources to check.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import nbformat
import pytest

from workbench.bundle import EVENTS_FILE, SPANS_FILE, TELEMETRY_FILE
from workbench.redaction import MASK
from workbench.targets import LiveTarget
from workbench.verdict import judge_notebook

TID = "4bf92f3577b34da6a3ce929d0e0e4736"
OTHER = "00f067aa0ba902b7aaaaaaaaaaaaaaaa"
OPAQUE = "op4que-V4lue-zz9"

_RECORD = f"""
from datetime import UTC, datetime

from screamingface import events as ev
from workbench.telemetry_recorder import EventRecorder

recorder = EventRecorder(EVENTS_PATH)
recorder(
    ev.Log(
        id="e1",
        run_id="r1",
        sequence=1,
        timestamp=datetime(2026, 10, 22, tzinfo=UTC),
        source="engine",
        severity_number=17,
        severity_text="ERROR",
        body="provider error OPENROUTER_API_KEY={OPAQUE}",
        attributes={{"x-api-key": "{OPAQUE}"}},
    )
)
"""

_RESULT = f"""
import json

print("WORKBENCH_RESULT=" + json.dumps({{"trace_ids": ["{TID}"], "events_path": EVENTS_PATH}}))
recorder.finish(None)
"""


def _notebook(path: Path) -> Path:
    params = nbformat.v4.new_code_cell("ENGINE_URL = ''\nSCOREBOARD_URL = ''\nEVENTS_PATH = ''")
    params.metadata["tags"] = ["parameters"]
    result = nbformat.v4.new_code_cell(_RESULT)
    result.metadata["tags"] = ["workbench-result"]
    nb = nbformat.v4.new_notebook(cells=[params, nbformat.v4.new_code_cell(_RECORD), result])
    nb.metadata["workbench"] = {"targets": ["replay"], "required_result": ["trace_ids"]}
    nbformat.write(nb, path)
    return path


_TARGET = LiveTarget(
    name="replay",
    engine_url="http://127.0.0.1:9",
    scoreboard_url="http://127.0.0.1:9",
    sources=(),
    required_hops=(),
)


def _spans_for(trace_ids: Iterable[str]) -> list[dict[str, Any]]:
    received = [
        {
            "trace_id": TID,
            "span_id": "1",
            "name": "url4.run",
            "attributes": {"k": f"api_key={OPAQUE}"},
        },
        {"trace_id": OTHER, "span_id": "2", "name": "url4.run", "attributes": {}},
    ]
    return [s for s in received if s["trace_id"] in set(trace_ids)]


def _judge(tmp_path: Path, **kwargs: Any) -> Path:
    path = _notebook(tmp_path / "telemetry.ipynb")
    out = tmp_path / "evidence"
    props: list[tuple[str, object]] = []
    try:
        judge_notebook(path, _TARGET, out, lambda k, v: props.append((k, v)), **kwargs)
    except pytest.fail.Exception:
        pass  # the verdict's own pass/fail is not under test here
    return out / "replay" / "telemetry"


def test_the_verdict_points_the_recorder_at_the_bundle_and_copies_the_runs_spans(
    tmp_path: Path,
) -> None:
    bundle = _judge(tmp_path, spans_for=_spans_for)
    trace = json.loads((bundle / "trace.json").read_text())
    assert trace["result"]["events_path"] == str(bundle / EVENTS_FILE)

    events = (bundle / EVENTS_FILE).read_text()
    assert OPAQUE not in events
    (row,) = [json.loads(line) for line in events.splitlines()]
    assert row["body"] == f"provider error OPENROUTER_API_KEY={MASK}"
    assert row["attributes"]["x-api-key"] == MASK

    spans = [json.loads(line) for line in (bundle / SPANS_FILE).read_text().splitlines()]
    assert [s["span_id"] for s in spans] == ["1"]  # the other trace id's span stays out
    assert OPAQUE not in (bundle / SPANS_FILE).read_text()

    telemetry = json.loads((bundle / TELEMETRY_FILE).read_text())
    assert telemetry["events"]["recorded"] == 1 and telemetry["events"]["note"] is None
    assert telemetry["spans"]["copied"] == 1 and telemetry["spans"]["note"] is None


def test_without_a_receiver_the_bundle_says_why_there_are_no_spans(tmp_path: Path) -> None:
    bundle = _judge(tmp_path)
    assert (bundle / SPANS_FILE).read_text() == ""
    telemetry = json.loads((bundle / TELEMETRY_FILE).read_text())
    assert telemetry["spans"]["note"] == "no OTLP receiver in this session"


def test_a_rerun_never_inherits_the_previous_runs_events(tmp_path: Path) -> None:
    bundle = tmp_path / "evidence" / "replay" / "telemetry"
    bundle.mkdir(parents=True)
    (bundle / EVENTS_FILE).write_text('{"kind": "stale"}\n' * 3)
    (bundle / "report.json").write_text("{}")
    _judge(tmp_path, spans_for=_spans_for)
    assert len((bundle / EVENTS_FILE).read_text().splitlines()) == 1
    assert not (bundle / "report.json").exists()
