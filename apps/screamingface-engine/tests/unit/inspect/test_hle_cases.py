# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""HLE's Case: the Candidate sees the picture, the judge reads the question as inspect's does.

FEATURE: OME-1478 PR 2 of 2. ``hle`` is Humanity's Last Exam's 2,500 questions, about 14% with
one picture, graded by inspect_evals' maintained ``regex_judge`` in the ``grader`` role (the
owner's pick, 2026-11-02). Two people read each Case, and each must read what inspect_evals
hands them:

1. The Candidate. The eval's system prompt asks for an explanation, an answer and a confidence;
   the question follows, and a picture question carries its picture's exact bytes.
2. The judge. ``regex_judge`` quotes ``state.input_text``, the Sample's own question, never the
   system prompt or the picture. Case Preparation keeps that question in the Grading Material,
   so our judge's prompt is inspect's, byte for byte.

Stand-in: ``datasets.load_dataset`` returns the two rows below (one text, one with a picture);
the real hle task, the real capture and our real scorer adapter run. Both judges are inspect's
mock model, which notes every prompt it is sent; it is bound to the ``grader`` role in both arms.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai import Task  # noqa: E402
from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.dataset import MemoryDataset  # noqa: E402
from inspect_ai.model import ChatMessage, Model, ModelOutput, get_model, model_roles  # noqa: E402
from inspect_ai.model._model import init_model_roles  # noqa: E402
from inspect_ai.solver import generate  # noqa: E402
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

#: The stand-in questions, as the Hub rows write them.
TEXT_QUESTION: str = "Stand-in question: what is 6 times 7?"
PICTURE_QUESTION: str = "Stand-in question: how many red squares does the picture show?"

#: inspect's mock Candidate answers with this text by default; both arms grade the same reply.
CANDIDATE_REPLY: str = "Default output from mockllm/model"

#: default.yaml's scorer arguments, as the HLE row's kwargs carry them.
_JUDGE_ARGUMENTS: dict[str, Any] = {
    "template": "regex_judge_template",
    "instructions": "regex_judge_instructions",
    "grader_role": "grader",
    "max_grader_attempts": 3,
}


def _png() -> bytes:
    """A tiny stand-in picture's PNG bytes."""

    buffer: io.BytesIO = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def _row(uid: str, question: str, image: str) -> dict[str, Any]:
    """One stand-in cais/hle row in the Hub's shape; ``image`` is a data URI or empty."""

    return {
        "id": uid,
        "question": question,
        "image": image,
        "image_preview": None,
        "answer": "42",
        "answer_type": "exactMatch",
        "author_name": "Stand-in author",
        "rationale": "",
        "rationale_image": None,
        "raw_subject": "Mathematics",
        "category": "Math",
        "canary": "",
    }


def _rows() -> list[dict[str, Any]]:
    """One text question and one picture question, as the Hub serves them."""

    picture: str = "data:image/png;base64," + base64.b64encode(_png()).decode("ascii")
    return [
        _row("stand-in-text", TEXT_QUESTION, ""),
        _row("stand-in-picture", PICTURE_QUESTION, picture),
    ]


def _system_prompt() -> str:
    """The eval's own system prompt for every question (``system_mc``, the CAIS one)."""

    from inspect_evals.hle.prompts import SYSTEM_MESSAGES

    return SYSTEM_MESSAGES["system_mc"]


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


@contextmanager
def _grader_role(judge: Model) -> Iterator[None]:
    """Bind inspect's ``grader`` role to ``judge`` for one grading, as a run binds our judge."""

    previous: dict[str, Any] = dict(model_roles())
    init_model_roles({**previous, "grader": judge})
    try:
        yield
    finally:
        init_model_roles(previous)


def _our_judge_prompt(record: PreparedCase) -> str:
    """Grade one prepared Case through the real adapter path and return the judge's prompt."""

    from inspect_evals.hle.scorers import regex_judge

    prompts: list[str] = []
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

        with _grader_role(_recording_judge(prompts)):
            grade = inspect_grade_case(
                regex_judge(**_JUDGE_ARGUMENTS), named_scores=("score", "confidence")
            )
            return await grade(request)

    outcome: Any = asyncio.run(graded())
    assert outcome.failure_code is None, outcome
    assert len(prompts) == 1, prompts
    return prompts[0]


