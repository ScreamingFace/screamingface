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
from decimal import Decimal
from pathlib import Path

from screamingface import CaseGrade, CaseResult, Usage, reports
from screamingface._core.ports import _ResultArtifact, _RunOutcome
from screamingface._evaluation.model import _compiled_candidate, _member_projection
from screamingface._results.store import ResultStore
from screamingface.case_result import CaseOperation
from screamingface.discovery import BenchmarkInfo
from screamingface.operation import OperationInfo
from screamingface.operation_accounting import OperationAccounting, OperationCache


def fixture(
    root: Path, candidate_count: int, case_count: int, prompt_bytes: int, *, fusion: bool = False
) -> str:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "fixture.json"
    benchmark = BenchmarkInfo("contracteval", "memory-fixture", case_count)
    operations = [OperationInfo(id="op", kind="model", label="answer")]
    members = []
    if fusion:
        operations = [
            OperationInfo(id="a", kind="model", label="A"),
            OperationInfo(id="b", kind="model", label="B"),
            OperationInfo(id="s", kind="synthesis", label="synthesis"),
        ]
        members = [
            _member_projection(operation_id=op.id, name=op.label, kind="model", models=["fixture"])
            for op in operations[:2]
        ]
    accounting = OperationAccounting(
        provider="fixture",
        response_model="fixture",
        usage=Usage(input_tokens=10, output_tokens=2, cost_usd="0.1"),
        cache=OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
        request_model="fixture",
        provider_latency_ms=1,
        provider_attempts=1,
    )
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
                operations=[
                    CaseOperation(
                        operation_id=op.id,
                        output="answer",
                        finish_reason="stop",
                        accounting=accounting,
                    )
                    for op in operations
                ],
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
            kind="fusion" if fusion else "model",
            models=["fixture"],
            url4="(@)!'memory fixture'",
            operations=operations,
            members=members,
        )
        outcome = _RunOutcome(
            run_id=name,
            started_at=datetime(2026, 10, 1, tzinfo=UTC),
            completed_at=datetime(2026, 10, 1, tzinfo=UTC),
            result_body=None,
            media_type="application/json",
            root_usage=Usage(
                input_tokens=10 * len(operations) * case_count,
                output_tokens=2 * len(operations) * case_count,
                cost_usd=Decimal("0.1") * len(operations) * case_count,
            ),
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
    parser.add_argument(
        "--fusion", action="store_true", help="Include fusion members and operation accounting"
    )
    args = parser.parse_args()
    key = fixture(
        args.directory, args.candidates, args.cases, args.prompt_bytes, fusion=args.fusion
    )
    report = reports.get(key, directory=args.directory)
    assert len(report.candidates) == args.candidates
    for candidate in report.candidates:
        assert len(candidate.cases) == args.cases
        assert candidate.cases[-1].input == "x" * args.prompt_bytes
        if args.fusion:
            assert len(candidate.members) == 2
            for member in candidate.members:
                assert member.usage is not None
                assert member.usage.input_tokens == 10 * args.cases
                assert member.usage.cost_usd == Decimal("0.1") * args.cases
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
