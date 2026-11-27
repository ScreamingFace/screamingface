# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai, datasets),
# absent in the default (extra-less) install the typecheck gate runs against; it is loaded only
# behind `inspect_available()`, like every other module in this package.
"""LABBench2's two picture subsets, FigQA2 image and TableQA2 image, as a LOCAL inspect Task.

Think of it as a lab practical: each question hands the Candidate one figure or one table from
a biology paper, as a picture, and asks for a number or a short answer read off it. An examiner
(the judge) compares the answer with the authors' ideal answer under the authors' own marking
sheet, and says correct, incorrect or unsure; only correct earns the mark.

Execution order, as the importer and the Engine see it:

    1. ``lab_bench_2_figqa2_img()`` / ``lab_bench_2_tableqa2_img()`` → :func:`load_rows`: the
       gated ``EdisonScientific/labbench2`` config at the pinned revision (the importer forces
       it at every build), in file order, 101 and 100 rows.
    2. per row, :func:`record_to_sample`: fetch the row's one picture from the authors' public
       bucket into the replay cache (:mod:`.figures`), and build the Candidate's message the
       authors' file mode builds: the question with its "Attached files" lines, then the
       picture. Case ``k`` is the ``k``-th row; the dataset's own id rides the metadata.
    3. the importer replays that twice in a clean child and seals each picture inside its Case.
    4. the Candidate answers once per Case, no tools.
    5. at grading, :func:`lab_bench_2_exact_match` asks the judge with the authors'
       exact-match prompt; correct scores 1, incorrect and unsure score 0.

References:
    - Paper: https://arxiv.org/abs/2604.09554 (LABBench2, Laurent et al., 2026)
    - Dataset: https://huggingface.co/datasets/EdisonScientific/labbench2 (gated, CC BY-SA 4.0)
    - The authors' harness (protocol authority, CC BY-SA 4.0):
      https://github.com/EdisonScientific/labbench2/tree/0cabab27f6a23a5bc060a4699205709f1be7e93f
    - The inspect port inspect_evals' register points to (MIT):
      https://github.com/Generality-Labs/lab-bench/tree/081864af494b180ecf6aae3f7333e384c0d227af/src/lab_bench_2
"""

from __future__ import annotations

import ast
import base64
import io
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageUser, ContentImage, ContentText, get_model
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState, generate

from screamingface_engine_inspect.judge_redraw import JudgedItem, judge_until_parsed
from screamingface_engine_inspect.local_tasks.lab_bench_2.figures import fetch_question_files
from screamingface_engine_inspect.local_tasks.lab_bench_2.vendor.lab_bench_port import (
    JUDGE_VERDICT_CORRECT,
    parse_judge_verdict,
)
from screamingface_engine_inspect.local_tasks.lab_bench_2.vendor.labbench2 import (
    STRUCTURED_EVALUATION_PROMPT_EXACT_MATCH,
    file_mode_question,
)
from screamingface_engine_inspect.picture_input import MAX_PICTURE_BASE64_BYTES

# ── pins ───────────────────────────────────────────────────────────────────────────────────
DATASET: Final[str] = "EdisonScientific/labbench2"
#: The dataset's HEAD on 2026-11-04, after the authors' 2026-10-08 fix of one tableqa2 answer
#: (owner decision on OME-1733, 2026-10-28).
DATASET_REVISION: Final[str] = "3678e7e38748477d0606407468db9cd7e2f2e667"
#: Each config has one split.
DATASET_SPLIT: Final[str] = "train"
#: The two picture configs and the row count each holds at the pinned revision; a dataset
#: that grew or shrank would otherwise ship a differently sized Benchmark under the same name.
CASE_COUNTS: Final[Mapping[str, int]] = {"figqa2-img": 101, "tableqa2-img": 100}

#: The judge, as the scorer calls it through the gateway provider: the authors' and the inspect
#: port's default grader, Claude Sonnet 4.5 (owner decision on OME-1733, 2026-11-04). The row's
#: JudgeSpec pins the same model and its temperature 0.
JUDGE_MODEL: Final[str] = "screamingface/openrouter/anthropic/claude-sonnet-4.5"

