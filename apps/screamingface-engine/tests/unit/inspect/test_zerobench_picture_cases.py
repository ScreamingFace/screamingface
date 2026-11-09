# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""ZeroBench's Case is what inspect_evals' own loader hands the model, pictures included.

FEATURE: OME-1855 — ZeroBench's 100 main questions are a Task-replay Benchmark whose
questions each carry one or more pictures. The eval has no solver of its own: its
``record_to_sample`` builds the one user message itself, the question text with the eval's
instruction line ("Let's think step by step and give the final answer in curly braces…")
first, then each picture, thumbnailed to 1024 px and re-saved in its own format. Capture runs
that loader for real, so the Case must hold exactly that, in that order. Grading is the eval's
own ``zerobench_scorer``: the LAST curly-braces group in the reply, lower-cased, must equal the
answer exactly; no braces means wrong.

Stand-in: ``datasets.load_dataset`` returns the rows below; the real zerobench task at its own
defaults (epochs=5, so the row declares 5 Attempts folded by the mean), inspect_evals' real
picture save and the real capture run. The grading tests run the Benchmark's real per-Case hook
over a stand-in Case, so no real answer appears here: the dataset is gated behind the authors'
no-public-answers terms.
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

from inspect_ai.dataset import Sample  # noqa: E402
from PIL import Image  # noqa: E402
from replayed_cases_helpers import replay_in_process_over_rows  # noqa: E402

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect import benchmarks  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    PreparedCase,
    prepared_case,
)

#: The eval's own instruction line (inspect_evals' INSTRUCTION_PROMPT), appended to every
#: question. WHY pinned as a literal: a changed line changes what every Candidate is asked.
_INSTRUCTION: str = (
    "\n\n\nLet's think step by step and give the final answer in curly braces, like this: "
    "{final answer}"
)


def _encoded(colour: str, picture_format: str) -> bytes:
    """A tiny stand-in picture as the Hub row holds it; the colour only makes bytes differ."""

    buffer: io.BytesIO = io.BytesIO()
    Image.new("RGB", (2, 2), colour).save(buffer, format=picture_format)
    return buffer.getvalue()


def _as_saved(encoded: bytes) -> bytes:
    """The bytes inspect_evals' record_to_message writes for a picture already under 1024 px:
    opened, thumbnailed (a no-op at this size), then saved again in its own format."""

    picture: Image.Image = Image.open(io.BytesIO(encoded))
    picture.thumbnail((1024, 1024))
    buffer: io.BytesIO = io.BytesIO()
    picture.save(buffer, format=picture.format)
    return buffer.getvalue()


def _row(question_id: str, pictures: list[tuple[str, bytes]]) -> dict[str, Any]:
    """One stand-in ZeroBench row in the Hub's shape: the decoded pictures beside their file
    names, in the same order."""

    return {
        "question_id": question_id,
        "question_text": f"Stand-in question {question_id}?",
        "question_images_decoded": [{"bytes": data, "path": None} for _, data in pictures],
        "question_answer": "stand-in answer",
        "question_images": [name for name, _ in pictures],
        "image_attribution": "stand-in attribution",
    }


def _replay(rows: list[dict[str, Any]], tmp_path: Path) -> list[PreparedCase]:
    """Replay the real zerobench task over ``rows``.

    WHY patch the picture folder and set INSPECT_EVALS_CACHE_DIR: inspect_evals writes each
    picture under its cache once and reuses it after, so a shared cache could serve a stale
    picture; capture accepts a picture file only under the import's own cache, which it reads
    from INSPECT_EVALS_CACHE_DIR, as the import child sets it.
    """

    evals_cache: Path = tmp_path / "cache" / "inspect_evals"
    with (
        mock.patch("inspect_evals.zerobench.zerobench.INSPECT_EVALS_CACHE_PATH", evals_cache),
        mock.patch.dict("os.environ", {"INSPECT_EVALS_CACHE_DIR": str(evals_cache)}),
    ):
        return replay_in_process_over_rows("zerobench", rows, tmp_path)


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


def test_zerobench_case_shows_the_question_with_the_instruction_then_every_picture_in_order(
    tmp_path: Path,
) -> None:
    """Each Case holds the question text with the eval's instruction line first, then every
    picture in the dataset's order, each re-saved in its own format.

    WHY pin the exact text and the order: the eval builds the message itself (no solver), so
    a capture that dropped the instruction line would ask for an answer the scorer cannot read
    (no braces, always wrong), and one that reordered the pictures would ask about a different
    picture than the question's "first" or "second" refers to.
    """

    red_png: bytes = _encoded("red", "PNG")
    blue_jpeg: bytes = _encoded("blue", "JPEG")
    green_png: bytes = _encoded("green", "PNG")
    rows: list[dict[str, Any]] = [
        _row("1", [("stand_in_1_a.png", red_png), ("stand_in_1_b.jpg", blue_jpeg)]),
        _row("2", [("stand_in_2.png", green_png)]),
    ]

    prepared: list[PreparedCase] = _replay(rows, tmp_path)

    by_question: dict[str, PreparedCase] = {
        _parts(case)[0]["text"].split("?")[0]: case for case in prepared
    }
    assert sorted(by_question) == ["Stand-in question 1", "Stand-in question 2"]

    two_pictures: list[dict[str, Any]] = _parts(by_question["Stand-in question 1"])
    assert [part["type"] for part in two_pictures] == ["text", "image_url", "image_url"]
    assert two_pictures[0]["text"] == f"Stand-in question 1?{_INSTRUCTION}"
    assert _shown(two_pictures[1], "image/png") == _as_saved(red_png)
    assert _shown(two_pictures[2], "image/jpeg") == _as_saved(blue_jpeg)

    one_picture: list[dict[str, Any]] = _parts(by_question["Stand-in question 2"])
    assert [part["type"] for part in one_picture] == ["text", "image_url"]
    assert one_picture[0]["text"] == f"Stand-in question 2?{_INSTRUCTION}"
    assert _shown(one_picture[1], "image/png") == _as_saved(green_png)


