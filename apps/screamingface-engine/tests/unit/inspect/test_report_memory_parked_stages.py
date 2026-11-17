"""The report probe marks the parked stages and restores the parked builder and face.

FEATURE: memory fix 3 (OME-1835), unit 2. The parked face adds two stage marks to the report
probe: ``2p`` when the builder starts marking Cases into parked text, and ``3p`` when the builder
has finished the light result and its head. The probe restores every wrapper it installs.

INVARIANT: after ``run_report`` returns, the builder's ``finish_body`` and the aggregate's
``aggregate_body_async`` are the very objects they were before the run.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.result_builder import CandidateResultBuilder  # noqa: E402
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    BenchmarkAggregation,
)

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "bench" / "report_memory.py"
_spec = importlib.util.spec_from_file_location("report_memory_parked", _SCRIPT)
assert _spec is not None and _spec.loader is not None
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)


@pytest.mark.asyncio
async def test_the_report_marks_the_parked_stages_and_restores_them(capsys):
    finish_body = CandidateResultBuilder.finish_body
    aggregate_body = BenchmarkAggregation.aggregate_body_async

    await module.run_report("single", 3, one_emoji=False)
    out = capsys.readouterr().out

    assert "succeeded" in out.lower()
    assert "1 aggregate start" in out
    assert "2p marking done" in out
    assert "3p builder finished" in out
    assert CandidateResultBuilder.finish_body is finish_body
    assert BenchmarkAggregation.aggregate_body_async is aggregate_body
