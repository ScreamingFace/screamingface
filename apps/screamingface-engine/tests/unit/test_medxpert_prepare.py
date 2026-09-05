"""Baking the MedXpertQA assets — and every way the build refuses to bake a wrong exam.

INVARIANT under test: the baked `input` is the row's question VERBATIM. MedXpertQA embeds its
choice list inside the question text, so re-rendering `options` into the prompt would duplicate
every choice — a silently degraded prompt that shifts scores against the published leaderboard
with nothing in the output pointing at the cause.

INVARIANT under test: the answer key never reaches `cases.json`. A client sees ids and questions.
"""

from __future__ import annotations

import json

import pytest

from screamingface_engine.benchmarks.medxpert.prepare import (
    PrepareError,
    case_records,
    emit,
)

_QUESTION = (
    "Which agent is indicated? Answer Choices: (A) alpha (B) beta (C) gamma (D) delta "
    "(E) epsilon (F) zeta (G) eta (H) theta (I) iota (J) kappa"
)
_OPTIONS = {k: f"choice {k}" for k in "ABCDEFGHIJ"}


def _row(row_id: str = "Text-0", *, label: str = "E", options: dict | None = None) -> dict:
    return {
        "id": row_id,
        "question": _QUESTION,
        "options": _OPTIONS if options is None else options,
        "label": label,
        "medical_task": "Diagnosis",
        "body_system": "Cardiovascular",
        "question_type": "Reasoning",
    }


def _rows(count: int = 3) -> list[dict]:
    return [_row(f"Text-{i}", label="ABCDEFGHIJ"[i % 10]) for i in range(count)]


def test_the_baked_input_is_the_question_verbatim() -> None:
    # THE F1a REGRESSION. If a future change appends the rendered options, this fails — which is
    # the only signal available, since a duplicated choice list still produces plausible scores.
    cases, _ = case_records(_rows(1))
    assert cases[0]["input"] == _QUESTION
    assert cases[0]["input"].count("(A)") == 1


def test_case_ids_are_one_based_positions() -> None:
    cases, _ = case_records(_rows(3))
    assert [case["id"] for case in cases] == [1, 2, 3]


def test_cases_carry_no_answer_key() -> None:
    cases, _ = case_records(_rows(2))
    assert {key for case in cases for key in case} == {"id", "input"}


def test_the_private_record_carries_the_label_and_metadata() -> None:
    _, answers = case_records(_rows(1))
    record = answers[1]
    assert record["label"] == "A"
    assert record["options_count"] == 10
    assert record["source_id"] == "Text-0"
    assert record["metadata"]["question_type"] == "Reasoning"


def test_a_label_outside_its_own_options_fails_the_build() -> None:
    # INVARIANT: an unanswerable row must stop the build. Serving it would mark every candidate
    # wrong on that row regardless of what they answered.
    with pytest.raises(PrepareError, match="label"):
        case_records([_row(label="Z")])


def test_options_that_are_not_a_contiguous_letter_map_fail_the_build() -> None:
    with pytest.raises(PrepareError, match="options"):
        case_records([_row(options={"A": "a", "C": "c"})])


def test_an_empty_question_fails_the_build() -> None:
    row = _row()
    row["question"] = "   "
    with pytest.raises(PrepareError, match="question"):
        case_records([row])


def test_emit_writes_public_cases_and_private_answers(tmp_path) -> None:
    summary = emit(_rows(3), tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text())
    assert summary["cases"] == len(cases) == 3
    assert len(list((tmp_path / "answers").glob("*.json"))) == 3


def test_emit_is_byte_identical_across_runs(tmp_path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    emit(_rows(3), first)
    emit(_rows(3), second)
    assert (first / "cases.json").read_bytes() == (second / "cases.json").read_bytes()
    assert (first / "answers" / "1.json").read_bytes() == (
        second / "answers" / "1.json"
    ).read_bytes()


def test_the_summary_names_the_pinned_revision(tmp_path) -> None:
    # OME-925: the orchestrator records this per bundle so a later failure cannot erase the
    # evidence for bundles that already landed.
    summary = emit(_rows(2), tmp_path)
    assert summary["dataset_revision"]
    assert summary["out"] == str(tmp_path)