def test_zerobench_grading_material_keeps_the_target_and_the_samples_metadata(
    tmp_path: Path,
) -> None:
    """The Grading Material carries the eval's own target and the Sample's metadata.

    WHY: the eval's scorer is its own, so the importer keeps all Sample metadata (the picture
    file names and the pictures' attribution), sealed inside the Case Digest; the target is the
    dataset's answer text, which the scorer compares exactly.
    """

    rows: list[dict[str, Any]] = [_row("1", [("stand_in_1.png", _encoded("red", "PNG"))])]

    [prepared] = _replay(rows, tmp_path)

    material: dict[str, Any] = prepared["grading_material"]
    assert material["target"] == "stand-in answer"
    assert material["metadata"] == {
        "question_images": ["stand_in_1.png"],
        "image_attribution": "stand-in attribution",
    }


async def _grade(reply: str, answer: str) -> CaseGradeOutcome:
    """Grade one reply on zerobench's real per-Case hook, over a stand-in Case."""

    sample = Sample(id="q1", input="Stand-in question?", target=answer)
    case: PreparedCase = prepared_case(sample, 1, str(sample.input), TASK_REPLAY_CASES["zerobench"])
    material: Any = json.loads(json.dumps(case["grading_material"]))
    hook = imported_benchmark("zerobench").aggregation().grade_case
    return await hook(
        GradeRequest(
            case_id=1,
            input=TextPayload(text=str(sample.input)),
            answer=TextPayload(text=reply),
            row={"case": {"status": "answered"}},
            material=material,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "score"),
    [
        # The last braces group is the answer; an earlier guess in braces is ignored.
        ("First I count {7}, but on a second look the total is {8}.", 1.0),
        # The right answer in an earlier group loses to a wrong last one.
        ("I get {8}. Hmm, or rather {7}.", 0.0),
        # Case is ignored on both sides.
        ("The final answer is {Eight}.", 1.0),
        # No braces at all: the scorer cannot read an answer, so the reply is wrong.
        ("The final answer is 8.", 0.0),
        # Exact match only: a longer string that starts with the answer is wrong.
        ("{8 apples}", 0.0),
    ],
)
async def test_zerobench_grades_the_last_braces_group_by_exact_match(
    reply: str, score: float
) -> None:
    """INVARIANT: the Benchmark score is the eval's own rule, exact match on the last
    curly-braces group, not a containment or a judge; a reply that reasons in braces and
    corrects itself is graded on its final group."""

    outcome: CaseGradeOutcome = await _grade(reply, "eight" if "Eight" in reply else "8")

    assert (outcome.score, outcome.failure_code) == (score, None)


def test_zerobench_asks_each_case_five_times_and_folds_them_by_the_mean() -> None:
    """The row declares inspect_evals' own repetition: 5 Attempts per Case, folded by the
    mean (inspect's pass_at(1)), and the capture at the Task's defaults still yields one Case
    per question, not one per epoch.

    WHY: the published number is like-for-like with inspect_evals' pass@1 and the official
    board's five-sample column only under this exact declaration; a row that drifted back to
    one Attempt, or to the any-of-N fold, would publish a different number under the same
    name. The 100-Case count is the Cases row's; the epochs must not multiply it.
    """

    [spec] = [row for row in BENCHMARKS if row.key == "zerobench"]
    assert (spec.attempts, spec.epoch_reducer) == (5, "pass_at_1")
    assert TASK_REPLAY_CASES["zerobench"].task_args is None
    assert TASK_REPLAY_CASES["zerobench"].case_count == 100
    assert imported_benchmark("zerobench").benchmark.catalog_entry()["attempts"] == 5
    # The fold rule is Attempts identity, not a whole-run metric: this row honours no eval
    # metric, so the metric pins stay empty (test_whole_run_metric's invariant holds) and the
    # reducer rides the Attempts pins into the revision.
    assert benchmarks._whole_run_metric_pins(spec) == ()
    assert benchmarks._attempts_pins(spec) == ("attempts=5", "epoch_reducer=pass_at_1")