#: The score of each verdict, the authors' ``LLMJudgeEvaluator``: only correct earns the mark.
CORRECT_SCORE: Final[float] = 1.0
NOT_CORRECT_SCORE: Final[float] = 0.0

# NAMED DEVIATION (OME-1970, owner 2026-11-26): two FigQA2 image figures re-sent as lossless WebP.
#: The Cases whose figure is over the hosts' picture floor (5,242,880 bytes of base64, which
#: Bedrock counts; OpenRouter can pick Bedrock for any Claude call), by Case number, each with
#: the dataset's own id so a re-ordered dataset cannot shrink the wrong figure. Measured
#: 25 Nov 2026: Case 4 is 4184 × 4834 px, 4,147,650 bytes of PNG, 5,530,200 of base64; Case 82
#: is 3156 × 3119 px, 4,109,792 bytes of PNG, 5,479,724 of base64. Re-saved as lossless WebP
#: they take 3,578,520 and 4,031,124 bytes of base64 with every pixel kept, so the only change
#: the Candidate sees is the file format (HLE and MathVista already send WebP). WHY not shrink
#: the pixels: a smaller PNG is not smaller here (5% fewer pixels gave 10.4 MB, noisier to
#: compress), and lossless keeps the authors' exam. The published revision holds by named
#: exception (owner, 2026-11-27): the model gets exactly the same pixels; only the file format
#: changed.
FITTED_TO_THE_PICTURE_FLOOR: Final[Mapping[str, Mapping[int, str]]] = {
    "figqa2-img": {
        4: "882b5ff3-83b4-4e64-a7d3-88af1476cfa0-img",
        82: "13ad1153-33c0-48c3-8e5c-d47688280aaa-img",
    }
}
#: libwebp's slowest, tightest lossless effort; WHY fixed: the bytes are sealed in the Case
#: Digest, so the encoder settings must never drift with a default.
_WEBP_LOSSLESS_METHOD: Final[int] = 6
_WEBP_LOSSLESS_QUALITY: Final[int] = 100
#: Pillow modes whose pixels 8-bit RGBA holds exactly, so the WebP round trip can be compared
#: in RGBA. WHY not 16-bit or float modes: converting them to RGBA clips, so a lossy WebP would
#: compare equal.
_EIGHT_BIT_MODES: Final[frozenset[str]] = frozenset({"1", "L", "LA", "P", "PA", "RGB", "RGBA"})


class LabBench2RowError(ValueError):
    """A dataset row the Task cannot turn into a Case; the build fails, naming the row."""


# ── dataset loader ─────────────────────────────────────────────────────────────────────────
def load_rows(tag: str) -> list[dict[str, Any]]:
    """Load one picture config at the pinned revision, in file order, refusing a wrong size."""

    import datasets  # recorded (and its revision forced) by the importer's Case Source recorder

    expected: int | None = CASE_COUNTS.get(tag)
    if expected is None:
        raise LabBench2RowError(f"{tag!r} is not one of the picture configs {sorted(CASE_COUNTS)}")
    loaded: Any = datasets.load_dataset(
        DATASET, tag, split=DATASET_SPLIT, revision=DATASET_REVISION
    )
    rows: list[dict[str, Any]] = [dict(row) for row in loaded]
    if len(rows) != expected:
        raise LabBench2RowError(
            f"{DATASET}@{DATASET_REVISION} config {tag!r} holds {len(rows)} rows, but the "
            f"Benchmark declares {expected} Cases; refusing to prepare a differently sized "
            "Benchmark under that name"
        )
    return rows