def _inspects_judge_prompt(tmp_path: Path, row: dict[str, Any]) -> str:
    """Run inspect_evals' own Sample and scorer under inspect's own ``eval()``, with the
    recorder in the ``grader`` role, and return the prompt inspect's judge was sent: the
    outside reference, not our code."""

    from inspect_evals.hle.dataset import record_to_sample
    from inspect_evals.hle.scorers import regex_judge

    prompts: list[str] = []
    task: Task = Task(
        dataset=MemoryDataset([record_to_sample(row)]),
        solver=generate(),
        scorer=regex_judge(**_JUDGE_ARGUMENTS),
    )
    logs: list[Any] = inspect_eval(
        task,
        model="mockllm/model",
        model_roles={"grader": _recording_judge(prompts)},
        log_dir=str(tmp_path / "logs"),
        display="none",
    )
    assert [log.status for log in logs] == ["success"]
    assert len(prompts) == 1, prompts
    return prompts[0]


def test_the_candidate_sees_the_system_prompt_the_question_and_the_picture_bytes(
    tmp_path: Path,
) -> None:
    """The text Case is the eval's system prompt then the question; the picture Case holds the
    same two texts and then the picture's exact bytes. WHY pin the bytes: a Case carrying
    another picture would ask about the wrong image, and every text check would still pass."""

    prepared: list[PreparedCase] = replay_in_process_over_rows("hle", _rows(), tmp_path)

    assert len(prepared) == 2
    text_case, picture_case = prepared
    assert text_case["case"]["input"] == f"{_system_prompt()}\n\n{TEXT_QUESTION}"
    [message] = json.loads(picture_case["case"]["input"])["messages"]
    parts: list[dict[str, Any]] = message["content"]
    assert [part["type"] for part in parts] == ["text", "text", "image_url"]
    assert [part["text"] for part in parts[:2]] == [_system_prompt(), PICTURE_QUESTION]
    shown: bytes = base64.b64decode(
        parts[2]["image_url"]["url"].removeprefix("data:image/png;base64,")
    )
    assert shown == _png()
    assert [case["grading_material"]["target"] for case in prepared] == ["42", "42"]


def test_the_judge_reads_the_question_byte_for_byte_as_inspect_s_judge_does(
    tmp_path: Path,
) -> None:
    """On the picture question: the kept question is the Sample's own text, without the system
    prompt or the picture, and our judge's whole prompt is byte-equal to the one inspect's own
    ``eval()`` sends its judge for the same row and reply."""

    picture_case: PreparedCase = replay_in_process_over_rows("hle", _rows(), tmp_path)[1]

    ours: str = _our_judge_prompt(picture_case)

    assert picture_case["grading_material"][SAMPLE_INPUT_KEY] == PICTURE_QUESTION
    assert ours == _inspects_judge_prompt(tmp_path, _rows()[1])
    assert "base64" not in ours


def test_hle_is_declared_with_the_maintained_judge_in_the_grader_role() -> None:
    """The row grades with inspect_evals' regex_judge through the pinned glm-5.3-flash judge,
    with default.yaml's judge settings, and keeps the question for that judge."""

    [row] = [spec for spec in BENCHMARKS if spec.key == "hle"]

    assert row.scorer == "inspect_evals.hle.scorers:regex_judge"
    assert row.scorer_kwargs == _JUDGE_ARGUMENTS
    assert row.named_scores == ("score", "confidence")
    assert row.judge is not None
    assert row.judge.model == "openrouter/z-ai/glm-5.3-flash"
    assert row.judge.model_role == "grader"
    assert dict(row.judge.params) == {
        "temperature": "0",
        "max_tokens": "32768",
        "web_search": "false",
    }
    declaration: Any = TASK_REPLAY_CASES["hle"]
    assert declaration.keep_sample_input is True
    assert declaration.task_args["scorer"]["graders"] == ["grader"]
