"""Authored cells for the offline completed-accounting review notebook."""

from __future__ import annotations

from textwrap import dedent

import nbformat
from nbformat import NotebookNode

_SAMPLE = """\
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from IPython.display import display

import screamingface as sf
from screamingface.case_result import CaseOperation
from screamingface.operation import OperationInfo


# Synthetic review data, not measured benchmark results. No network or model calls.
def observation(model, cost, *, cached=False):
    return sf.OperationAccounting(
        provider="demo",
        request_model=model,
        response_model=model,
        usage=sf.Usage(
            input_tokens=0 if cached else 1200,
            output_tokens=0 if cached else 240,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            reasoning_tokens=None,
            cost_usd=cost,
        ),
        provider_latency_ms=0 if cached else 1250,
        provider_attempts=0 if cached else 1,
        cache=sf.OperationCache(hits=int(cached), misses=int(not cached), bypasses=0, unknown=0),
    )


operations = [
    OperationInfo(id="a", kind="model", label="Member A"),
    OperationInfo(id="b", kind="model", label="Member B"),
    OperationInfo(id="synthesis", kind="synthesis", label="Synthesis", depends_on=["a", "b"]),
]


def sample_case(case_id, *, missing=False):
    records = [
        CaseOperation("a", "Paris", "stop", observation("demo/model-a", "0.01")),
        CaseOperation(
            "b",
            "Paris",
            "stop",
            None
            if missing
            else observation("demo/model-b", "0" if case_id == 2 else "0.02", cached=case_id == 2),
        ),
        CaseOperation("synthesis", "Paris", "stop", observation("demo/writer", "0.015")),
    ]
    evidence = sf.Evidence(
        sequence=1,
        producer=sf.EvidenceProducer(type="model", id="demo/judge"),
        valid=True,
        outcome="MET",
        raw_output="MET",
        explanation="Answer matches the reference.",
        accounting=observation("demo/judge", "0.005"),
    )
    grade = sf.CaseGrade(
        method="demo",
        score=1.0,
        metrics={},
        checks=[
            sf.Check(
                type="rubric",
                id="correct",
                label="Correct answer",
                evidence=[evidence],
                outcome="MET",
                score=1.0,
            )
        ],
    )
    return sf.CaseResult(
        case_id=case_id,
        input="What is the capital of France?",
        output="Paris",
        finish_reason="stop",
        grade=grade,
        failures=[],
        metadata={},
        operations=records,
    )


def review_report(*, missing=False):
    cases = [sample_case(1), sample_case(2, missing=missing)]
    benchmark = sf.BenchmarkInfo("accounting-review", "synthetic-v1", 2)
    start = datetime(2026, 9, 28, 12, tzinfo=UTC)
    candidate = sf.CandidateResult(
        benchmark=benchmark,
        run_id="synthetic-missing" if missing else "synthetic-review",
        started_at=start,
        completed_at=start + timedelta(seconds=8),
        name="Two models + synthesis + judge",
        kind="fusion",
        url4="(@)!'review'",
        models=["demo/model-a", "demo/model-b", "demo/writer"],
        operations=operations,
        score=1.0,
        coverage=1.0,
        metrics={"pass_rate": 1.0},
        cases=cases,
        members=[
            sf.MemberResult(
                operation_id=key,
                name=label,
                kind="model",
                models=[model],
                failures=None,
                duration_ms=None,
                usage=None,
            )
            for key, label, model in [
                ("a", "Member A", "demo/model-a"),
                ("b", "Member B", "demo/model-b"),
            ]
        ],
        failures=[],
        usage=sf.Usage(input_tokens=8400, output_tokens=1680, cost_usd="0.08"),
    )
    return sf.Report(benchmark=benchmark, case_count=2, candidates=[candidate])


report = review_report()
display(report)
"""


def cells() -> tuple[NotebookNode, ...]:
    md = nbformat.v4.new_markdown_cell
    code = nbformat.v4.new_code_cell
    return (
        md(
            "# Completed report accounting\n\nOffline review of OME-1031. These are clearly "
            "labelled **synthetic observations**, not benchmark results. Run all cells: no API "
            "keys, Engine, or paid model calls are needed.\n\n"
            "Start Jupyter from `packages/screamingface` in this checkout with "
            "`uv run --extra notebook --with jupyterlab --with ipykernel jupyter lab`. "
            "Open `examples/14_report_accounting.ipynb` and use its Python kernel. "
            "The released package does not include this draft feature yet."
        ),
        code(dedent(_SAMPLE).rstrip()),
        md(
            "## Check the numbers\n\nThe total is USD 0.08: "
            "generation USD 0.04, synthesis USD 0.03, "
            "grading USD 0.01. Case 2 has a cache hit for Member B, costing zero. "
            "Select a Case, then open **Cost & usage** to inspect its activity blocks. "
            "Provider time is summed processing time, not elapsed run duration."
        ),
        code(
            "view = report.candidates[0].accounting\n"
            "for stage, total in view.by_stage.items():\n"
            '    print(stage, total.usage.cost_usd, "USD", total.calls, "calls")\n'
            'assert view.unattributed_cost_usd == Decimal("0")\n'
            "assert view.by_case[2].cache.hits == 1\n"
            'assert view.by_member["a"].usage.cost_usd == Decimal("0.02")'
        ),
        md(
            "## Missing observations\n\nA missing record must read **Unknown**, not zero. "
            "The authoritative total is unchanged. The Python API exposes the same views "
            "by stage, operation, model, member, and Case."
        ),
        code(
            "incomplete = review_report(missing=True)\ndisplay(incomplete)\n"
            'assert incomplete.candidates[0].accounting.by_member["b"].usage.cost_usd is None'
        ),
        md(
            "## Your own run\n\nAfter running any supported benchmark with this Client, "
            "display the returned `report` and inspect `report.candidates[0].accounting`. "
            "The same views work across benchmarks. Availability depends on retained Engine "
            "records; loop internals remain unattributed. No live widget behavior changes."
        ),
    )
