"""Baking ContractEval: the public contract question and the private gold spans."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.contracteval.pins import MAX_CONTEXT_TOKENS
from screamingface_engine.benchmarks.contracteval.prepare import (
    PrepareError,
    case_records,
    emit,
)


def _row(
    row_id: str = "Doc__Governing Law",
    *,
    context: str = "1. Governing Law. This Agreement is governed by Delaware law.",
    question: str = "Which state's law governs this contract?",
    spans: list[str] | None = None,
    title: str = "Doc",
) -> dict[str, object]:
    return {
        "id": row_id,
        "title": title,
        "context": context,
        "question": question,
        "answers": {"text": list(spans or []), "answer_start": [0] * len(spans or [])},
    }


class TestCaseRecords:
    def test_the_public_case_carries_the_contract_and_the_question(self) -> None:
        cases, _ = case_records([_row()])

        assert cases[0]["id"] == 1
        assert "Governing Law" in str(cases[0]["input"])
        assert "Which state's law governs" in str(cases[0]["input"])

    def test_the_public_case_never_reveals_WHICH_sentences_are_the_answer(self) -> None:
        """INVARIANT: what stays private here is the LOCATION of the answer, not its text.

        Unlike MedXpertQA — where the gold letter must never appear in the prompt — a CUAD gold
        span is by construction a quotation FROM the contract, so its text is unavoidably inside
        the public input; that is the task. The leak to guard against is any marker saying which
        sentences those are: a `gold_spans` list, an `answer_start` offset, or highlighting.
        """

        cases, _ = case_records([_row(spans=["governed by Delaware law"])])

        assert set(cases[0]) == {"id", "input"}
        for leaked in ("gold_spans", "answers", "answer_start", "is_positive"):
            assert leaked not in str(cases[0])

    def test_the_private_record_carries_the_gold_spans_and_polarity(self) -> None:
        _, answers = case_records([_row(spans=["governed by Delaware law"])])

        assert answers[1]["gold_spans"] == ["governed by Delaware law"]
        assert answers[1]["is_positive"] is True
        assert answers[1]["source_id"] == "Doc__Governing Law"

    def test_a_row_with_no_gold_spans_is_marked_negative(self) -> None:
        _, answers = case_records([_row(spans=[])])

        assert answers[1]["gold_spans"] == []
        assert answers[1]["is_positive"] is False

    def test_case_ids_are_one_based_and_follow_row_order(self) -> None:
        """WHY pinned: aggregate indexes rows BY POSITION against the selected case ids."""

        cases, answers = case_records([_row("a"), _row("b"), _row("c")])

        assert [c["id"] for c in cases] == [1, 2, 3]
        assert sorted(answers) == [1, 2, 3]

    def test_a_gold_span_that_is_not_a_string_is_refused(self) -> None:
        row = _row()
        row["answers"] = {"text": [17], "answer_start": [0]}

        with pytest.raises(PrepareError, match="gold span"):
            case_records([row])

    def test_an_empty_contract_is_refused(self) -> None:
        with pytest.raises(PrepareError, match="context"):
            case_records([_row(context="   ")])

    def test_an_empty_question_is_refused(self) -> None:
        with pytest.raises(PrepareError, match="question"):
            case_records([_row(question="")])

    def test_an_over_budget_contract_fails_the_build(self) -> None:
        """PROTOCOL (spec D-7): there is NO truncation path. The largest real contract is
        63,389 tokens against a 120,000 budget, so this guard never fires on the pinned
        revision — it exists so a future revision that grew a document fails the BUILD instead
        of silently scoring a model against text it never saw."""

        oversized = "word " * (MAX_CONTEXT_TOKENS + 1000)

        with pytest.raises(PrepareError, match="exceeds the context budget"):
            case_records([_row(context=oversized)])


class TestEmit:
    def test_writes_the_public_file_and_one_private_record_per_case(self, tmp_path: Path) -> None:
        summary = emit([_row("a", spans=["x"]), _row("b", spans=[])], tmp_path)

        cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
        assert len(cases) == 2
        assert (tmp_path / "answers" / "1.json").exists()
        assert (tmp_path / "answers" / "2.json").exists()
        assert summary["cases"] == 2

    def test_the_audit_summary_reports_the_polarity_split(self, tmp_path: Path) -> None:
        """WHY it matters: the negative share drives the laziness denominator and is the number
        that tells a reader an always-abstaining model would score 70% accuracy."""

        summary = emit([_row("a", spans=["x"]), _row("b"), _row("c")], tmp_path)

        assert summary["positive_cases"] == 1
        assert summary["negative_cases"] == 2

    def test_the_audit_summary_names_the_pinned_revision(self, tmp_path: Path) -> None:
        summary = emit([_row()], tmp_path)

        assert summary["dataset_revision"]
        assert summary["split"] == "test"


class TestModuleEntryPoint:
    def test_prepare_is_runnable_as_a_module(self) -> None:
        """REGRESSION: the SDK bakes assets by spawning
        `python -m screamingface_engine.benchmarks.contracteval.prepare --out <dir>`, so a
        missing `main` fails only at bake time with "prepared output is missing [...]", which
        names the symptom and hides the cause. The family guard in test_benchmark_deployment
        checks that the command STRING matches its regex — not that the module answers it.
        """

        from screamingface_engine.benchmarks.contracteval import prepare as module

        assert callable(module.main)

    def test_the_entry_point_reports_a_prepare_failure_as_exit_1(self, tmp_path: Path) -> None:
        from screamingface_engine.benchmarks.contracteval import prepare as module

        def _boom() -> list[dict[str, object]]:
            raise PrepareError("dataset unavailable")

        original = module.load_rows
        module.load_rows = _boom  # type: ignore[assignment]
        try:
            assert module.main(["--out", str(tmp_path)]) == 1
        finally:
            module.load_rows = original  # type: ignore[assignment]
