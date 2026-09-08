"""The ContractEval reducer — the only one that builds a confusion matrix instead of a mean."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.contracteval.aggregate import (
    AggregateError,
    aggregate,
    selected_cases,
)
from screamingface_engine.benchmarks.contracteval.case_evaluation import (
    CHECK_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine.benchmarks.contracteval.definition import BENCHMARK_ID, REVISION


def _root(tmp_path: Path, polarity: dict[int, bool]) -> Path:
    (tmp_path / "answers").mkdir()
    (tmp_path / "cases.json").write_text(
        json.dumps([{"id": i, "input": f"Contract {i}?"} for i in polarity]), encoding="utf-8"
    )
    for case_id, is_positive in polarity.items():
        (tmp_path / "answers" / f"{case_id}.json").write_text(
            json.dumps(
                {
                    "source_id": f"Doc__Q{case_id}",
                    "title": "Doc",
                    "question": "Q?",
                    "gold_spans": ["a clause"] if is_positive else [],
                    "is_positive": is_positive,
                }
            ),
            encoding="utf-8",
        )
    return tmp_path


def _record(case_id: int, *, correct: bool, is_positive: bool, abstained: bool, jac: float = 0.5):
    return {
        "schema": CHECK_SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "correct": correct,
        "is_positive": is_positive,
        "abstained": abstained,
        "jaccard": jac,
        "status": "completed",
        "refusal": None,
        "finish_reason": "stop",
        "output": "reply",
    }


def _rows(*records: dict) -> str:
    return json.dumps(
        [
            case_execution_payload(
                r["case_id"],
                encode_candidate_invocation("reply", "stop", None),
                [bind_case_evaluation(r["case_id"], [r])],
            )
            for r in records
        ]
    )


def _aggregate(root: Path, raw: str, case_ids: tuple[int, ...]) -> dict:
    return aggregate(
        raw, root, benchmark_id=BENCHMARK_ID, benchmark_revision=REVISION, case_ids=case_ids
    )


class TestConfusionMatrix:
    def test_f1_and_f2_match_hand_computed_values(self, tmp_path: Path) -> None:
        """2 TP, 1 FN, 1 FP, 1 TN -> P=2/3, R=2/3, F1=2/3, F2=2/3."""

        root = _root(tmp_path, {1: True, 2: True, 3: True, 4: False, 5: False})
        rows = _rows(
            _record(1, correct=True, is_positive=True, abstained=False),
            _record(2, correct=True, is_positive=True, abstained=False),
            _record(3, correct=False, is_positive=True, abstained=False),
            _record(4, correct=False, is_positive=False, abstained=False),
            _record(5, correct=True, is_positive=False, abstained=True),
        )

        result = _aggregate(root, rows, (1, 2, 3, 4, 5))

        assert result["metrics"]["true_positives"] == 2
        assert result["metrics"]["false_negatives"] == 1
        assert result["metrics"]["false_positives"] == 1
        assert result["metrics"]["true_negatives"] == 1
        assert result["metrics"]["precision"] == pytest.approx(2 / 3, abs=1e-4)
        assert result["metrics"]["recall"] == pytest.approx(2 / 3, abs=1e-4)
        assert result["score"] == pytest.approx(2 / 3, abs=1e-4)
        assert result["metrics"]["f2"] == pytest.approx(2 / 3, abs=1e-4)

    def test_f1_is_the_headline_score_not_accuracy(self, tmp_path: Path) -> None:
        """PROTOCOL (spec D-2): with a 70/30 negative skew, accuracy rewards always-abstaining.
        The paper's headline is F1 and so is ours."""

        root = _root(tmp_path, {1: True, 2: False, 3: False})
        rows = _rows(
            _record(1, correct=False, is_positive=True, abstained=True),
            _record(2, correct=True, is_positive=False, abstained=True),
            _record(3, correct=True, is_positive=False, abstained=True),
        )

        result = _aggregate(root, rows, (1, 2, 3))

        assert result["metrics"]["accuracy"] == pytest.approx(2 / 3, abs=1e-4)
        assert result["score"] == 0.0

    def test_an_always_abstaining_model_scores_zero_instead_of_dividing_by_zero(
        self, tmp_path: Path
    ) -> None:
        """NAMED DEVIATION (spec, Task 3): the reference computes 2PR/(P+R) with no guard and
        raises ZeroDivisionError here. Given the 70/30 skew this is a realistic model, so we
        return 0.0 — the mathematically correct limit for a model that never scores a TP."""

        root = _root(tmp_path, {1: True, 2: True})
        rows = _rows(
            _record(1, correct=False, is_positive=True, abstained=True),
            _record(2, correct=False, is_positive=True, abstained=True),
        )

        result = _aggregate(root, rows, (1, 2))

        assert result["score"] == 0.0
        assert result["metrics"]["f2"] == 0.0
        assert result["metrics"]["precision"] == 0.0


