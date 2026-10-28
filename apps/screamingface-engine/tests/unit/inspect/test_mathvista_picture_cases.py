# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""MathVista's Case is what inspect_evals' own solver hands the model, picture included.

FEATURE: OME-1479 — MathVista (testmini) is a Task-replay Benchmark whose questions each carry
one picture. Its solver branches only on the Sample's ``question_type``: a multiple-choice
question is wrapped in inspect's single-answer template over the lettered choices; a
free-form one is wrapped in the eval's fixed "ANSWER: $ANSWER" template around the dataset's
own ``query`` text, which already carries the precision and unit hint. Both rewrite the
user message's text, and inspect's text setter puts the rewritten text AFTER the picture, so
the model is shown the picture first. Capture runs the real solver, so the Case must hold
exactly that; and the scorer reads ``question_type`` again at grading time, so the Grading
Material must keep the Sample's metadata.

Stand-in: ``datasets.load_dataset`` returns the rows below; the real mathvista task,
inspect_evals' real picture save (thumbnail, then the picture's own format) and the real
capture run.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from PIL import Image  # noqa: E402
from replayed_cases_helpers import replay_in_process_over_rows  # noqa: E402

from screamingface_engine_inspect.prepare import PreparedCase  # noqa: E402

#: inspect's single-answer multiple-choice template for three options, as inspect 0.3.263
#: renders it.
_MCQ_INSTRUCTION: str = (
    "Answer the following multiple choice question. The entire content of your response "
    "should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is "
    "one of A,B,C."
)

#: The eval's own free-form instruction line (inspect_evals' FREEFORM_TEMPLATE).
_FREEFORM_INSTRUCTION: str = (
    "Answer the following question. The entire content of your response should be of the "
    "following format: 'ANSWER: $ANSWER' (without quotes) where $ANSWER is your answer."
)


def _encoded(colour: str, picture_format: str) -> bytes:
    """A tiny stand-in picture as the Hub row holds it; the colour only makes bytes differ."""

    buffer: io.BytesIO = io.BytesIO()
    Image.new("RGB", (2, 2), colour).save(buffer, format=picture_format)
    return buffer.getvalue()


def _as_saved(encoded: bytes) -> bytes:
    """The bytes inspect_evals' record_to_sample writes for a picture already under 1024 px:
    opened, then saved again in its own format."""

    picture: Image.Image = Image.open(io.BytesIO(encoded))
    buffer: io.BytesIO = io.BytesIO()
    picture.save(buffer, format=picture.format)
    return buffer.getvalue()


def _row(pid: str, question_type: str, picture: bytes) -> dict[str, Any]:
    """One stand-in MathVista testmini row in the Hub's shape."""

    multiple_choice: bool = question_type == "multi_choice"
    return {
        "pid": pid,
        "question": f"Stand-in question {pid}?",
        "image": f"images/{pid}.jpg",
        "decoded_image": {"bytes": picture, "path": None},
        "choices": ["larger than", "equal to", "smaller than"] if multiple_choice else None,
        "unit": None,
        "precision": None if multiple_choice else 1.0,
        "answer": "equal to" if multiple_choice else "1.5",
        "question_type": question_type,
        "answer_type": "text" if multiple_choice else "float",
        "metadata": {
            "category": "math-targeted-vqa",
            "context": "function plot",
            "grade": "college",
            "img_height": 2,
            "img_width": 2,
            "language": "english",
            "skills": ["algebraic reasoning"],
            "source": "FunctionQA",
            "split": "testmini",
            "task": "textbook question answering",
        },
        "query": f"Hint: answer with one decimal place.\nQuestion: Stand-in query {pid}?",
    }


def _replay(rows: list[dict[str, Any]], tmp_path: Path) -> list[PreparedCase]:
    """Replay the real mathvista task over ``rows``.

    WHY patch the picture folder and set INSPECT_EVALS_CACHE_DIR: inspect_evals writes each
    picture under its cache once and reuses it after, so a shared cache could serve a stale
    picture; capture accepts a picture file only under the import's own cache, which it reads
    from INSPECT_EVALS_CACHE_DIR, as the import child sets it.
    """

    evals_cache: Path = tmp_path / "cache" / "inspect_evals"
    with (
        mock.patch("inspect_evals.mathvista.mathvista.INSPECT_EVALS_CACHE_PATH", evals_cache),
        mock.patch.dict("os.environ", {"INSPECT_EVALS_CACHE_DIR": str(evals_cache)}),
    ):
        return replay_in_process_over_rows("mathvista", rows, tmp_path)


