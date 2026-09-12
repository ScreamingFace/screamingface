"""DRACO pinned-dataset preparation.

FEATURE: a benchmark's declared world is generated from its dataset at image build.
STORY: as a benchmark author, `prepare` turns `perplexity-ai/draco` into cases, private rubrics,
and weight-free Judge criteria consumed by its installed runtime.

The HF download itself is not exercised — `build()` takes rows, so every test here runs offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.draco import prepare

_RUBRIC = {
    "sections": [
        {"id": "Factual Accuracy", "criteria": [{"id": "a1", "weight": 2, "requirement": "x"}]}
    ]
}


def _row(question: str = "What is X?", rubric: object | None = None) -> dict:
    return {
        "problem": question,
        "answer": json.dumps(_RUBRIC) if rubric is None else rubric,
        "domain": "finance",
    }


# --- artifacts ------------------------------------------------------------------


def test_dataset_download_is_pinned_to_the_benchmark_revision(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class Datasets:
        @staticmethod
        def load_dataset(dataset: str, *, revision: str):
            calls.append((dataset, revision))
            return {"train": [_row()]}

    monkeypatch.setattr(prepare.importlib, "import_module", lambda _name: Datasets)

    assert len(prepare.load_rows()) == 1
    assert calls == [(prepare.DATASET, prepare.DATASET_REVISION)]


def test_cases_json_carries_id_and_input(tmp_path: Path) -> None:
    prepare.build([_row("Q1"), _row("Q2")], tmp_path)

    cases = json.loads((tmp_path / "cases.json").read_text())
    assert cases[0]["id"] == 1
    assert cases[0]["input"] == "Q1"
    assert [c["id"] for c in cases] == [1, 2]


def test_cases_json_never_carries_the_rubric(tmp_path: Path) -> None:
    """INVARIANT: the privacy boundary of the whole design.

    The client receives `cases.json`; the rubric stays in the image. Leaking it here would let a
    Candidate be tuned against the answer key while every test still passed.
    """
    prepare.build([_row()], tmp_path)

    body = (tmp_path / "cases.json").read_text()
    assert "Factual Accuracy" not in body
    assert "weight" not in body


def test_each_rubric_is_written_to_its_own_file(tmp_path: Path) -> None:
    prepare.build([_row(), _row()], tmp_path)

    assert json.loads((tmp_path / "rubrics" / "1.json").read_text()) == _RUBRIC
    assert (tmp_path / "rubrics" / "2.json").exists()


def test_private_grading_artifacts_are_NOT_declared_as_routes(tmp_path: Path) -> None:
    """INVARIANT: criteria and weights must be unreachable from an expression.

    A declared `/draco/rubrics/N` could be fetched into a judge prompt, which is exactly the
    leak `grading_mode: official` exists to prevent. The task builder reads weight-free criteria
    and `aggregate.py` reads weighted rubrics directly from disk.
    """
    prepare.build([_row()], tmp_path)

    assert not (tmp_path / "url4.data.toml").exists()


def test_the_judge_facing_criteria_carry_no_weights(tmp_path: Path) -> None:
    prepare.build([_row()], tmp_path)

    criteria = json.loads((tmp_path / "criteria" / "1.json").read_text())
    assert criteria == [{"id": "a1", "requirement": "x", "criterion_type": "positive"}]
    assert "weight" not in json.dumps(criteria)


def test_the_judge_facing_criteria_derive_negative_type_without_leaking_weight(
    tmp_path: Path,
) -> None:
    rubric = json.dumps(
        {
            "sections": [
                {
                    "id": "quality",
                    "criteria": [{"id": "bad", "weight": -2, "requirement": "makes an error"}],
                }
            ]
        }
    )
    prepare.build([_row(rubric=rubric)], tmp_path)

    criteria = json.loads((tmp_path / "criteria" / "1.json").read_text())
    assert criteria == [
        {"id": "bad", "requirement": "makes an error", "criterion_type": "negative"}
    ]
    assert "weight" not in json.dumps(criteria)


# --- validation -----------------------------------------------------------------


def test_an_empty_question_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(prepare.PrepareError, match="empty"):
        prepare.build([_row("")], tmp_path)


def test_a_rubric_with_no_sections_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(prepare.PrepareError, match="sections"):
        prepare.build([_row(rubric=json.dumps([{"id": "a1"}]))], tmp_path)


def test_a_rubric_that_flattens_to_zero_criteria_is_rejected(tmp_path: Path) -> None:
    """It would score every answer 0.0 while looking like a successful run."""
    with pytest.raises(prepare.PrepareError, match="0 criteria"):
        prepare.build([_row(rubric=json.dumps({"sections": []}))], tmp_path)


def test_a_full_build_must_match_the_declared_case_count(tmp_path: Path) -> None:
    with pytest.raises(prepare.PrepareError, match="expected 100 DRACO cases"):
        prepare.build([_row()], tmp_path, expected_count=100)

    assert not any(tmp_path.iterdir())


# --- the round trip -------------------------------------------------------------


def test_prepared_rubrics_load_back_into_the_aggregator(tmp_path: Path) -> None:
    """The two halves must agree on the on-disk shape — this is the seam between them."""
    from screamingface_engine.benchmarks.draco import assets, scoring

    prepare.build([_row(), _row()], tmp_path)

    rubrics = assets.load_rubrics(tmp_path / "rubrics")
    assert set(rubrics) == {1, 2}
    assert scoring.normalized_score(rubrics[1], {"a1": True}) == 1.0
