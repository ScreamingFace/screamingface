"""A hand-built omitted-row ladder finalizes failures that still count as completed.

HealthBench is the subject since OME-1527 moved DRACO, the original one, to a local inspect Task.
"""

import json

import pytest
from test_builtin_early_score_timing import _assets, _call

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.builtins import BUILTIN_REGISTRATIONS
from screamingface_engine.benchmarks.healthbench.definition import HEALTHBENCH_WORST30
from screamingface_engine.observations import RunObservations
from url4.peer.server import Url4Node


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/graded"])
async def test_finalized_missing_cases_publish_completion(tmp_path, monkeypatch, suffix):
    registration = next(r for r in BUILTIN_REGISTRATIONS if r.benchmark.id == "healthbench-worst30")
    _assets(tmp_path, monkeypatch, registration)
    node = Url4Node("missing")
    HEALTHBENCH_WORST30.install(node, tmp_path)
    snapshots = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink",
        lambda: lambda body, attrs: snapshots.append(dict(attrs)),
    )
    run = RunObservations((ActivityObserver,))
    try:
        with run.bind():
            result = json.loads(
                await _call(
                    node,
                    f"/benchmarks/healthbench-worst30/{HEALTHBENCH_WORST30.revision}/aggregate{suffix}",
                    "[]",
                    "aggregate:2",
                )
            )
            assert [c["status"] for c in result["cases"]] == ["failed", "failed"]
            assert [s["sf.progress.completed"] for s in snapshots] == [1, 2]
            assert all(s["sf.progress.score"] is None for s in snapshots)
    finally:
        await run.aclose()
        await node.aclose()
