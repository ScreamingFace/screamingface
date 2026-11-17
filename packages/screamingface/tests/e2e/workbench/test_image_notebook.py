"""The image input matrix notebook's glue (plan Task 5): rows, evidence counts, budget, display.

The notebook feeds these functions what the stack returned; pinning them here keeps the
notebook's own cells thin enough to read, and its decisions testable without a paid run.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from workbench.image_matrix import Cell
from workbench.image_notebook import (
    ANSWER_CAP,
    BENCHMARK_MEDIA,
    Budget,
    benchmark_cell,
    benchmark_run_cells,
    coverage_failures,
    html_table,
    matrix_rows,
    reported_trace_ids,
    skipped_cell,
    upstream_calls,
    url4_cell,
)
from workbench.image_url4 import Url4Outcome

TID = "a" * 32
OTHER = "b" * 32
MODEL = "openrouter/google/gemini-3-flash-preview"


def _gateway(*lines: str) -> str:
    return "".join(f"2026-11-17T10:00:00Z [gateway] INFO: {ln}\n" for ln in lines)


# --- upstream_calls -----------------------------------------------------------------------------


def test_a_refusal_before_dispatch_counts_no_upstream_call() -> None:
    """The gateway's 422 backstop opens accounting for the call but never dispatches it."""
    log = _gateway(
        f"usage accounting started provider=openrouter gateway_call_id=c1 supported=True "
        f"trace_id={TID} gateway_call_id=c1"
    )
    assert upstream_calls(log, TID) == 0


def test_dispatch_evidence_counts_each_call_once() -> None:
    log = _gateway(
        f"usage accounting started provider=openrouter trace_id={TID} gateway_call_id=c1",
        f"global cache fill new provider=openrouter trace_id={TID} gateway_call_id=c1",
        f"dispatch failed provider=openrouter status=400 trace_id={TID} gateway_call_id=c2",
        f"dispatch failed provider=openrouter status=400 trace_id={TID} gateway_call_id=c2",
    )
    assert upstream_calls(log, TID) == 2


def test_upstream_calls_ignore_other_traces_and_other_services() -> None:
    log = _gateway(
        f"dispatch failed provider=openrouter trace_id={OTHER} gateway_call_id=c9",
    ) + (f"2026-11-17T10:00:00Z [engine] dispatch failed trace_id={TID} gateway_call_id=c3\n")
    assert upstream_calls(log, TID) == 0


def test_a_parent_trace_id_is_not_this_trace() -> None:
    log = _gateway(f"dispatch failed parent_trace_id={TID} gateway_call_id=c1")
    assert upstream_calls(log, TID) == 0


# --- cells --------------------------------------------------------------------------------------


def test_url4_cell_classifies_the_outcome() -> None:
    outcome = Url4Outcome(TID, "The number is 7392.", None)
    cell = url4_cell(MODEL, "image/png", "answer", outcome, "7392", chat_calls=1)
    assert (cell.path, cell.observed, cell.trace_id, cell.chat_calls) == (
        "url4",
        "answered",
        TID,
        1,
    )


def test_url4_refusal_keeps_its_code() -> None:
    outcome = Url4Outcome(TID, None, "intent_error")
    cell = url4_cell(MODEL, "application/pdf", "refuse", outcome, "HELIOTROPE", chat_calls=0)
    assert (cell.observed, cell.code) == ("refused", "intent_error")


def test_url4_unknown_expectation_is_skipped_with_a_reason() -> None:
    outcome = Url4Outcome(TID, "7392", None)
    cell = url4_cell(MODEL, "image/png", "unknown", outcome, "7392", chat_calls=None)
    assert cell.observed == "skipped" and cell.reason


@pytest.mark.parametrize(
    ("graded", "error", "output", "observed"),
    [
        (True, None, "ANSWER: B", "answered"),
        (False, None, "ANSWER: A", "wrong"),
        # Ungraded: fall back to the known-answer check on the output.
        (None, None, "ANSWER: B", "answered"),
        (None, "intent_error", None, "refused"),
        (None, "provider_error", None, "error"),
    ],
)
def test_benchmark_cell_trusts_the_benchmark_scorer(
    graded: bool | None, error: str | None, output: str | None, observed: str
) -> None:
    cell = benchmark_cell(
        MODEL,
        "inspect-lab_bench_figqa#1",
        "image/jpeg",
        "answer",
        error_code=error,
        graded_correct=graded,
        output=output,
        expected_value="B",
        trace_id=TID,
        spend_usd=Decimal("0.001"),
        chat_calls=None,
    )
    assert cell.observed == observed
    assert cell.path == "benchmark" and cell.case == "inspect-lab_bench_figqa#1"


def test_skipped_cell_names_why() -> None:
    cell = skipped_cell("url4", MODEL, "image/gif", "answer", "budget exhausted")
    assert cell.observed == "skipped" and cell.reason == "budget exhausted"


# --- coverage, trace ids, rows ------------------------------------------------------------------


def _cell(**over: Any) -> Cell:
    base: dict[str, Any] = {
        "path": "url4",
        "model": MODEL,
        "media_type": "image/png",
        "expected": "answer",
        "observed": "answered",
        "answer": "7392",
        "code": None,
        "trace_id": TID,
        "spend_usd": None,
        "reason": None,
    }
    return Cell(**(base | over))


def test_a_known_cell_left_unrun_is_a_coverage_failure() -> None:
    """Unknown is never a pass: a cell the budget stopped proved nothing."""
    cells = [
        _cell(observed="skipped", reason="budget exhausted"),
        _cell(expected="unknown", observed="skipped", reason="not listed"),
        _cell(),
    ]
    (failure,) = coverage_failures(cells)
    assert "budget exhausted" in failure