def record_to_sample(
    row: Mapping[str, Any],
    case_id: int,
    fetch: Callable[[str], list[Path]] = fetch_question_files,
    fitted: Mapping[int, str] | None = None,
) -> Sample:
    """One dataset row → the authors' file-mode message: the question text, then its picture.

    The text is the authors' file-mode question (:func:`file_mode_question`), naming the
    attached files by base name; the pictures follow it in one user message, in file-name
    order, as the authors' loader passes ``[question_text, *files]``. The ideal answer is the
    target; the dataset's id, tag and source papers ride the metadata.

    Worked example, FigQA2 image row 1: question ``"For L1 Layer M1 neurons, which contrast
    resulted in the highest calcium peak in the dark condition?"``, files
    ``/figs/imgs/b60fdf79-…/`` holding ``figure.png`` → one user message
    ``[text "For L1 … condition?\\n\\nAttached files:\\n- figure.png\\n\\nUse only …", image
    <cache>/…/figure.png]``, target ``"+/- 0.5"``.

    Args:
        row: one dataset row.
        case_id: the Case's 1-based position in the config.
        fetch: files prefix → local files (the tests pass a fake; the build fetches).
        fitted: Case number → dataset id of the Cases whose figure is re-sent as lossless
            WebP to fit the hosts' picture floor (:data:`FITTED_TO_THE_PICTURE_FLOOR`).

    Raises:
        LabBench2RowError: the row lacks a question, an ideal answer or a files prefix, is not
            served in file mode, or its prefix holds a file that is not a picture; or a fitted
            Case's row has another dataset id, or its figure fits already or cannot fit.
    """

    question: str = _required_text(row, "question", case_id)
    ideal: str = _required_text(row, "ideal", case_id)
    prefix: str = _required_text(row, "files", case_id)
    if not _file_mode(row.get("mode"), case_id):
        raise LabBench2RowError(f"case {case_id}: the row is not served in file mode")
    suffix: object = row.get("prompt_suffix") or ""
    if not isinstance(suffix, str):
        raise LabBench2RowError(f"case {case_id}: prompt_suffix must be text")
    files: list[Path] = fetch(prefix)
    pictures: list[Path] = [path for path in files if path.suffix.lower() in _PICTURE_SUFFIXES]
    # WHY refuse a non-picture: the authors would attach it as a document, a part this
    # Benchmark's picture envelope cannot carry; none exists at the pinned revision.
    if not pictures or len(pictures) != len(files):
        raise LabBench2RowError(
            f"case {case_id}: the files prefix must hold pictures only, found "
            f"{sorted(path.name for path in files)}"
        )
    text: str = file_mode_question(question, [path.name for path in files], suffix)
    images: list[str] = [str(path) for path in pictures]
    expected_id: str | None = (fitted or {}).get(case_id)
    if expected_id is not None:
        dataset_id: str = _required_text(row, "id", case_id)
        # INVARIANT: shrink only the figure the deviation names, by number AND dataset id.
        if dataset_id != expected_id:
            raise LabBench2RowError(
                f"case {case_id}: listed to fit the picture floor as {expected_id!r}, but the "
                f"row is {dataset_id!r}"
            )
        images = [_fitted_picture(path, case_id) for path in pictures]
    return Sample(
        id=case_id,
        input=[
            ChatMessageUser(
                content=[
                    ContentText(text=text),
                    *(ContentImage(image=image) for image in images),
                ]
            )
        ],
        target=ideal,
        metadata={
            "id": _required_text(row, "id", case_id),
            "tag": _required_text(row, "tag", case_id),
            "sources": str(row.get("sources") or ""),
        },
    )


#: The picture file types the authors' harness attaches as images (``evals/utils.py``).
_PICTURE_SUFFIXES: Final[frozenset[str]] = frozenset({".png", ".jpg", ".jpeg"})


