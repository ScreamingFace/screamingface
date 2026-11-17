"""The image input matrix notebook's glue (image input matrix spec §3.5, plan Task 5). Pure.

``image_matrix`` decides what a cell means; this module turns what the stack returned into
cells, counts the evidence a refusal needs, guards the spend, and renders the matrix for
``matrix.json`` and the notebook's display cell. The notebook's own cells only call the stack
and these functions, so every decision is pinned by ``test_image_notebook`` without a paid run.

WHY upstream calls are counted from dispatch evidence, not from every gateway line (Review
Focus 1): until engine-side url4 admission lands (PR #1853), a text-only model on the url4 path
is refused by the gateway's 422 backstop. That refusal is itself one gateway request under the
trace (accounting opens for it) but never reaches the provider. The gateway logs no line for a
successful dispatch, so the evidence a call went upstream is a ``dispatch failed`` line (a
provider answered with an error) or a ``global cache fill`` (a provider answered and the reply
was stored). A refused cell with neither is refused before any paid call; a provider that
accepted the part and answered is ``answered``/``wrong`` and fails the verdict on its own.

WHY only answered cells report trace ids: the workbench requires every reported id in the
engine AND aigateway hops with a ``gateway_call_id``. A Benchmark refusal never reaches the
gateway, so its id would fail the chain for the very reason it passed the matrix. The refused
cells' ids stay in ``matrix.json`` for the reader.
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Final

from workbench.evidence import trace_id_tokens
from workbench.image_matrix import Cell, Expected, Observed, Path_, classify
from workbench.image_url4 import Url4Outcome
from workbench.redaction import redact

PROMPT: Final = "Reply with only the number (or word) shown in the attached file."
ANSWER_CAP: Final = 200  # spec §3.5: the answer excerpt in matrix.json
# WHY an estimate: the url4 sync response carries no cost (image_url4 NOTE), so the budget
# charges each url4 call that reached a model at this ceiling. Calibration (ledger, Task 4)
# measured ~$0.002 per FigQA Case with a full figure; a 320x120 fixture costs less.
URL4_CALL_ESTIMATE_USD: Final = Decimal("0.01")
BENCHMARK_CASE_ESTIMATE_USD: Final = Decimal("0.01")  # the same ceiling, per gold Case
# WHY a wildcard: served picture Benchmarks carry only png/jpeg/gif/webp (ledger, Task 4), all
# the gateway's `image` modality. A cell records the Case's real type once a Case Result names
# it; a run refused at admission has none, so it keeps this.
BENCHMARK_MEDIA: Final = "image/*"
_CALL_ID: Final = "gateway_call_id="
_DISPATCH_MARKS: Final = ("dispatch failed ", "global cache fill ")
_GATEWAY_TAG: Final = "[gateway] "
_MARKS: Final[dict[Observed, str]] = {
    "answered": "✓",
    "wrong": "✗",
    "error": "✗",
    "refused": "⊘",
    "skipped": "?",
}


def upstream_calls(runtime_log: str, trace_id: str) -> int:
    """Distinct gateway calls under ``trace_id`` that show a provider dispatch (module WHY)."""
    calls: set[str] = set()
    for line in runtime_log.splitlines():
        if _GATEWAY_TAG not in line or trace_id not in trace_id_tokens(line):
            continue
        if not any(mark in line for mark in _DISPATCH_MARKS):
            continue
        for part in line.split():
            if part.startswith(_CALL_ID) and len(part) > len(_CALL_ID):
                calls.add(part[len(_CALL_ID) :])
    return len(calls)


class Budget:
    """The notebook's spend guard: a call runs only if its projection fits what is left."""

    def __init__(self, limit_usd: Decimal) -> None:
        if limit_usd <= 0:
            raise ValueError(f"BUDGET_USD must be positive, got {limit_usd}")
        self.limit = limit_usd
        self.spent = Decimal(0)

    def allows(self, projected: Decimal) -> bool:
        return self.spent + projected <= self.limit

    def charge(self, amount: Decimal | None, *, estimate: Decimal = URL4_CALL_ESTIMATE_USD) -> None:
        """Add ``amount``; an unknown amount (``None``) is charged at ``estimate``."""
        self.spent += estimate if amount is None else amount


def _unknown_reason(model: str) -> str:
    return f"the gateway's /v1/models does not describe {model}"


def url4_cell(
    model: str,
    media_type: str,
    expected: Expected,
    outcome: Url4Outcome,
    expected_value: str,
    *,
    chat_calls: int | None,
) -> Cell:
    observed = classify(
        expected,
        answer=outcome.answer,
        error_code=outcome.error_code,
        expected_value=expected_value,
    )
    return Cell(
        "url4",
        model,
        media_type,
        expected,
        observed,
        outcome.answer,
        outcome.error_code,
        outcome.trace_id,
        outcome.spend_usd,
        _unknown_reason(model) if expected == "unknown" else None,
        chat_calls=chat_calls,
    )


