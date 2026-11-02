# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""MMMU's open-answer Case: the Candidate sees the pictures, the judge reads the question.

FEATURE: OME-1477 PR 2 — ``mmmu_open`` is MMMU's 53 open-answer questions, graded by
inspect's ``model_graded_fact`` judge. Two people read each Case, and each must read what
inspect_evals hands them:

1. The Candidate. The eval's ``prompt_template`` puts "Answer the question using a single
   word or phrase." above the question, and inspect's text setter puts the rewritten text
   AFTER the message's pictures, so the Candidate is shown the pictures first, then that text.
2. The judge. inspect's judge quotes ``state.input_text``, which under ``eval()`` is the
   Sample's own question, without the template's line (OME-1755). Case Preparation keeps that
   question in the Grading Material, so our judge's prompt is inspect's, byte for byte.

Stand-in: ``datasets.load_dataset`` returns the rows below for one subject; the real mmmu
task, inspect_evals' real ``save_image`` (thumbnail, then PNG), the real capture and our real
scorer adapter run. Both judges are inspect's mock model, which notes every prompt it is sent.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

import datasets  # noqa: E402
from inspect_ai import Task  # noqa: E402
from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.model import ChatMessage, Model, ModelOutput, get_model  # noqa: E402
from inspect_ai.scorer import model_graded_fact  # noqa: E402
from PIL import Image  # noqa: E402
from replayed_cases_helpers import replay_in_process_over_rows  # noqa: E402

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS  # noqa: E402
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES, PreparedCase  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import (  # noqa: E402
    SAMPLE_INPUT_KEY,
    inspect_grade_case,
)

#: The stand-in open question, as the Hub row writes it: the picture's tag, then the ask.
QUESTION: str = "<image 1> <image 2> Stand-in question: how far apart are the two towns, in km?"

#: The eval's own open-answer line (inspect_evals ``OPEN_PROMPT``), which only the Candidate sees.
OPEN_INSTRUCTION: str = "Answer the question using a single word or phrase."

#: inspect's mock Candidate answers with this text by default; both arms grade the same reply.
CANDIDATE_REPLY: str = "Default output from mockllm/model"


def _picture(colour: str) -> Image.Image:
    """A tiny stand-in picture; the colour only makes the two pictures' bytes differ."""

    return Image.new("RGB", (2, 2), colour)


def _png(picture: Image.Image) -> bytes:
    """The bytes inspect_evals' save_image writes for a picture already under 1024 px."""

    buffer: io.BytesIO = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


def _row(number: int, question_type: str, pictures: list[Image.Image]) -> dict[str, Any]:
    """One stand-in MMMU row in the Hub's shape: seven picture slots, options as a string."""

    row: dict[str, Any] = {
        "id": f"validation_Geography_{number}",
        "question": QUESTION if question_type == "open" else f"<image 1> Question {number}?",
        "options": "[]" if question_type == "open" else "['North', 'South', 'East', 'West']",
        "answer": "120" if question_type == "open" else "B",
        "question_type": question_type,
        "subfield": "Stand-in subfield",
        "explanation": "",
        "img_type": "['Maps']",
        "topic_difficulty": "Easy",
    }
    for slot in range(1, 8):
        row[f"image_{slot}"] = pictures[slot - 1] if slot <= len(pictures) else None
    return row


def _rows() -> list[dict[str, Any]]:
    """One open question with two pictures in slot order, and one multiple-choice question
    the eval's own filter leaves out."""

    return [
        _row(1, "open", [_picture("red"), _picture("blue")]),
        _row(2, "multiple-choice", [_picture("green")]),
    ]


def _patched_mmmu(tmp_path: Path) -> tuple[Any, Any, Any]:
    """Point inspect_evals' picture folder at this test's own cache, for one subject.

    WHY: inspect_evals writes each picture under its cache once and reuses it after, so a
    shared cache could serve a stale picture; capture accepts a picture file only under the
    import's own cache, which it reads from INSPECT_EVALS_CACHE_DIR, as the import child sets
    it. WHY one subject: the task loads each of its 30 subjects separately, and the stand-in
    would serve the same rows 30 times.
    """

    evals_cache: Path = tmp_path / "cache" / "inspect_evals"
    return (
        mock.patch("inspect_evals.mmmu.mmmu.subjects_list", ["Geography"]),
        mock.patch("inspect_evals.mmmu.utils.INSPECT_EVALS_CACHE_PATH", evals_cache),
        mock.patch.dict("os.environ", {"INSPECT_EVALS_CACHE_DIR": str(evals_cache)}),
    )


def _replay(tmp_path: Path) -> list[PreparedCase]:
    """Replay the real mmmu_open task over the stand-in rows, as Case Preparation does."""

    subjects, cache_path, cache_env = _patched_mmmu(tmp_path)
    with subjects, cache_path, cache_env:
        return replay_in_process_over_rows("mmmu_open", _rows(), tmp_path)