def _fitted_picture(path: Path, case_id: int) -> str:
    """One figure over the hosts' picture floor, re-sent as lossless WebP: same pixels, smaller.

    Think of it as re-zipping a file with a better zip: every pixel comes back identical, only
    the container changes. Stages, in execution order:

    1. Measure the figure as the Case would carry it: its base64 text. If that already fits
       :data:`MAX_PICTURE_BASE64_BYTES`, the deviation is stale and the build fails.
    2. Re-encode with libwebp's lossless coder at fixed settings (they are sealed in the Case
       Digest through the bytes they produce). A figure whose pixels 8-bit RGBA cannot hold
       (16-bit, say) fails the build first.
    3. Decode the WebP and compare every pixel with the figure's: "lossless" is checked, not
       assumed. WHY: with these settings libwebp drops the colour of a fully transparent pixel,
       and Pillow saves a 16-bit picture as 8-bit, both without an error.
    4. If the WebP's base64 still does not fit, the build fails: shrinking pixels would be a
       new deviation for the owner to decide, never a silent fallback.

    Worked example, Case 4: PNG 4,147,650 bytes → 5,530,200 of base64, over 5,242,880 →
    WebP 2,683,890 bytes → 3,578,520 of base64, which fits → ``data:image/webp;base64,…``.
    """

    # WHY import here: Pillow comes with the `inspect` extra, not the extra-less install the
    # typecheck gate reads this module in.
    from PIL import Image

    # Stage 1 — over the floor as sent?
    original: bytes = path.read_bytes()
    original_size: int = len(base64.b64encode(original))
    if original_size <= MAX_PICTURE_BASE64_BYTES:
        raise LabBench2RowError(
            f"case {case_id}: the figure already fits the picture floor ({original_size:,} bytes "
            f"as base64, at most {MAX_PICTURE_BASE64_BYTES:,}); drop it from the fitted list"
        )
    # Stage 2 — lossless WebP at fixed settings, for a figure 8-bit RGBA can hold.
    buffer: io.BytesIO = io.BytesIO()
    with Image.open(path) as picture:
        if picture.mode not in _EIGHT_BIT_MODES:
            raise LabBench2RowError(
                f"case {case_id}: the figure is {picture.mode}, which 8-bit WebP cannot hold "
                f"pixel for pixel"
            )
        picture.save(
            buffer,
            format="WEBP",
            lossless=True,
            quality=_WEBP_LOSSLESS_QUALITY,
            method=_WEBP_LOSSLESS_METHOD,
        )
        source_pixels: bytes = picture.convert("RGBA").tobytes()
    # Stage 3 — every pixel came back.
    # INVARIANT: the WebP decodes to the figure's exact pixels, so the deviation changes the
    # container only.
    with Image.open(io.BytesIO(buffer.getvalue())) as fitted:
        if fitted.convert("RGBA").tobytes() != source_pixels:
            raise LabBench2RowError(
                f"case {case_id}: lossless WebP changed the figure's pixels; it cannot be sent "
                f"as WebP unchanged"
            )
    encoded: str = base64.b64encode(buffer.getvalue()).decode("ascii")
    # Stage 4 — it must now fit.
    if len(encoded) > MAX_PICTURE_BASE64_BYTES:
        raise LabBench2RowError(
            f"case {case_id}: lossless WebP is {len(encoded):,} bytes as base64, still over "
            f"the picture floor of {MAX_PICTURE_BASE64_BYTES:,}"
        )
    return f"data:image/webp;base64,{encoded}"


def _required_text(row: Mapping[str, Any], field: str, case_id: int) -> str:
    """A row field that must be non-blank text, returned unchanged."""

    value: object = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise LabBench2RowError(f"case {case_id}: {field} must be non-empty text")
    return value


def _file_mode(mode: object, case_id: int) -> bool:
    """Whether the row is served in file mode; the dataset stores the modes as a dict's repr.

    The authors' ``QuestionMode`` defaults every mode to True when absent; the pinned rows all
    carry ``"{'file': True, 'retrieve': False, 'inject': False}"``.
    """

    if mode is None or mode == "":
        return True
    parsed: object = mode
    if isinstance(mode, str):
        try:
            parsed = ast.literal_eval(mode)
        except (ValueError, SyntaxError):
            raise LabBench2RowError(f"case {case_id}: mode is not a readable dict") from None
    if not isinstance(parsed, dict):
        raise LabBench2RowError(f"case {case_id}: mode must be a dict of modes")
    return parsed.get("file", True) is not False


# ── the judge's reply ──────────────────────────────────────────────────────────────────────
def parse_verdict(reply: str) -> tuple[str, str] | None:
    """The judge's verdict word and its whole reply, or None when the reply names no verdict.

    The inspect port's reader (:func:`parse_judge_verdict`): the LAST ``result`` followed by
    correct, incorrect or unsure, any case, so an echo of the rubric words earlier in the
    reasoning does not decide it; ``result = "correct"`` (code) is no verdict. The reply is
    kept whole as the judge's evidence.
    """

    verdict: str | None = parse_judge_verdict(reply)
    return None if verdict is None else (verdict, reply)