def test_reported_trace_ids_are_the_cells_that_reached_a_model() -> None:
    """A refused cell never reached the gateway's model hop, so its id cannot satisfy the
    trace-chain check; only cells that produced an answer (right or wrong) report theirs."""
    cells = [
        _cell(trace_id="1" * 32),
        _cell(trace_id="1" * 32, media_type="image/gif"),
        _cell(trace_id="2" * 32, observed="wrong", answer="1111"),
        _cell(trace_id="3" * 32, expected="refuse", observed="refused", code="intent_error"),
        _cell(trace_id=None),
    ]
    assert reported_trace_ids(cells) == ["1" * 32, "2" * 32]


def test_matrix_rows_are_json_and_cap_the_answer() -> None:
    cells = [
        _cell(answer="7392 " + "x" * 500, spend_usd=Decimal("0.0012"), chat_calls=1),
        _cell(path="benchmark", case="b#1", answer=None),
    ]
    rows = matrix_rows(cells)
    json.dumps(rows)
    assert len(rows[0]["answer"]) == ANSWER_CAP
    assert rows[0]["spend_usd"] == "0.0012"
    assert rows[0]["chat_calls"] == 1
    assert rows[1]["case"] == "b#1" and rows[1]["answer"] is None
    assert set(rows[0]) == {
        "path",
        "model",
        "media_type",
        "case",
        "expected",
        "observed",
        "answer",
        "code",
        "trace_id",
        "spend_usd",
        "reason",
        "chat_calls",
    }


# --- budget -------------------------------------------------------------------------------------


def test_budget_refuses_a_call_that_would_overrun() -> None:
    budget = Budget(Decimal("0.05"))
    assert budget.allows(Decimal("0.04"))
    budget.charge(Decimal("0.04"))
    assert not budget.allows(Decimal("0.02"))
    assert budget.allows(Decimal("0.01"))
    assert budget.spent == Decimal("0.04")


def test_budget_counts_an_unknown_spend_at_its_estimate() -> None:
    budget = Budget(Decimal("0.05"))
    budget.charge(None, estimate=Decimal("0.03"))
    assert budget.spent == Decimal("0.03")


def test_budget_refuses_a_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="BUDGET_USD"):
        Budget(Decimal("0"))


# --- display ------------------------------------------------------------------------------------


def test_html_table_marks_each_outcome_and_escapes() -> None:
    cells = [
        _cell(),
        _cell(media_type="image/gif", observed="wrong", answer="1"),
        _cell(media_type="application/pdf", expected="refuse", observed="refused"),
        _cell(media_type="image/webp", observed="skipped", expected="unknown"),
        _cell(model="<x>", path="benchmark", case="b#1", observed="error"),
    ]
    html = html_table(cells)
    for mark in ("✓", "✗", "⊘", "?"):
        assert mark in html
    assert "<x>" not in html and "&lt;x&gt;" in html
    assert "url4 image/png" in html and "benchmark b#1" in html


# --- benchmark_run_cells ------------------------------------------------------------------------


class _Grade:
    def __init__(self, score: float | None) -> None:
        self.score = score


class _Failure:
    code = "provider_error"


class _Media:
    media_type = "image/jpeg"


class _Case:
    def __init__(self, case_id: int | str, *, score: float | None = 1.0, failed: bool = False):
        self.case_id = case_id
        self.status = "failed" if failed else "scored"
        self.failures = (_Failure(),) if failed else ()
        self.grade = None if score is None else _Grade(score)
        self.output = "ANSWER: B"
        self.media = (_Media(),)


class _Usage:
    cost_usd = Decimal("0.003")


class _Candidate:
    def __init__(self, *cases: _Case) -> None:
        self.trace_id = TID
        self.usage = _Usage()
        self.cases = cases


class _Report:
    def __init__(self, *cases: _Case) -> None:
        self.candidates = [_Candidate(*cases)]


class _Error(Exception):
    def __init__(self, code: str, trace_id: str | None) -> None:
        self.code = code
        self.trace_id = trace_id


GOLDS = [
    {"benchmark": "b", "case": 1, "expected": "B"},
    {"benchmark": "b", "case": 2, "expected": "F"},
]


def test_a_run_yields_one_cell_per_gold_case_with_the_run_spend_once() -> None:
    cells, cases = benchmark_run_cells(
        MODEL, "b", GOLDS, "answer", _Report(_Case(1), _Case("2", score=0.0)), None
    )
    assert [(c.case, c.observed) for c in cells] == [("b#1", "answered"), ("b#2", "wrong")]
    assert [c.media_type for c in cells] == ["image/jpeg", "image/jpeg"]
    assert [c.spend_usd for c in cells] == [Decimal("0.003"), None]
    assert {c.trace_id for c in cells} == {TID}
    assert len(cases) == 2


def test_a_run_refused_at_admission_is_refused_on_every_case() -> None:
    cells, cases = benchmark_run_cells(
        MODEL, "b", GOLDS[:1], "refuse", None, _Error("intent_error", OTHER)
    )
    assert [(c.observed, c.code, c.trace_id) for c in cells] == [("refused", "intent_error", OTHER)]
    assert [c.media_type for c in cells] == [BENCHMARK_MEDIA]
    assert cases == []


def test_a_failed_or_missing_case_is_an_error() -> None:
    cells, _ = benchmark_run_cells(
        MODEL, "b", GOLDS, "answer", _Report(_Case(1, failed=True)), None
    )
    assert [(c.observed, c.code) for c in cells] == [
        ("error", "provider_error"),
        ("error", "case_missing"),
    ]
