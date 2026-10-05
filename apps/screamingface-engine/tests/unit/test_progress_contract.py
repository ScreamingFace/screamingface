"""Exact public progress facts and scope separation."""

import asyncio
from pathlib import Path

from test_graded_result_transport import _result

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.progress import completed_case, grading_progress
from screamingface_engine.candidate_scope import candidate_invocation_scope
from screamingface_engine.observations import RunObservations


def test_exact_schema_and_client_parser_conformance(monkeypatch):
    result = _result()
    snapshots = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink",
        lambda: lambda body, attrs: snapshots.append(dict(attrs)),
    )
    run = RunObservations((ActivityObserver,))
    try:
        with run.bind():
            completed_case(
                "board", "v1", result, lambda cases: CandidateScore(score=0.5, metrics={})
            )
    finally:
        asyncio.run(run.aclose())
    assert snapshots == [
        {
            "sf.progress.schema": "screamingface.benchmark-progress.v1",
            "sf.progress.benchmark": "board",
            "sf.progress.benchmark_revision": "v1",
            "sf.progress.revision": 1,
            "sf.progress.completed": 1,
            "sf.progress.graded": 1,
            "sf.progress.score": 0.5,
        }
    ]
    assert {key: type(value) for key, value in snapshots[0].items()} == {
        "sf.progress.schema": str,
        "sf.progress.benchmark": str,
        "sf.progress.benchmark_revision": str,
        "sf.progress.revision": int,
        "sf.progress.completed": int,
        "sf.progress.graded": int,
        "sf.progress.score": float,
    }
    # Exercise the actual Client parser against the Engine's emitted payload.
    import json
    import subprocess
    import sys

    client = Path(__file__).resolve().parents[4] / "packages/screamingface/src"
    assert client.exists()
    code = """
import json, sys
from datetime import datetime, UTC
sys.path.insert(0, sys.argv[1])
from screamingface.events import Log
from screamingface._ui.provisional_score import parse_snapshot
attrs = json.load(sys.stdin)
event = Log(id="1", run_id="run", sequence=1, timestamp=datetime.now(UTC),
    source="board", severity_number=9, severity_text="INFO",
    body="Benchmark progress", attributes=attrs)
parsed = parse_snapshot(event, 2)
assert parsed is not None and parsed.score == 0.5 and parsed.completed == 1
"""
    subprocess.run(
        [sys.executable, "-c", code, str(client)],
        input=json.dumps(snapshots[0]),
        text=True,
        capture_output=True,
        check=True,
    )


def test_nested_candidate_suppressed_and_boards_and_revisions_independent(monkeypatch):
    result = _result()
    snapshots = []
    monkeypatch.setattr("screamingface_engine.activity.progress.time.monotonic", lambda: 1.0)
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink",
        lambda: lambda body, attrs: snapshots.append(dict(attrs)),
    )

    def scorer(cases):
        return CandidateScore(score=0.5, metrics={})

    run = RunObservations((ActivityObserver,))
    try:
        with run.bind():
            with candidate_invocation_scope(), grading_progress("nested", "v1", scorer):
                completed_case("nested", "v1", result, scorer)
            assert snapshots == []
            for board, revision in [("a", "v1"), ("b", "v1"), ("a", "v2")]:
                completed_case(board, revision, result, scorer)
            for board, revision in [("a", "v1"), ("b", "v1"), ("a", "v2")]:
                with grading_progress(board, revision, scorer):
                    completed_case(
                        board, revision, result.model_copy(update={"case_id": 2}), scorer
                    )
            assert [
                (
                    s["sf.progress.benchmark"],
                    s["sf.progress.benchmark_revision"],
                    s["sf.progress.completed"],
                )
                for s in snapshots
            ] == [
                ("a", "v1", 1),
                ("b", "v1", 1),
                ("a", "v2", 1),
                ("a", "v1", 2),
                ("b", "v1", 2),
                ("a", "v2", 2),
            ]
    finally:
        asyncio.run(run.aclose())
