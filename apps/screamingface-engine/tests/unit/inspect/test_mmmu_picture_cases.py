# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""MMMU's Case is what inspect_evals' own solver chain hands the model, pictures included.

FEATURE: OME-1477 — MMMU (multiple choice) is a Task-replay Benchmark whose questions carry
pictures. Its solver chain is ``prompt_template`` then ``multiple_choice``: the template adds
"Answer with the option's letter…" above the question, then ``multiple_choice`` wraps that in
inspect's own lettered-options template. Both rewrite the user message's text, and inspect's
text setter puts the rewritten text AFTER the message's pictures, so the model is shown the
pictures first. Capture runs the real chain, so the Case must hold exactly that.

Stand-in: ``datasets.load_dataset`` returns the rows below for one subject; the real mmmu
task, inspect_evals' real ``save_image`` (thumbnail, then PNG) and the real capture run.
WHY one subject: the task loads each of its 30 subjects separately, and the stand-in would
serve the same rows 30 times.
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

#: inspect's multiple-choice template for four options, as inspect 0.3.263 renders it.
_MCQ_INSTRUCTION: str = (
    "Answer the following multiple choice question. The entire content of your response "
    "should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is "
    "one of A,B,C,D."
)


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
        "question": f"<image 1> Stand-in question {number}?",
        "options": "['North', 'South', 'East', 'West']" if question_type != "open" else "[]",
        "answer": "B" if question_type != "open" else "North",
        "question_type": question_type,
        "subfield": "Stand-in subfield",
        "explanation": "",
        "img_type": "['Maps']",
        "topic_difficulty": "Easy",
    }
    for slot in range(1, 8):
        row[f"image_{slot}"] = pictures[slot - 1] if slot <= len(pictures) else None
    return row


def _replay(rows: list[dict[str, Any]], tmp_path: Path) -> list[PreparedCase]:
    """Replay the real mmmu_multiple_choice task over ``rows`` for one subject.

    WHY patch the image folder and set INSPECT_EVALS_CACHE_DIR: inspect_evals writes each
    picture under its cache once and reuses it after, so a shared cache could serve a stale
    picture; capture accepts a picture file only under the import's own cache, which it reads
    from INSPECT_EVALS_CACHE_DIR, as the import child sets it.
    """

    evals_cache: Path = tmp_path / "cache" / "inspect_evals"
    with (
        mock.patch("inspect_evals.mmmu.mmmu.subjects_list", ["Geography"]),
        mock.patch("inspect_evals.mmmu.utils.INSPECT_EVALS_CACHE_PATH", evals_cache),
        mock.patch.dict("os.environ", {"INSPECT_EVALS_CACHE_DIR": str(evals_cache)}),
    ):
        return replay_in_process_over_rows("mmmu_multiple_choice", rows, tmp_path)


def test_mmmu_case_shows_the_pictures_then_the_text_both_solvers_wrote(tmp_path: Path) -> None:
    """The Case holds the pictures first, in slot order, as inspect sends them, then the text
    both solvers wrote; the open question is left out, as the eval's own filter does.

    WHY pin the exact text: the template's line and inspect's lettered options are both part
    of what the Candidate is asked, and a chain that ran only one solver would drop one."""

    north: Image.Image = _picture("red")
    south: Image.Image = _picture("blue")
    rows: list[dict[str, Any]] = [
        _row(1, "multiple-choice", [north, south]),
        _row(2, "open", [north]),
    ]

    prepared: list[PreparedCase] = _replay(rows, tmp_path)

    assert len(prepared) == 1
    envelope: dict[str, Any] = json.loads(prepared[0]["case"]["input"])
    assert envelope["schema"] == "screamingface.candidate-input.v2"
    [message] = envelope["messages"]
    assert message["role"] == "user"
    parts: list[dict[str, Any]] = message["content"]
    assert [part["type"] for part in parts] == ["image_url", "image_url", "text"]
    shown: list[bytes] = [
        base64.b64decode(part["image_url"]["url"].removeprefix("data:image/png;base64,"))
        for part in parts[:2]
    ]
    assert shown == [_png(north), _png(south)]
    assert parts[2]["text"] == (
        f"{_MCQ_INSTRUCTION}\n\n"
        "Answer with the option's letter from the given choices directly.\n"
        "<image 1> Stand-in question 1?\n\n"
        "A) North\nB) South\nC) East\nD) West"
    )
    assert prepared[0]["grading_material"]["target"] == "B"