# ── the scorer ─────────────────────────────────────────────────────────────────────────────
@scorer(metrics=[mean(), stderr()])
def lab_bench_2_exact_match(judge_model: str = JUDGE_MODEL) -> Scorer:
    """Grade one answer against the ideal answer with the authors' exact-match judge.

    Think of it as a marker holding the authors' answer sheet: numbers count as equal when
    they agree to within 1e-6 whatever their notation, a non-numeric answer must state the same
    thing, and a doubtful case is marked unsure. Only "correct" earns the mark.

    Stages, in execution order:

    1. No answer: an empty or blank reply scores 0 without asking the judge, the authors'
       "No output provided".
    2. Ask: fill the authors' exact-match prompt with the question text the Candidate saw
       (``state.input_text``, the text part of the Case, "Attached files" lines included, as
       the authors' ``extract_question_from_inputs`` reads it), the ideal answer and the
       answer as given (the authors do not strip it), and send it as one user message
       through :func:`judge_until_parsed`. The row pins temperature 0.
    3. Read: :func:`parse_verdict`. A reply with no verdict is redrawn, at most twice; a third
       one raises, and the Case fails by name and counts 0 (the authors' evaluator scores any
       judge failure 0.0).
    4. Score: correct → 1.0; incorrect or unsure → 0.0.

    Worked example: ideal ``"1.67"``, answer ``"The odds ratio is 1.670."``, judge reply
    ``"rationale: 1.670 equals 1.67.\\nresult: correct"`` → verdict ``correct``, score 1.0.

    Args:
        judge_model: the gateway judge, ``screamingface/<model>``; the row pins the same one.

    Returns:
        The inspect scorer. The Score's value is 1.0 or 0.0, its explanation the judge's reply.

    Raises:
        JudgeReplyUnparseable: no reply named a verdict after the redraws.
    """

    async def score(state: TaskState, target: Target) -> Score:
        answer: str = state.output.completion
        # Stage 1 — no answer, no judge call.
        if not answer.strip():
            return Score(
                value=NOT_CORRECT_SCORE,
                answer=answer,
                explanation="No output provided",
                metadata={"verdict": None, "judge_redraws": 0},
            )
        # Stage 2-3 — ask, read, redraw while the reply names no verdict.
        prompt: str = STRUCTURED_EVALUATION_PROMPT_EXACT_MATCH.format(
            question=state.input_text,
            correct_answer=target.text,
            answer=answer,
        )
        judged: JudgedItem[tuple[str, str]] = await judge_until_parsed(
            get_model(judge_model), prompt, parse_verdict, item="the answer"
        )
        verdict, reply = judged.verdict
        # Stage 4 — only correct earns the mark.
        return Score(
            value=CORRECT_SCORE if verdict == JUDGE_VERDICT_CORRECT else NOT_CORRECT_SCORE,
            answer=answer,
            explanation=reply,
            metadata={"verdict": verdict, "judge_redraws": judged.redraws},
        )

    return score


# ── the Tasks ──────────────────────────────────────────────────────────────────────────────
def _task(tag: str) -> Task:
    """One picture config as a Task: its rows in file order, one generate, the judge."""

    fitted: Mapping[int, str] = FITTED_TO_THE_PICTURE_FLOOR.get(tag, {})
    samples: list[Sample] = [
        record_to_sample(row, case_id, fitted=fitted)
        for case_id, row in enumerate(load_rows(tag), start=1)
    ]
    return Task(
        dataset=MemoryDataset(samples=samples, name=f"lab_bench_2_{tag.replace('-', '_')}"),
        solver=generate(),
        scorer=lab_bench_2_exact_match(),
    )


@task
def lab_bench_2_figqa2_img() -> Task:
    """LABBench2 FigQA2 image: 101 questions, each about one figure from a biology paper."""

    return _task("figqa2-img")


@task
def lab_bench_2_tableqa2_img() -> Task:
    """LABBench2 TableQA2 image: 100 questions, each about one table from a biology paper."""

    return _task("tableqa2-img")