def benchmark_cell(
    model: str,
    case: str,
    media_type: str,
    expected: Expected,
    *,
    error_code: str | None,
    graded_correct: bool | None,
    output: str | None,
    expected_value: str,
    trace_id: str | None,
    spend_usd: Decimal | None,
    chat_calls: int | None,
) -> Cell:
    """One gold Case. WHY the Benchmark's grade decides, not the token check: a FigQA reply
    reasons over every option letter, so ``B`` appears in a wrong answer too. Only an ungraded
    Case falls back to the known-answer check on its output."""
    if expected == "unknown" or error_code is not None or graded_correct is None:
        observed = classify(
            expected, answer=output, error_code=error_code, expected_value=expected_value
        )
    else:
        observed = "answered" if graded_correct else "wrong"
    return Cell(
        "benchmark",
        model,
        media_type,
        expected,
        observed,
        output,
        error_code,
        trace_id,
        spend_usd,
        _unknown_reason(model) if expected == "unknown" else None,
        case=case,
        chat_calls=chat_calls,
    )


def _case_outcome(case: Any) -> tuple[str | None, bool | None]:
    """(error code, graded correct) for one Case Result; a full-marks grade is correct."""
    if case.status == "failed":
        return (case.failures[0].code if case.failures else "case_failed"), None
    score = None if case.grade is None else case.grade.score
    return None, None if score is None else score >= 1.0


def benchmark_run_cells(
    model: str,
    benchmark: str,
    golds: Sequence[Mapping[str, Any]],
    expected: Expected,
    report: Any,
    error: Any,
) -> tuple[list[Cell], list[Any]]:
    """One ``evaluate`` over ``golds`` → one cell per gold Case, plus the Case Results found.

    ``report`` is the run's ``sf.Report`` (or an error's ``partial_report``), ``error`` the
    ``sf.ScreamingFaceError`` it raised, either ``None``. The run's spend lands on its first
    cell only, so summing ``spend_usd`` over the matrix never counts a run twice.
    """
    ran = list(report.candidates) if report is not None else []
    result = ran[0] if ran else None
    by_id = {str(c.case_id): c for c in result.cases} if result is not None else {}
    trace_id = (result.trace_id if result is not None else None) or getattr(error, "trace_id", None)
    spend = result.usage.cost_usd if result is not None else None
    cells: list[Cell] = []
    found: list[Any] = []
    for gold in golds:
        case = by_id.get(str(gold["case"]))
        output: str | None = None
        graded: bool | None = None
        media_type = BENCHMARK_MEDIA
        if case is None:
            code = getattr(error, "code", None) or "case_missing"
        else:
            found.append(case)
            code, graded = _case_outcome(case)
            output = case.output
            if case.media:
                media_type = case.media[0].media_type
        cells.append(
            benchmark_cell(
                model,
                f"{benchmark}#{gold['case']}",
                media_type,
                expected,
                error_code=code,
                graded_correct=graded,
                output=output,
                expected_value=str(gold["expected"]),
                trace_id=trace_id,
                spend_usd=spend if not cells else None,
                chat_calls=None,
            )
        )
    return cells, found


def skipped_cell(
    path: Path_,
    model: str,
    media_type: str,
    expected: Expected,
    reason: str,
    *,
    case: str | None = None,
) -> Cell:
    """A cell not run (budget, setup); ``coverage_failures`` fails it unless it was unknown."""
    return Cell(
        path, model, media_type, expected, "skipped", None, None, None, None, reason, case=case
    )


def coverage_failures(cells: Sequence[Cell]) -> list[str]:
    """Cells whose expectation was known but that never ran: unknown is never a pass."""
    return [
        f"{c.path} {c.model} {c.case or c.media_type}: not run — {c.reason or 'no reason'}"
        for c in cells
        if c.observed == "skipped" and c.expected != "unknown"
    ]


def reported_trace_ids(cells: Sequence[Cell]) -> list[str]:
    """The trace ids of cells that reached a model, deduplicated in order (module WHY)."""
    reached = (c.trace_id for c in cells if c.observed in ("answered", "wrong") and c.trace_id)
    return list(dict.fromkeys(reached))


def matrix_rows(cells: Sequence[Cell]) -> list[dict[str, Any]]:
    """``matrix.json`` rows: JSON-ready, answers redacted THEN capped at ``ANSWER_CAP``.

    WHY that order: a cap that cuts a key in half leaves a fragment no redaction pattern
    recognises, and the row is printed in the executed notebook before the bundle sees it.
    """
    rows: list[dict[str, Any]] = []
    for cell in cells:
        row = asdict(cell)
        row["answer"] = None if cell.answer is None else redact(cell.answer)[:ANSWER_CAP]
        row["spend_usd"] = None if cell.spend_usd is None else str(cell.spend_usd)
        rows.append(row)
    return rows


def _column(cell: Cell) -> str:
    return f"{cell.path} {cell.case if cell.case is not None else cell.media_type}"


def html_table(cells: Sequence[Cell]) -> str:
    """Model rows × path/media columns: ✓ answered, ✗ wrong or error, ⊘ refused, ? skipped."""
    columns = list(dict.fromkeys(_column(c) for c in cells))
    models = list(dict.fromkeys(c.model for c in cells))
    grid = {(c.model, _column(c)): c for c in cells}
    head = "".join(f"<th>{html.escape(col)}</th>" for col in columns)
    body = []
    for model in models:
        tds = []
        for col in columns:
            cell = grid.get((model, col))
            if cell is None:
                tds.append("<td></td>")
                continue
            title = html.escape(f"expected {cell.expected}; {cell.code or cell.reason or ''}")
            tds.append(f'<td title="{title}">{_MARKS[cell.observed]}</td>')
        body.append(f"<tr><th>{html.escape(model)}</th>{''.join(tds)}</tr>")
    return f"<table><tr><th>model</th>{head}</tr>{''.join(body)}</table>"
