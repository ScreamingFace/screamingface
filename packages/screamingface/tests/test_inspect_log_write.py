"""The quarantined `.eval` writer (OME-1117).

Mental model: a mail slot to inspect's own writer. These tests never install
`inspect_ai` — they stub its `log` module to prove we hand OUR payload to THEIR
`EvalLog.model_validate` + `write_eval_log` and nothing else; the real
round-trip is `tests/test_inspect_log_live.py`, opt-in behind the extra.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import screamingface as sf
from screamingface._evaluation.model import _compiled_operation
from screamingface._inspect_log import write_inspect_log
from screamingface._inspect_log.payload import eval_log_payload


def _report() -> sf.Report:
    benchmark = sf.BenchmarkInfo(id="draco", revision="fixture-revision", case_count=100)
    cases = tuple(
        sf.CaseResult(
            case_id=case_id,
            input=f"Question {case_id}",
            output=f"Answer {case_id}",
            finish_reason="stop",
            grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
            failures=(),
            metadata={},
        )
        for case_id in (1, 2)
    )
    candidate = sf.CandidateResult(
        benchmark=benchmark,
        run_id="run_opus",
        started_at=datetime(2026, 9, 16, 8, 0, tzinfo=UTC),
        completed_at=datetime(2026, 9, 16, 8, 5, tzinfo=UTC),
        name="opus",
        kind="model",
        url4="(@)!'opus'",
        models=("provider/opus",),
        operations=(
            _compiled_operation(id="op_opus", kind="model", label="opus", depends_on=()),
            _compiled_operation(
                id="op_opus_aggregate",
                kind="aggregation",
                label="aggregate",
                depends_on=("op_opus",),
            ),
        ),
        score=1.0,
        coverage=1.0,
        metrics={},
        cases=cases,
        members=(),
        failures=(),
        usage=sf.Usage(input_tokens=100, output_tokens=20, cost_usd="0.12"),
    )
    return sf.Report(benchmark=benchmark, case_count=2, candidates=(candidate,))


class _Recorder:
    """Captures what crossed the mail slot into the stubbed inspect_ai."""

    def __init__(self) -> None:
        self.validated: list[dict[str, Any]] = []
        self.written: list[tuple[Any, str]] = []


def _stub_inspect_ai(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder) -> None:
    log_module = ModuleType("inspect_ai.log")

    class _EvalLog:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        @classmethod
        def model_validate(cls, payload: dict[str, Any]) -> _EvalLog:
            recorder.validated.append(payload)
            return cls(payload)

    def _write_eval_log(log: _EvalLog, location: str) -> None:
        recorder.written.append((log, location))
        Path(location).write_bytes(b"stub-eval-zip")

    log_module.EvalLog = _EvalLog  # type: ignore[attr-defined]
    log_module.write_eval_log = _write_eval_log  # type: ignore[attr-defined]
    package = ModuleType("inspect_ai")
    package.log = log_module  # type: ignore[attr-defined]
    # WHY: `find_spec` consults sys.modules and REQUIRES __spec__ on what it
    # finds there — a bare ModuleType stub without one makes it raise ValueError.
    package.__spec__ = ModuleSpec("inspect_ai", loader=None)
    log_module.__spec__ = ModuleSpec("inspect_ai.log", loader=None)
    monkeypatch.setitem(sys.modules, "inspect_ai", package)
    monkeypatch.setitem(sys.modules, "inspect_ai.log", log_module)


def test_missing_dependency_error_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    # INVARIANT: the failure is a doorstep message, not a stack trace — it names
    # the exact install command that fixes it.
    from screamingface._inspect_log import write as write_module

    monkeypatch.setattr(write_module, "find_spec", lambda name: None)
    with pytest.raises(ModuleNotFoundError, match=r"screamingface\[inspect\]"):
        write_inspect_log(_report(), Path("report.eval"))


def test_writer_hands_our_payload_to_inspects_own_writer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _Recorder()
    _stub_inspect_ai(monkeypatch, recorder)
    target = tmp_path / "runs" / "draco.eval"

    selected = write_inspect_log(_report(), target)

    assert selected == target
    assert target.read_bytes() == b"stub-eval-zip"
    # The document that crossed is exactly the pure mapping's output.
    assert recorder.validated == [eval_log_payload(_report())]
    (log, location) = recorder.written[0]
    assert location == str(target)
    assert log.payload == recorder.validated[0]


def test_writer_requires_the_eval_suffix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.eval"):
        write_inspect_log(_report(), tmp_path / "report.json")


def test_candidate_selector_passes_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder = _Recorder()
    _stub_inspect_ai(monkeypatch, recorder)
    write_inspect_log(_report(), tmp_path / "opus.eval", candidate="opus")
    assert recorder.validated[0]["eval"]["model"] == "opus"


def test_inspect_rejection_surfaces_as_a_domain_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # INVARIANT (defend at boundaries): if the pinned inspect-ai ever rejects
    # our document, the user sees a ScreamingFace error naming the export —
    # never a raw pydantic stack trace.
    import screamingface.errors

    recorder = _Recorder()
    _stub_inspect_ai(monkeypatch, recorder)
    log_module = sys.modules["inspect_ai.log"]

    def _reject(payload: dict[str, Any]) -> None:
        raise ValueError("1 validation error for EvalLog")

    monkeypatch.setattr(
        log_module, "EvalLog", type("_L", (), {"model_validate": staticmethod(_reject)})
    )
    with pytest.raises(screamingface.errors.ScreamingFaceError, match="inspect"):
        write_inspect_log(_report(), tmp_path / "draco.eval")


def test_write_failure_surfaces_as_a_domain_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import screamingface.errors

    recorder = _Recorder()
    _stub_inspect_ai(monkeypatch, recorder)
    log_module = sys.modules["inspect_ai.log"]

    def _fail_write(log: Any, location: str) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(log_module, "write_eval_log", _fail_write)
    with pytest.raises(screamingface.errors.ScreamingFaceError, match="export"):
        write_inspect_log(_report(), tmp_path / "draco.eval")


def test_missing_dependency_error_warns_about_the_runtime_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WHY: the most likely person to hit this is a runtime-extra user, for whom
    # `pip install "screamingface[inspect]"` is declared IMPOSSIBLE in the same
    # environment — the message must say so or it names a fix that cannot work.
    from screamingface._inspect_log import write as write_module

    monkeypatch.setattr(write_module, "find_spec", lambda name: None)
    with pytest.raises(ModuleNotFoundError, match="separate environment"):
        write_inspect_log(_report(), Path("report.eval"))
