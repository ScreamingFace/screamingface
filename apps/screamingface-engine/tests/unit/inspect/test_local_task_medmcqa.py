# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai and huggingface_hub, absent in the
# extra-less typecheck install.
"""MedMCQA as a LOCAL inspect Task — our own eval in inspect's shape (OME-1696).

What these tests pin, and why:

- a dataset row becomes the question, its four options in dataset order, and the letter of the
  correct one (`cop` 0..3 → A..D), so the key always names one of the options shown;
- a row with no real key (`cop` -1, as on the withheld test split) is refused, not served as a
  question nobody can get right;
- the downloaded file is refused when its sha256 is not the pinned one, so a changed upload on
  the Hub cannot change the Cases under the same revision;
- the question is shown under inspect's standard multiple-choice instruction, options A) to D);
- real MedMCQA questions grade right and wrong through the production aggregate route with the
  network blocked;
- the row: 4,183 Cases, no judge, no check surface.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

import huggingface_hub  # noqa: E402
from inspect_ai.model import ChatMessageUser, ModelOutput  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from test_inspect_task_replay_benchmarks import _node, _scores  # noqa: E402

from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from screamingface_engine_inspect.local_tasks.medmcqa.medmcqa import (  # noqa: E402
    DATASET_SHA256,
    load_medmcqa_validation,
    medmcqa,
    record_to_sample,
)
from screamingface_engine_inspect.prepare import PreparedCase  # noqa: E402

#: Four real validation rows, one per answer letter (ids are the dataset's own).
_ROWS: list[dict[str, Any]] = [
    {
        "id": "17360c6c-2c98-4fe2-aa85-487dcf4678df",
        "question": "Concentration of tropicamide:",
        "opa": "0.01",
        "opb": "0.02",
        "opc": "0.03",
        "opd": "0.04",
        "cop": 0,
        "subject_name": "Ophthalmology",
    },
    {
        "id": "efa0e92a-b11b-4c1c-a97d-8b4409430caa",
        "question": "The resolution of IOPA is about:",
        "opa": "10 Lp/mm",
        "opb": "16 Lp/mm",
        "opc": "28 Lp/mm",
        "opd": "30 Lp/mm",
        "cop": 1,
        "subject_name": "Dental",
    },
    {
        "id": "d4e13d7b-8ca9-447e-b93d-e8b86afd017a",
        "question": "Classify the class of recession:",
        "opa": "Class 1",
        "opb": "Class 2",
        "opc": "Class 3",
        "opd": "Class 4",
        "cop": 2,
        "subject_name": "Dental",
    },
    {
        "id": "3ea8bac5-2e0f-4f6f-8f5e-c9c1ef405a76",
        "question": "Ammonia from brain is removed as:",
        "opa": "Urea",
        "opb": "Alanine",
        "opc": "Glutamate",
        "opd": "Glutamine",
        "cop": 3,
        "subject_name": "Biochemistry",
    },
]


def test_a_row_becomes_its_question_options_and_key_letter() -> None:
    """cop indexes the options in dataset order, so cop 3 is D, the fourth option shown."""

    sample = record_to_sample(_ROWS[3])

    assert sample.id == "3ea8bac5-2e0f-4f6f-8f5e-c9c1ef405a76"
    assert sample.input == "Ammonia from brain is removed as:"
    assert sample.choices == [
        "Urea",
        "Alanine",
        "Glutamate",
        "Glutamine",
    ]
    assert sample.target == "D"
    assert [record_to_sample(row).target for row in _ROWS] == ["A", "B", "C", "D"]


@pytest.mark.parametrize("cop", [-1, 4, None])
def test_a_row_without_a_real_key_is_refused(cop: object) -> None:
    """The test split's withheld key is -1; served, it would mark every reply wrong."""

    with pytest.raises(ValueError, match="not an option index"):
        record_to_sample({**_ROWS[0], "cop": cop})


def test_a_file_whose_sha256_is_not_the_pin_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Hub commit pins the file's name; the sha256 pins its bytes."""

    tampered: Path = tmp_path / "validation.parquet"
    tampered.write_bytes(b"not the pinned file")
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda **_kwargs: str(tampered))

    with pytest.raises(ValueError, match=f"expected {DATASET_SHA256}"):
        load_medmcqa_validation()


def test_the_question_is_shown_under_inspects_standard_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Options A) to D) in dataset order, under the letter-only instruction every
    multiple-choice Benchmark here uses (owner decision, OME-1696)."""

    sample = record_to_sample(_ROWS[3])
    monkeypatch.setattr(
        "screamingface_engine_inspect.local_tasks.medmcqa.medmcqa.load_medmcqa_validation",
        lambda: [sample],
    )
    task = medmcqa()
    state = TaskState(
        model="none/none",  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=1,
        epoch=1,
        input=str(sample.input),
        messages=[ChatMessageUser(content=str(sample.input))],
        choices=list(sample.choices or []),
    )
    sent: list[str] = []

    async def record(state: TaskState, *_args: Any, **_kwargs: Any) -> TaskState:
        sent.append(str(state.messages[-1].content))
        state.output = ModelOutput.from_content(model="none/none", content="ANSWER: D")
        return state

    asyncio.run(task.solver(state, record))

    assert sent[0] == (
        "Answer the following multiple choice question. The entire content of your response "
        "should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER "
        "is one of A,B,C,D.\n\n"
        "Ammonia from brain is removed as:\n\n"
        "A) Urea\nB) Alanine\nC) Glutamate\nD) Glutamine"
    )


def _case(index: int, row: dict[str, Any]) -> PreparedCase:
    """A real row as Case Preparation writes it (input as rendered, the key and options)."""

    sample = record_to_sample(row)
    choices: list[str] = list(sample.choices or [])
    return {
        "case": {"id": index, "case_id": str(index), "input": str(sample.input)},
        "grading_material": {"target": str(sample.target), "choices": choices},
    }


@pytest.mark.asyncio
async def test_real_questions_grade_right_and_wrong_with_no_network(
    tmp_path: Path, no_network: None
) -> None:
    """Through the production aggregate route: the key letter scores 1, any other 0."""

    benchmark = imported_benchmark("medmcqa")
    node = _node(benchmark, [_case(index, row) for index, row in enumerate(_ROWS, 1)], tmp_path)

    right: list[str] = ["ANSWER: A", "ANSWER: B", "ANSWER: C", "Glutamine.\nANSWER: D"]
    wrong: list[str] = ["ANSWER: B", "ANSWER: C", "ANSWER: D", "ANSWER: A"]

    assert await _scores(node, benchmark, right) == [1.0] * 4
    assert await _scores(node, benchmark, wrong) == [0.0] * 4


def test_the_row_serves_4183_cases_with_no_judge() -> None:
    benchmark = imported_benchmark("medmcqa")

    assert benchmark.benchmark.case_count == 4183
    assert benchmark.judge is None
    # Elimination attack over four options: multiple-choice rows never carry the offer.
    assert benchmark.benchmark.check_surface is None
