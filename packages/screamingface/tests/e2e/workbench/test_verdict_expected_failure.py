"""The expected-failure verdict end to end, on a real kernel (spec §3.7; unit 7 plan, Task 1).

A real notebook runs through the real runner and verdict. It records its SDK events and a
report into the bundle, as ``debug_failing_run`` will, and the verdict judges the declared
failure against them. No live target; the chain's log sources are files under ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import nbformat
import pytest

from workbench.evidence import FileLogSource
from workbench.targets import LiveTarget
from workbench.verdict import judge_notebook

TID = "4bf92f3577b34da6a3ce929d0e0e4736"
EXPECT = {"outcome": "fail", "failure_codes": ["provider_error"], "stage": "candidate"}

_RECORD = """
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from screamingface import events as ev
from workbench.telemetry_recorder import EventRecorder

recorder = EventRecorder(EVENTS_PATH)
recorder(
    ev.Span(
        id="e1",
        run_id="r1",
        sequence=1,
        timestamp=datetime(2026, 10, 22, tzinfo=UTC),
        source="engine",
        name="chat",
        operation="chat",
        start=datetime(2026, 10, 22, tzinfo=UTC),
        status=SPAN_STATUS,
    )
)
failures = [
    {"stage": STAGE, "code": code, "message": "m", "retryable": None, "metadata": {}}
    for code in CODES
]
report = SimpleNamespace(
    to_dict=lambda: {"candidates": [{"name": "fusion", "failures": failures, "cases": []}]},
    candidates=[],
)
"""

_RESULT = f"""
print("WORKBENCH_RESULT=" + json.dumps({{"trace_ids": ["{TID}"]}}))
recorder.finish(report)
"""


def _notebook(path: Path, expect: dict[str, Any] | None, **params: Any) -> Path:
    defaults = "ENGINE_URL = ''\nSCOREBOARD_URL = ''\nEVENTS_PATH = ''\n"
    knobs = "\n".join(f"{k} = {v!r}" for k, v in params.items())
    cell = nbformat.v4.new_code_cell(defaults + knobs)
    cell.metadata["tags"] = ["parameters"]
    result = nbformat.v4.new_code_cell(_RESULT)
    result.metadata["tags"] = ["workbench-result"]
    nb = nbformat.v4.new_notebook(cells=[cell, nbformat.v4.new_code_cell(_RECORD), result])
    nb.metadata["workbench"] = {"targets": ["replay"], "required_result": ["trace_ids"]}
    if expect is not None:
        nb.metadata["workbench"]["expect"] = expect
    nbformat.write(nb, path)
    return path


def _target(tmp_path: Path, *, engine_line: str) -> LiveTarget:
    log = tmp_path / "engine.log"
    log.write_text(engine_line + "\n")
    return LiveTarget(
        name="replay",
        engine_url="http://127.0.0.1:9",
        scoreboard_url="http://127.0.0.1:9",
        sources=(FileLogSource("engine", log),),
        required_hops=("engine",),
    )


def _judge(
    tmp_path: Path,
    *,
    expect: dict[str, Any] | None = EXPECT,
    codes: tuple[str, ...] = ("provider_error",),
    stage: str = "candidate",
    span_status: str = "error",
    engine_line: str = f"INFO: run scheduled trace_id={TID}",
) -> tuple[str | None, dict[str, Any], str]:
    """(failure message or None, trace.json, summary.md)."""
    path = _notebook(
        tmp_path / "debug.ipynb", expect, CODES=list(codes), STAGE=stage, SPAN_STATUS=span_status
    )
    out = tmp_path / "evidence"
    message: str | None = None
    try:
        judge_notebook(path, _target(tmp_path, engine_line=engine_line), out, lambda k, v: None)
    except pytest.fail.Exception as exc:
        message = str(exc)
    trace = json.loads((out / "replay" / "debug" / "trace.json").read_text())
    return message, trace, (out / "summary.md").read_text()


def test_the_declared_failure_with_its_evidence_passes_as_expected_fail(tmp_path: Path) -> None:
    message, trace, summary = _judge(tmp_path)
    assert message is None, message
    assert trace["passed"] is True and trace["reasons"] == []
    assert trace["expect"] == EXPECT
    assert trace["observed"] == {
        "failures": [{"code": "provider_error", "stage": "candidate"}],
        "error_telemetry": {"spans": 1, "logs": 0},
    }
    assert f"| replay | debug | expected FAIL ✓ | {TID} | — |" in summary


def test_an_unexpected_pass_is_red_in_trace_and_summary(tmp_path: Path) -> None:
    message, trace, summary = _judge(tmp_path, codes=())
    assert message is not None and "unexpected pass" in message
    assert trace["passed"] is False and trace["observed"]["failures"] == []
    assert "| replay | debug | expected FAIL ✗ |" in summary
    assert "unexpected pass" in summary


def test_a_wrong_code_is_red(tmp_path: Path) -> None:
    message, _, _ = _judge(tmp_path, codes=("aigateway_http_404",))
    assert message is not None and "wrong failure code" in message
    assert "aigateway_http_404" in message and "provider_error" in message


def test_a_wrong_stage_is_red(tmp_path: Path) -> None:
    message, _, _ = _judge(tmp_path, stage="grading")
    assert message is not None and "wrong failure stage" in message


def test_an_incomplete_trace_chain_is_red(tmp_path: Path) -> None:
    message, trace, _ = _judge(tmp_path, engine_line="INFO: run scheduled trace_id=none")
    assert message is not None and "trace chain incomplete" in message
    assert trace["passed"] is False


def test_no_error_telemetry_is_red(tmp_path: Path) -> None:
    message, _, _ = _judge(tmp_path, span_status="ok")
    assert message is not None and "no error telemetry" in message


def test_a_malformed_declaration_is_red(tmp_path: Path) -> None:
    malformed = {"outcome": "fail", "failure_codes": []}
    message, trace, summary = _judge(tmp_path, expect=malformed)
    assert message is not None and "malformed workbench.expect" in message
    assert trace["expect"] == malformed and trace["observed"] == {}
    assert "| replay | debug | expected FAIL ✗ |" in summary


def test_a_notebook_without_expect_is_judged_as_before(tmp_path: Path) -> None:
    message, trace, summary = _judge(tmp_path, expect=None)
    assert message is None, message
    assert "expect" not in trace and "observed" not in trace
    assert f"| replay | debug | PASS | {TID} | — |" in summary
