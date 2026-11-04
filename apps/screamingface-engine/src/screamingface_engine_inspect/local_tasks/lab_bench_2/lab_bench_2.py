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

    Raises:
        LabBench2RowError: the row lacks a question, an ideal answer or a files prefix, is not
            served in file mode, or its prefix holds a file that is not a picture.
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
    return Sample(
        id=case_id,
        input=[
            ChatMessageUser(
                content=[
                    ContentText(text=text),
                    *(ContentImage(image=str(path)) for path in pictures),
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

    samples: list[Sample] = [
        record_to_sample(row, case_id) for case_id, row in enumerate(load_rows(tag), start=1)
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