def _parts(case: PreparedCase) -> list[dict[str, Any]]:
    """The one user message's content parts, as the Candidate is sent them."""

    envelope: dict[str, Any] = json.loads(case["case"]["input"])
    assert envelope["schema"] == "screamingface.candidate-input.v2"
    [message] = envelope["messages"]
    assert message["role"] == "user"
    return message["content"]


def _shown(part: dict[str, Any], media_type: str) -> bytes:
    """The picture bytes one image part carries, refusing any other media type."""

    prefix: str = f"data:{media_type};base64,"
    url: str = part["image_url"]["url"]
    assert url.startswith(prefix)
    return base64.b64decode(url.removeprefix(prefix))


def test_mathvista_case_shows_the_picture_then_the_text_its_solver_wrote(tmp_path: Path) -> None:
    """Each Case holds the picture first, then the text the solver wrote for its question type.

    WHY pin the exact text: the free-form template wraps the dataset's ``query`` (which
    carries the precision hint) and the multiple-choice one wraps the bare ``question`` with
    inspect's lettered choices; a solver that took the wrong branch would ask a different
    question, or lose the hint the scorer's exact match depends on.
    """

    png: bytes = _encoded("red", "PNG")
    jpeg: bytes = _encoded("blue", "JPEG")
    rows: list[dict[str, Any]] = [
        _row("1", "multi_choice", png),
        _row("2", "free_form", jpeg),
    ]

    prepared: list[PreparedCase] = _replay(rows, tmp_path)

    by_kind: dict[str, PreparedCase] = {
        case["grading_material"]["metadata"]["question_type"]: case for case in prepared
    }
    assert sorted(by_kind) == ["free_form", "multi_choice"]

    choice_parts: list[dict[str, Any]] = _parts(by_kind["multi_choice"])
    assert [part["type"] for part in choice_parts] == ["image_url", "text"]
    assert _shown(choice_parts[0], "image/png") == _as_saved(png)
    assert choice_parts[1]["text"] == (
        f"{_MCQ_INSTRUCTION}\n\n"
        "Stand-in question 1?\n\n"
        "A) larger than\nB) equal to\nC) smaller than"
    )

    free_parts: list[dict[str, Any]] = _parts(by_kind["free_form"])
    assert [part["type"] for part in free_parts] == ["image_url", "text"]
    assert _shown(free_parts[0], "image/jpeg") == _as_saved(jpeg)
    assert free_parts[1]["text"] == (
        f"\n{_FREEFORM_INSTRUCTION}\n\n"
        "Hint: answer with one decimal place.\nQuestion: Stand-in query 2?\n"
    )


def test_mathvista_grading_material_keeps_what_the_scorer_reads(tmp_path: Path) -> None:
    """The Grading Material keeps the Sample's metadata and the eval's own target.

    WHY: the eval's scorer picks its answer pattern by ``question_type`` at grading time (a
    letter for multiple choice, the last ``ANSWER:`` line for free-form) and raises on a
    missing key; and its target is the option's letter for multiple choice but the dataset's
    answer text for free-form.
    """

    rows: list[dict[str, Any]] = [
        _row("1", "multi_choice", _encoded("red", "PNG")),
        _row("2", "free_form", _encoded("blue", "PNG")),
    ]

    prepared: list[PreparedCase] = _replay(rows, tmp_path)

    by_kind: dict[str, dict[str, Any]] = {
        case["grading_material"]["metadata"]["question_type"]: case["grading_material"]
        for case in prepared
    }
    assert by_kind["multi_choice"]["target"] == "B"
    assert by_kind["multi_choice"]["choices"] == ["larger than", "equal to", "smaller than"]
    assert by_kind["multi_choice"]["metadata"]["source"] == "FunctionQA"
    assert by_kind["free_form"]["target"] == "1.5"
    assert by_kind["free_form"]["metadata"]["precision"] == 1.0
    assert "choices" not in by_kind["free_form"]
