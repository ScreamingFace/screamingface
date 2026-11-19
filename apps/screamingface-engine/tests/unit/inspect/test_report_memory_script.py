"""The report-only memory probe runs a small run and restores every patch it installs.

FEATURE: memory fix 3 unit 0 (OME-1835). ``scripts/bench/report_memory.py`` is the stage probe
that measures end-of-run memory. It wraps stage functions at run time and must leave ``src/``
exactly as it found it, even when the run fails.

INVARIANT: after ``run_report`` returns or raises, every wrapped function is the original.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks import grading_endpoints  # noqa: E402
from screamingface_engine.benchmarks.contract import CandidateResult  # noqa: E402
from screamingface_engine.runner import executor  # noqa: E402

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "bench" / "report_memory.py"
_spec = importlib.util.spec_from_file_location("report_memory", _SCRIPT)
assert _spec is not None and _spec.loader is not None
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)


@pytest.mark.asyncio
async def test_the_report_runs_a_small_single_model_run_and_restores_every_patch(capsys):
    compact_json = grading_endpoints.compact_json
    as_payload = CandidateResult.as_payload
    build_result = executor._RunState.build_result

    await module.run_report("single", 3, one_emoji=False)
    out = capsys.readouterr().out

    assert "succeeded" in out.lower()
    assert "0 run start" in out
    assert "1 aggregate start" in out
    assert "8 run end" in out
    assert grading_endpoints.compact_json is compact_json
    assert CandidateResult.as_payload is as_payload
    assert executor._RunState.build_result is build_result


def test_the_fusion_candidate_names_five_members_and_a_synthesizer():
    assert module._FUSION_CANDIDATE.count("/prov/member-") == 5
    assert "/prov/synth~v1(" in module._FUSION_CANDIDATE
    assert len(module._FUSION_MODELS) == 6