class TestLaziness:
    def test_divides_by_the_selected_positives_not_the_reference_constant(
        self, tmp_path: Path
    ) -> None:
        """PROTOCOL (spec D-3): the reference divides by a hardcoded 1244 — the FULL split's
        positive count — which is wrong for any subset run. Two positives selected, one falsely
        abstained -> 0.5, not 1/1244."""

        root = _root(tmp_path, {1: True, 2: True, 3: False})
        rows = _rows(
            _record(1, correct=False, is_positive=True, abstained=True),
            _record(2, correct=True, is_positive=True, abstained=False),
            _record(3, correct=True, is_positive=False, abstained=True),
        )

        result = _aggregate(root, rows, (1, 2, 3))

        assert result["metrics"]["false_no_related_clause_rate"] == pytest.approx(0.5)

    def test_counts_every_abstention_including_the_correct_ones(self, tmp_path: Path) -> None:
        root = _root(tmp_path, {1: True, 2: False})
        rows = _rows(
            _record(1, correct=False, is_positive=True, abstained=True),
            _record(2, correct=True, is_positive=False, abstained=True),
        )

        result = _aggregate(root, rows, (1, 2))

        assert result["metrics"]["no_related_clause_rate"] == pytest.approx(1.0)


class TestJaccard:
    def test_the_mean_skips_negative_rows(self, tmp_path: Path) -> None:
        """PROTOCOL (spec F-5): Evaluation.py `continue`s on empty labels, so a negative row
        never enters the Jaccard population — averaging it in would dilute the number."""

        root = _root(tmp_path, {1: True, 2: False})
        rows = _rows(
            _record(1, correct=True, is_positive=True, abstained=False, jac=0.8),
            _record(2, correct=True, is_positive=False, abstained=True, jac=0.0),
        )

        result = _aggregate(root, rows, (1, 2))

        assert result["metrics"]["jaccard_mean"] == pytest.approx(0.8)

    def test_is_zero_when_no_positive_case_was_selected(self, tmp_path: Path) -> None:
        root = _root(tmp_path, {1: False})
        rows = _rows(_record(1, correct=True, is_positive=False, abstained=True))

        result = _aggregate(root, rows, (1,))

        assert result["metrics"]["jaccard_mean"] == 0.0


