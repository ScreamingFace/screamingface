"""Live round-trip against the real pinned inspect-ai (OME-1117 acceptance).

Runs only where the `inspect` extra is installed (skipped in CI, whose install
is `uv sync --extra notebook` — the extras genuinely conflict with `runtime`):

    uv run --extra inspect pytest tests/test_inspect_log_live.py

Acceptance pinned here: the exported file is opened by inspect's OWN reader —
the same one `inspect view` uses — and carries the provenance label and the
run's real metered cost.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import screamingface as sf
from screamingface._evaluation.model import _compiled_operation

pytest.importorskip("inspect_ai")


def _report() -> sf.Report:
    benchmark = sf.BenchmarkInfo(id="draco", revision="fixture-revision", case_count=100)
    cases = (
        sf.CaseResult(
            case_id=1,
            input="What is 2+2?",
            output="4",
            finish_reason="stop",
            grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
            failures=(),
            metadata={},
        ),
        sf.CaseResult(
            case_id=2,
            input="What is 3+3?",
            output=None,
            finish_reason=None,
            grade=sf.CaseGrade(method="fixture", score=None, metrics={}, checks=()),
            failures=(
                sf.Failure(
                    stage="candidate",
                    code="provider_timeout",
                    message="the provider timed out",
                    case_id=2,
                ),
            ),
            metadata={},
        ),
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
        score=0.5,
        coverage=0.5,
        metrics={},
        cases=cases,
        members=(),
        failures=(),
        usage=sf.Usage(input_tokens=100, output_tokens=20, cost_usd="0.12"),
    )
    return sf.Report(benchmark=benchmark, case_count=2, candidates=(candidate,))


def test_exported_eval_log_opens_in_inspects_own_reader(tmp_path: Path) -> None:
    from inspect_ai.log import read_eval_log

    selected = _report().export(tmp_path / "draco.eval", format="inspect")

    log = read_eval_log(str(selected))
    assert log.status == "success"
    assert log.eval.task == "draco"
    assert log.eval.model == "opus"
    # Provenance label + one-way stamp (acceptance).
    assert log.eval.metadata is not None
    assert log.eval.metadata["produced_by"] == "ScreamingFace engine"
    assert log.eval.metadata["one_way_export"] is True
    # Real metered cost, passed through (acceptance).
    assert log.stats.model_usage["opus"].total_cost == pytest.approx(0.12)
    assert log.samples is not None and len(log.samples) == 2
    assert log.samples[0].output.completion == "4"
    assert log.samples[0].scores is not None
    assert log.samples[0].scores["screamingface"].value == 1.0
    # The failed Case keeps our failure vocabulary in its metadata.
    assert log.samples[1].metadata is not None
    assert log.samples[1].metadata["failures"][0]["code"] == "provider_timeout"
