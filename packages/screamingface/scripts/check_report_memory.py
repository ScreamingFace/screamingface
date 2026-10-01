"""Measure the OME-1448 workload without model calls (11 x ~200 MB by default).

Run in a fresh process: python scripts/check_report_memory.py --directory /path/to/fixture
Files are retained for inspection; remove the fixture directory explicitly afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import shutil
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from screamingface import CaseGrade, CaseResult, Usage, reports
from screamingface._core.ports import _ResultArtifact, _RunOutcome
from screamingface._evaluation.model import _compiled_candidate
from screamingface._results.store import ResultStore
from screamingface.discovery import BenchmarkInfo
from screamingface.operation import OperationInfo


def fixture(root: Path, candidate_count: int, case_count: int, prompt_bytes: int) -> str:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "fixture.json"
    benchmark = BenchmarkInfo("contracteval", "memory-fixture", case_count)
    metadata = {
        "schema": "screamingface.candidate-result.v1",
        "benchmark_id": benchmark.id,
        "benchmark_revision": benchmark.revision,
        "case_count": case_count,
        "score": 1.0,
        "coverage": 1.0,
        "metrics": {},
        "failures": [],
    }
    with source.open("w") as stream:
        stream.write(json.dumps(metadata)[:-1] + ',"cases":[')
        for index in range(case_count):
            case = CaseResult(
                case_id=index,
                input="x" * prompt_bytes,
                output=f"answer {index}",
                finish_reason="stop",
                failures=[],
                metadata={},
                grade=CaseGrade(method="deterministic", score=1.0, metrics={}, checks=[]),
            )
            stream.write(("," if index else "") + json.dumps(case.to_dict()))
        stream.write("]}")
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    context = {
        "id": "memory-fixture",
        "benchmark": asdict(benchmark),
        "case_count": case_count,
        "candidates": [f"candidate-{index}" for index in range(candidate_count)],
    }
    store = ResultStore(root)
    for index, name in enumerate(context["candidates"]):
        candidate = _compiled_candidate(
            name=name,
            kind="model",
            models=["fixture"],
            url4="(@)!'memory fixture'",
            operations=[OperationInfo(id="op", kind="model", label="answer")],
        )
        outcome = _RunOutcome(
            run_id=name,
            started_at=datetime(2026, 10, 1, tzinfo=UTC),
            completed_at=datetime(2026, 10, 1, tzinfo=UTC),
            result_body=None,
            media_type="application/json",
            root_usage=Usage(),
            artifact=_ResultArtifact(digest, source.stat().st_size, digest),
        )
        saved = store.record("http://127.0.0.1:1", candidate, outcome, context)
        shutil.copyfile(source, saved.path)
    print(
        json.dumps(
            {
                "candidate_bytes": source.stat().st_size,
                "candidates": candidate_count,
                "cases_per_candidate": case_count,
            }
        ),
        flush=True,
    )
    return saved.key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--candidates", type=int, default=11)
    parser.add_argument("--cases", type=int, default=4182)
    parser.add_argument("--prompt-bytes", type=int, default=48000)
    args = parser.parse_args()
    key = fixture(args.directory, args.candidates, args.cases, args.prompt_bytes)
    report = reports.get(key, directory=args.directory)
    assert len(report.candidates) == args.candidates
    for candidate in report.candidates:
        assert len(candidate.cases) == args.cases
        assert candidate.cases[-1].input == "x" * args.prompt_bytes
    destination = report.export(args.directory / "report.json")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    print(
        json.dumps({"peak_rss_bytes": peak_bytes, "export_bytes": destination.stat().st_size}),
        flush=True,
    )
    # INVARIANT: the entire 2.2 GB fixture must fit comfortably on a 16 GB laptop.
    assert peak_bytes < 512 * 1024 * 1024, peak_bytes


if __name__ == "__main__":
    main()