def _recording_judge(prompts: list[str]) -> Model:
    """A stand-in judge: inspect's mock model, which also notes every prompt it is sent."""

    judge: Model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content(model="mockllm/model", content="GRADE: C")] * 4,
    )
    answer: Callable[..., Any] = judge.generate

    async def generate_and_record(
        input: str | list[ChatMessage], *args: Any, **kwargs: Any
    ) -> ModelOutput:
        """Note the judge prompt's text, then answer as the mock would."""

        messages: list[Any] = input if isinstance(input, list) else [input]
        prompts.append("\n".join(getattr(message, "text", str(message)) for message in messages))
        return await answer(input, *args, **kwargs)

    judge.generate = generate_and_record  # type: ignore[method-assign]
    return judge


def _our_judge_prompt(record: PreparedCase) -> str:
    """Grade one prepared Case through the real adapter path and return the judge's prompt."""

    prompts: list[str] = []
    grade = inspect_grade_case(model_graded_fact(model=_recording_judge(prompts)))
    request: GradeRequest = GradeRequest(
        case_id=record["case"]["id"],
        input=TextPayload(text=record["case"]["input"]),
        answer=TextPayload(text=CANDIDATE_REPLY),
        row={},
        material=record["grading_material"],
        finish_reason="stop",
    )

    async def graded() -> Any:
        """Await the adapter's grade inside the one event loop ``asyncio.run`` opens."""

        return await grade(request)

    outcome: Any = asyncio.run(graded())
    assert outcome.failure_code is None, outcome
    assert len(prompts) == 1, prompts
    return prompts[0]


def _inspects_judge_prompt(tmp_path: Path) -> str:
    """Run inspect_evals' own open-answer Task under inspect's own ``eval()`` over the same
    rows, mock Candidate and mock judge, and return the prompt inspect's judge was sent: the
    outside reference, not our code."""

    from inspect_evals.mmmu.mmmu import mmmu_task_open

    prompts: list[str] = []
    subjects, cache_path, cache_env = _patched_mmmu(tmp_path / "eval")
    with subjects, cache_path, cache_env:
        theirs: Task = mmmu_task_open(datasets.Dataset.from_list(_rows()))
        # WHY swap only the scorer's model: model_graded_fact() with no model grades with the
        # model under test; the recorder must stand in for the judge, and nothing else changes.
        task: Task = Task(
            dataset=theirs.dataset,
            solver=theirs.solver,
            scorer=model_graded_fact(model=_recording_judge(prompts)),
        )
        logs: list[Any] = inspect_eval(
            task, model="mockllm/model", log_dir=str(tmp_path / "logs"), display="none"
        )
    assert [log.status for log in logs] == ["success"]
    assert len(prompts) == 1, prompts
    return prompts[0]


def test_the_candidate_sees_the_pictures_in_slot_order_then_the_eval_s_open_line(
    tmp_path: Path,
) -> None:
    """The Case holds the two pictures first, in slot order, as inspect sends them, then the
    template's line above the question; the multiple-choice row is left out, as the eval's
    own filter does. WHY pin the bytes: a Case whose pictures swapped places would ask about
    the wrong map, and every text check would still pass."""

    red: Image.Image = _picture("red")
    blue: Image.Image = _picture("blue")

    prepared: list[PreparedCase] = _replay(tmp_path)

    assert len(prepared) == 1
    envelope: dict[str, Any] = json.loads(prepared[0]["case"]["input"])
    [message] = envelope["messages"]
    assert message["role"] == "user"
    parts: list[dict[str, Any]] = message["content"]
    assert [part["type"] for part in parts] == ["image_url", "image_url", "text"]
    shown: list[bytes] = [
        base64.b64decode(part["image_url"]["url"].removeprefix("data:image/png;base64,"))
        for part in parts[:2]
    ]
    assert shown == [_png(red), _png(blue)]
    assert parts[2]["text"] == f"{OPEN_INSTRUCTION}\n{QUESTION}"
    assert prepared[0]["grading_material"]["target"] == "120"


def test_the_judge_reads_the_sample_s_question_byte_for_byte_as_inspect_s_judge_does(
    tmp_path: Path,
) -> None:
    """The bug OME-1755 fixed, on MMMU's real chain: the kept question is the Sample's own,
    without the Candidate's open-answer line, and our judge's whole prompt is byte-equal to
    the one inspect's own ``eval()`` sends its judge for the same row and reply."""

    [record] = _replay(tmp_path)

    ours: str = _our_judge_prompt(record)

    assert record["grading_material"][SAMPLE_INPUT_KEY] == QUESTION
    assert ours == _inspects_judge_prompt(tmp_path)
    assert f"[Question]: {QUESTION}\n" in ours
    assert OPEN_INSTRUCTION not in ours


def test_mmmu_open_is_declared_as_a_judged_row_that_keeps_the_question() -> None:
    """The row grades with inspect's own model_graded_fact through the pinned judge, and its
    declaration keeps the question, or the image build would replay Cases without it."""

    [row] = [spec for spec in BENCHMARKS if spec.key == "mmmu_open"]

    assert row.scorer == "inspect_ai.scorer:model_graded_fact"
    assert row.judge is not None
    assert row.judge.model == "openrouter/openai/gpt-5.4"
    assert TASK_REPLAY_CASES["mmmu_open"].keep_sample_input is True
