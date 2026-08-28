"""GDPval runtime handlers — baked assets are parsed once, not once per call.

INVARIANT under test: baked assets are immutable for the process lifetime, and cases.json is
multi-MB (it embeds the flattened text of all 85 reference documents). A handler must read it
from disk at most once per closure — ~204 re-reads per 102-case run is pure waste, and any
observable difference between the first call and a later one would mean the cache lies.
"""

from __future__ import annotations

import json
from pathlib import Path

from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_SCHEMA,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.gdpval.pins import JUDGE_MODEL, JUDGE_PARAMS
from screamingface_engine.benchmarks.gdpval.runtime import (
    _cases,
    _rubric_tasks,
    _rubric_verdict,
)
from screamingface_engine.grading_accounting import capture_grading_requests
from screamingface_engine.operation_accounting import (
    OperationAccounting,
    OperationCache,
    OperationUsage,
)
from screamingface_engine.operation_calls import (
    capture_request_accounting,
    operation_call_identity,
    record_operation_call,
)
from url4.peer.server import Request

_CASE_IDS = (1, 2)


def _accounting() -> OperationAccounting:
    return OperationAccounting(
        provider="openrouter",
        request_model=JUDGE_MODEL,
        response_model=JUDGE_MODEL,
        usage=OperationUsage(
            input_tokens=20,
            output_tokens=3,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            reasoning_tokens=1,
            cost_usd="0.5",
        ),
        provider_latency_ms=75,
        cache=OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
    )


def _write_assets(root: Path) -> None:
    envelope = json.dumps(
        {
            "schema": CANDIDATE_INPUT_SCHEMA,
            "messages": [{"role": "user", "content": "Do the work."}],
        }
    )
    (root / "rubrics").mkdir(parents=True, exist_ok=True)
    (root / "cases.json").write_text(
        json.dumps([{"id": case_id, "input": envelope} for case_id in _CASE_IDS]),
        encoding="utf-8",
    )
    for case_id in _CASE_IDS:
        (root / "rubrics" / f"{case_id}.json").write_text(
            json.dumps(
                {
                    "task_id": f"task-{case_id}",
                    "items": [{"rubric_id": 1, "criterion": "is complete", "points": 2}],
                }
            ),
            encoding="utf-8",
        )


def _count_reads(monkeypatch, reads: list[Path]) -> None:
    original = Path.read_text

    def counting(self: Path, encoding: str | None = None, errors: str | None = None) -> str:
        reads.append(Path(self))
        return original(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", counting)


def test_the_cases_route_reads_the_baked_file_once(tmp_path, monkeypatch) -> None:
    _write_assets(tmp_path)
    reads: list[Path] = []
    _count_reads(monkeypatch, reads)

    handler = _cases(tmp_path, _CASE_IDS)
    first, second = handler(), handler()

    assert first == second
    assert reads.count(tmp_path / "cases.json") == 1


def test_rubric_tasks_read_the_baked_assets_once_per_case(tmp_path, monkeypatch) -> None:
    _write_assets(tmp_path)
    reads: list[Path] = []
    _count_reads(monkeypatch, reads)

    handler = _rubric_tasks(tmp_path, _CASE_IDS, "gdpval-text")
    context = encode_candidate_invocation("the deliverable", "stop", None)
    first = handler(Request(path="/t", context=context, intent="1", params={}))
    second = handler(Request(path="/t", context=context, intent="1", params={}))

    assert first == second
    assert reads.count(tmp_path / "cases.json") == 1
    assert reads.count(tmp_path / "rubrics" / "1.json") == 1


def test_rubric_verdict_retains_its_exact_request_accounting(tmp_path: Path) -> None:
    _write_assets(tmp_path)
    tasks = _rubric_tasks(tmp_path, _CASE_IDS, "gdpval-text")
    verdict = _rubric_verdict("gdpval-text")

    with capture_request_accounting():
        with capture_grading_requests():
            rows = json.loads(
                tasks(
                    Request(
                        path="/tasks",
                        context=encode_candidate_invocation("the deliverable", "stop", None),
                        intent="1",
                        params={},
                    )
                )
            )
            with operation_call_identity(
                "/" + JUDGE_MODEL.removeprefix("/"),
                dict(JUDGE_PARAMS),
                context=rows[0]["grader_prompt"],
                intent="",
            ):
                record_operation_call("judge reply", "stop", _accounting())
            record = json.loads(
                verdict(
                    Request(
                        path="/verdict",
                        context='{"explanation":"complete","criteria_met":true}',
                        intent="1:1",
                        params={},
                    )
                )
            )

    assert record["accounting"]["usage"]["cost_usd"] == "0.5"
