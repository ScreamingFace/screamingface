"""Baking the GDPval text-subset assets — and every way the build refuses to bake a wrong one.

INVARIANT under test: the preparer's output IS the answer key. It must be reproducible byte for
byte, it must refuse to proceed when the upstream dataset has moved under the frozen selection,
and it must refuse to bake a Case whose rubric cannot produce a score.

AIDEV-NOTE: `datasets`, `pdfplumber` and `python-docx` are build-time only and absent here, so
these tests drive the pure functions and inject a fake reference reader. `load_rows` is the one
seam that talks to HuggingFace and is exercised at image build.
"""

from __future__ import annotations

import json

import pytest

from screamingface_engine.benchmarks.gdpval.prepare import (
    PrepareError,
    case_input,
    emit,
    rubric_items,
    select_rows,
)
from screamingface_engine.benchmarks.gdpval.subset import TEXT_SUBSET_TASK_IDS

_CONTENT = "The memo identifies the three highest-risk findings."
_CONTAINER = "Submission is provided as a Microsoft Word (.docx) document"


def _rubric(*items: tuple[int, str]) -> str:
    return json.dumps([{"score": s, "criterion": c} for s, c in items])


def _row(task_id: str, *, refs: tuple[str, ...] = (), rubric: str | None = None) -> dict:
    return {
        "task_id": task_id,
        "prompt": f"Do the work for {task_id}.",
        "reference_files": list(refs),
        "rubric_json": rubric if rubric is not None else _rubric((2, _CONTENT)),
    }


def _all_rows() -> list[dict]:
    # Deliberately shuffled: the preparer must impose the frozen order, not inherit it.
    return [_row(t) for t in reversed(TEXT_SUBSET_TASK_IDS)]


def _reader(_task_id: str, file_name: str) -> str:
    return f"extracted text of {file_name}" + "." * 300


def test_selection_returns_the_frozen_tasks_in_frozen_order() -> None:
    selected = select_rows(_all_rows())
    assert [r["task_id"] for r in selected] == list(TEXT_SUBSET_TASK_IDS)


def test_a_missing_task_fails_the_build_and_names_it() -> None:
    # INVARIANT: the dataset moving under the frozen selection must stop the build, never
    # silently bake a smaller exam under the same identity.
    rows = [r for r in _all_rows() if r["task_id"] != TEXT_SUBSET_TASK_IDS[0]]
    with pytest.raises(PrepareError) as excinfo:
        select_rows(rows)
    assert TEXT_SUBSET_TASK_IDS[0] in str(excinfo.value)


def test_extra_upstream_tasks_are_ignored_not_served() -> None:
    rows = [*_all_rows(), _row("a-task-not-in-the-subset")]
    assert len(select_rows(rows)) == len(TEXT_SUBSET_TASK_IDS)


def test_container_criteria_are_absent_from_the_baked_rubric() -> None:
    row = _row("t", rubric=_rubric((2, _CONTENT), (2, _CONTAINER)))
    items = rubric_items(row, 1)
    assert [i["criterion"] for i in items] == [_CONTENT]


def test_a_rubric_left_without_positive_points_fails_the_build() -> None:
    # WHY: the Case score is points earned over POSITIVE points available. A rubric whose only
    # positive criteria were container checks would divide by zero.
    row = _row("t", rubric=_rubric((2, _CONTAINER), (-5, _CONTENT)))
    with pytest.raises(PrepareError, match="positive"):
        rubric_items(row, 1)


def test_non_integer_points_fail_the_build() -> None:
    # INVARIANT: the judge must see "[7]", never "[7.0]" — a float silently changes the grader
    # prompt's bytes for every future run.
    row = _row("t", rubric=json.dumps([{"score": 2.0, "criterion": _CONTENT}]))
    with pytest.raises(PrepareError, match="integer"):
        rubric_items(row, 1)


def test_case_input_carries_the_prompt_and_every_reference() -> None:
    row = _row("t", refs=("a.pdf", "b.docx"))
    body = json.loads(case_input(row, reader=_reader))["messages"][0]["content"]
    assert row["prompt"] in body
    assert "a.pdf" in body and "b.docx" in body


def test_case_input_orders_references_as_the_dataset_lists_them() -> None:
    # INVARIANT: reference order is part of the answer key — two builds must agree.
    row = _row("t", refs=("second.pdf", "first.pdf"))
    body = json.loads(case_input(row, reader=_reader))["messages"][0]["content"]
    assert body.index("second.pdf") < body.index("first.pdf")


def test_emit_writes_one_case_and_one_rubric_per_selected_task(tmp_path) -> None:
    count = emit(_all_rows(), tmp_path, reader=_reader)
    cases = json.loads((tmp_path / "cases.json").read_text())
    assert count == len(TEXT_SUBSET_TASK_IDS) == len(cases)
    assert [c["id"] for c in cases] == list(range(1, len(cases) + 1))
    assert len(list((tmp_path / "rubrics").glob("*.json"))) == len(cases)


def test_cases_json_carries_no_rubric(tmp_path) -> None:
    # INVARIANT: the client sees Case ids and inputs; the answer key stays in the image.
    #
    # AIDEV-NOTE: assert the STRUCTURE, never a substring. An earlier version of this test
    # searched cases.json for "criterion" and passed — on synthetic prompts. Real GDPval task
    # text says things like "Endotoxin Level: < 1 EU/ml as a release criterion", so the
    # substring form fails for an innocent reason while proving nothing about the invariant.
    emit(_all_rows(), tmp_path, reader=_reader)
    cases = json.loads((tmp_path / "cases.json").read_text())
    assert {key for case in cases for key in case} == {"id", "input"}
    envelope = json.loads(cases[0]["input"])
    assert set(envelope) == {"schema", "messages"}
    assert set(envelope["messages"][0]) == {"role", "content"}


def test_emit_is_byte_identical_across_runs(tmp_path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    emit(_all_rows(), first, reader=_reader)
    emit(_all_rows(), second, reader=_reader)
    assert (first / "cases.json").read_bytes() == (second / "cases.json").read_bytes()
    assert (first / "rubrics" / "1.json").read_bytes() == (
        second / "rubrics" / "1.json"
    ).read_bytes()


def test_rubric_ids_are_one_based_positions() -> None:
    # INVARIANT: `scoring.case_score` indexes points with enumerate(points, start=1) and
    # `verdict.binding_key` refuses ids below 1. A 0-based id here would misalign every
    # criterion with its point value and silently produce wrong scores.
    row = _row("t", rubric=_rubric((2, _CONTENT), (1, "Second criterion."), (3, "Third.")))
    assert [item["rubric_id"] for item in rubric_items(row, 1)] == [1, 2, 3]