class TestCaseLevel:
    def test_a_correct_case_scores_one_and_a_wrong_case_zero(self, tmp_path: Path) -> None:
        root = _root(tmp_path, {1: True, 2: True})
        rows = _rows(
            _record(1, correct=True, is_positive=True, abstained=False),
            _record(2, correct=False, is_positive=True, abstained=False),
        )

        result = _aggregate(root, rows, (1, 2))

        assert [c["grade"]["score"] for c in result["cases"]] == [1.0, 0.0]
        assert result["cases"][0]["grade"]["method"] == "containment"

    def test_a_case_with_no_row_is_a_visible_failure_not_a_zero(self, tmp_path: Path) -> None:
        """A Case that never ran has NOT been measured — score None, and out of the matrix."""

        root = _root(tmp_path, {1: True, 2: True})
        rows = _rows(_record(1, correct=True, is_positive=True, abstained=False))

        result = _aggregate(root, rows, (1, 2))

        assert result["cases"][1]["grade"]["score"] is None
        assert result["cases"][1]["failures"][0]["code"] == "missing_case_row"
        assert result["metrics"]["true_positives"] == 1
        assert result["metrics"]["false_negatives"] == 0

    def test_a_missing_answer_asset_fails_that_case_alone(self, tmp_path: Path) -> None:
        root = _root(tmp_path, {1: True, 2: True})
        (root / "answers" / "2.json").write_text("{}", encoding="utf-8")
        rows = _rows(
            _record(1, correct=True, is_positive=True, abstained=False),
            _record(2, correct=True, is_positive=True, abstained=False),
        )

        result = _aggregate(root, rows, (1, 2))

        assert result["cases"][1]["failures"][0]["code"] == "missing_answer_asset"
        assert result["cases"][0]["grade"]["score"] == 1.0


class TestInputGuards:
    def test_more_rows_than_selected_cases_aborts_before_scoring(self, tmp_path: Path) -> None:
        root = _root(tmp_path, {1: True, 2: True})
        rows = _rows(
            _record(1, correct=True, is_positive=True, abstained=False),
            _record(2, correct=True, is_positive=True, abstained=False),
        )

        with pytest.raises(AggregateError, match="rows for 1 selected Cases"):
            _aggregate(root, rows, (1,))

    def test_unusable_cases_json_aborts_before_scoring(self, tmp_path: Path) -> None:
        root = _root(tmp_path, {1: True})
        (root / "cases.json").write_text("{}", encoding="utf-8")

        rows = _rows(_record(1, correct=True, is_positive=True, abstained=False))

        with pytest.raises(AggregateError, match="must be a JSON array"):
            _aggregate(root, rows, (1,))

    def test_selected_cases_preserves_the_requested_order(self, tmp_path: Path) -> None:
        chosen = selected_cases(_root(tmp_path, {1: True, 2: False}), (2, 1))

        assert [c.case_id for c in chosen] == [2, 1]


class TestPolarityAgreement:
    def test_a_check_record_disagreeing_with_the_answer_key_fails_the_case(
        self, tmp_path: Path
    ) -> None:
        """INVARIANT: the baked answer key is the authority on a Case's polarity, and the check
        record carries its own copy. If the two disagree the assets and the run are out of step
        — a wrong revision, or a stale bundle — and silently trusting either one puts the Case
        in the WRONG confusion-matrix cell. Fail it loudly instead.
        """

        root = _root(tmp_path, {1: True})
        rows = _rows(_record(1, correct=True, is_positive=False, abstained=True))

        result = _aggregate(root, rows, (1,))

        assert result["cases"][0]["grade"]["score"] is None
        assert result["cases"][0]["failures"][0]["code"] == "polarity_mismatch"

    def test_agreement_scores_normally(self, tmp_path: Path) -> None:
        root = _root(tmp_path, {1: True})
        rows = _rows(_record(1, correct=True, is_positive=True, abstained=False))

        result = _aggregate(root, rows, (1,))

        assert result["cases"][0]["grade"]["score"] == 1.0


class TestEvidence:
    def test_raw_output_is_the_verdict_not_the_abstention_flag(self, tmp_path: Path) -> None:
        """`raw_output` is the deterministic producer's OUTPUT — here the containment verdict,
        matching IFEval's verifier evidence. Whether the model abstained is context, and lives
        in metadata beside the gold-span count."""

        root = _root(tmp_path, {1: True})
        rows = _rows(_record(1, correct=True, is_positive=True, abstained=False))

        evidence = _aggregate(root, rows, (1,))["cases"][0]["grade"]["checks"][0]["evidence"][0]

        assert evidence["raw_output"] is True
        assert evidence["outcome"] == "PASS"
        assert evidence["metadata"]["abstained"] is False
        assert evidence["metadata"]["gold_span_count"] == 1
