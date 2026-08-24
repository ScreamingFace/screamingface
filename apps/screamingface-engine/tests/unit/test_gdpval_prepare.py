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


# --- reference resolution ---------------------------------------------------------------------


def test_reference_urls_maps_every_file_to_its_download_url() -> None:
    from screamingface_engine.benchmarks.gdpval.prepare import reference_urls

    rows = [
        {"reference_files": ["a/x.pdf", "b/y.docx"], "reference_file_urls": ["u1", "u2"]},
        {"reference_files": ["c/z.pdf"], "reference_file_urls": ["u3"]},
    ]
    assert reference_urls(rows) == {"a/x.pdf": "u1", "b/y.docx": "u2", "c/z.pdf": "u3"}


def test_reference_urls_tolerates_a_row_with_no_references() -> None:
    # WHY: 66 of the 102 selected tasks carry no reference files at all.
    from screamingface_engine.benchmarks.gdpval.prepare import reference_urls

    assert reference_urls([{"reference_files": None, "reference_file_urls": None}]) == {}


def test_an_unfetchable_reference_names_its_task_and_file(tmp_path) -> None:
    # INVARIANT: a reference with no URL fails the build identifiably. Silently skipping it would
    # bake a task whose prompt refers to material the model never received.
    from screamingface_engine.benchmarks.gdpval.ingestion import IngestionError
    from screamingface_engine.benchmarks.gdpval.prepare import _build_reader

    read = _build_reader(tmp_path, {})
    with pytest.raises(IngestionError) as excinfo:
        read("task-42", "missing/file.pdf")
    assert "task-42" in str(excinfo.value)
    assert "missing/file.pdf" in str(excinfo.value)


def test_a_reference_format_with_no_reader_fails_the_build(tmp_path) -> None:
    from screamingface_engine.benchmarks.gdpval.ingestion import IngestionError
    from screamingface_engine.benchmarks.gdpval.prepare import _build_reader

    read = _build_reader(tmp_path, {"sheet.xlsx": "u"})
    with pytest.raises(IngestionError, match="no reader"):
        read("task-42", "sheet.xlsx")


def test_a_cached_reference_is_not_downloaded_again(tmp_path) -> None:
    # WHY: the preparer fetches 85 files; a re-run after a mid-build failure must not re-download
    # everything. Presence plus non-zero size is the cache hit.
    from screamingface_engine.benchmarks.gdpval.prepare import _fetch

    cached = tmp_path / "ref.pdf"
    cached.write_bytes(b"already here")
    _fetch("task-42", "ref.pdf", {}, tmp_path)  # no URL available: only a cache hit can pass
    assert cached.read_bytes() == b"already here"


def test_prepare_returns_an_audit_summary(tmp_path, monkeypatch) -> None:
    # INVARIANT (OME-925): a preparer returns an operator-readable summary, not None. The
    # deployment orchestrator records it per bundle so a later bundle's refusal cannot erase
    # the evidence for the ones that already landed.
    from screamingface_engine.benchmarks.gdpval import prepare as module

    monkeypatch.setattr(module, "load_rows", _all_rows)
    monkeypatch.setattr(module, "_build_reader", lambda _cache, _urls: _reader)
    summary = module.prepare(tmp_path)

    assert summary["cases"] == len(TEXT_SUBSET_TASK_IDS)
    # WHY the exclusions belong in the record: dropping 7 tasks is a scoring-relevant choice.
    # A summary showing 102 cases without saying any were dropped would hide that decision.
    assert summary["excluded_tasks"] == 7
    assert summary["dataset_revision"]
