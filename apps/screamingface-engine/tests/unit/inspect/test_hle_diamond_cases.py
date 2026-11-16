# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""HLE-Diamond's Case: the Candidate and the judge read what inspect_evals' hle hands them.

FEATURE: OME-1863. ``hle_diamond`` is HLE-Diamond's 1,000 questions through inspect_evals' hle
prompt and judge. Two people read each Case, and each must read what inspect_evals' hle would
hand them for the same Diamond row:

1. The Candidate: the eval's system prompt, the question, and a picture question's exact bytes.
2. The judge: ``regex_judge`` quotes the Sample's own question, so our judge's whole prompt is
   byte-equal to the one inspect's own ``eval()`` sends for the same row and reply.

The Case also keeps the row's ``partition`` as private Grading Material, and the row is judged
exactly as ``hle`` is (same scorer, arguments and judge), so the two Benchmarks differ only in
their questions.

Stand-in: ``datasets.load_dataset`` returns the two rows below (one text, one picture); the
real hle_diamond Task, the real capture and our real scorer adapter run. The helpers that
grade and record the judge's prompt are ``test_hle_cases.py``'s, imported, not copied.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from replayed_cases_helpers import replay_in_process_over_rows  # noqa: E402
from test_hle_cases import (  # noqa: E402
    _inspects_judge_prompt,
    _our_judge_prompt,
    _png,
    _system_prompt,
)

from screamingface_engine_inspect.benchmarks import BENCHMARKS  # noqa: E402
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES, PreparedCase  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import SAMPLE_INPUT_KEY  # noqa: E402

#: The stand-in questions, as the Hub rows write them (not real Diamond questions).
TEXT_QUESTION: str = "Stand-in question: what is 6 times 7?"
PICTURE_QUESTION: str = "Stand-in question: how many red squares does the picture show?"


def _row(uid: str, question: str, image: str, partition: str) -> dict[str, Any]:
    """One stand-in cais/hle-diamond row: cais/hle's columns plus ``partition``."""

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
        "partition": partition,
    }


def _rows() -> list[dict[str, Any]]:
    """One text reasoning question and one picture knowledge question, as the Hub serves them."""

    picture: str = "data:image/png;base64," + base64.b64encode(_png()).decode("ascii")
    return [
        _row("stand-in-text", TEXT_QUESTION, "", "reasoning"),
        _row("stand-in-picture", PICTURE_QUESTION, picture, "knowledge"),
    ]


def _row_spec(key: str) -> Any:
    """The catalogue row for ``key``."""

    [row] = [spec for spec in BENCHMARKS if spec.key == key]
    return row


def test_the_candidate_sees_the_system_prompt_the_question_and_the_picture_bytes(
    tmp_path: Path,
) -> None:
    """The text Case is the eval's system prompt then the question; the picture Case holds the
    same two texts and then the picture's exact bytes. WHY pin the bytes: a Case carrying
    another picture would ask about the wrong image, and every text check would still pass."""

    prepared: list[PreparedCase] = replay_in_process_over_rows("hle_diamond", _rows(), tmp_path)

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


def test_the_partition_is_kept_as_grading_material_never_shown_to_the_candidate(
    tmp_path: Path,
) -> None:
    """``partition`` rides in the private Grading Material beside the answer key, so per-half
    scores can come later without changing the Cases; the Candidate's input never names it."""

    prepared: list[PreparedCase] = replay_in_process_over_rows("hle_diamond", _rows(), tmp_path)

    assert [case["grading_material"]["target"] for case in prepared] == ["42", "42"]
    assert [case["grading_material"]["metadata"]["partition"] for case in prepared] == [
        "reasoning",
        "knowledge",
    ]
    assert all("reasoning" not in case["case"]["input"] for case in prepared)
    assert all("knowledge" not in case["case"]["input"] for case in prepared)


def test_the_judge_reads_the_question_byte_for_byte_as_inspect_s_judge_does(
    tmp_path: Path,
) -> None:
    """On the picture question: the kept question is the Sample's own text, without the system
    prompt or the picture, and our judge's whole prompt is byte-equal to the one inspect's own
    ``eval()`` sends its judge for the same Diamond row and reply."""

    picture_case: PreparedCase = replay_in_process_over_rows("hle_diamond", _rows(), tmp_path)[1]

    ours: str = _our_judge_prompt(picture_case)

    assert picture_case["grading_material"][SAMPLE_INPUT_KEY] == PICTURE_QUESTION
    assert ours == _inspects_judge_prompt(tmp_path, _rows()[1])
    assert "base64" not in ours


def test_hle_diamond_is_judged_exactly_as_hle_is() -> None:
    """Same scorer, scorer arguments, named scores, judge and failure policy as the ``hle`` row,
    and the same primary-judge spec into the Task. WHY: the ticket's promise is that the two
    Benchmarks differ only in their questions, so a judge change on one must be made on both."""

    diamond: Any = _row_spec("hle_diamond")
    hle: Any = _row_spec("hle")

    assert diamond.scorer == hle.scorer == "inspect_evals.hle.scorers:regex_judge"
    assert diamond.scorer_kwargs == hle.scorer_kwargs
    assert diamond.named_scores == hle.named_scores == ("score", "confidence")
    assert diamond.judge == hle.judge
    assert diamond.failure_policy == hle.failure_policy == "withhold"
    declaration: Any = TASK_REPLAY_CASES["hle_diamond"]
    assert declaration.task_args == TASK_REPLAY_CASES["hle"].task_args
    assert declaration.keep_sample_input is True
    assert declaration.keep_sample_metadata is True
    assert declaration.case_count == 1000
    assert declaration.source_pins == {
        "cais/hle-diamond": "04eeb7efa7e3e4f83a00cbd5ce436a38fd5dda23"
    }
