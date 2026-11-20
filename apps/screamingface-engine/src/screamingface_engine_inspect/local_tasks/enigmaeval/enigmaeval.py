# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai, datasets),
# absent in the default (extra-less) install the typecheck gate runs against; it is loaded only
# behind `inspect_available()`, like every other module in this package.
"""EnigmaEval, 1,161 puzzle-hunt puzzles answered by a word or short phrase, as a LOCAL Task.

Think of it as a puzzle hunt with an answer box: each puzzle hands the Candidate the puzzle's
text and its pictures, tells it what kind of answer to expect (a word, a pair, a list) and a
page of solving tips, and asks for a worked solution ending in ``<answer>…</answer>``. The
marker reads the first answer box, lowercases it, keeps only letters and digits, and compares it
with the gold answer. No judge, one Attempt per puzzle.

Execution order, as the importer and the Engine see it:

    1. ``enigmaeval()`` → :func:`load_rows`: the gated ``cais/EnigmaEval`` v2 ``test`` split at
       the pinned revision (the importer forces it at every build), in file order, 1,161 rows.
    2. per row, :func:`record_to_sample`: the authors' system and user prompts
       (:func:`authors_prompts`), then each picture re-saved as PNG the authors' way
       (``_pil_to_base64_png``, palette and other modes to RGB). The Sample id is the row's
       ``task_id``; the source, the id and the dataset's canary ride the metadata.
    3. the importer drops the Samples the prepare row holds out, replays the rest twice in a
       clean child and seals each picture inside its Case.
    4. the Candidate answers once per Case, no tools.
    5. at grading, :func:`enigmaeval_exact_match`: the authors' answer reader and normaliser.

References:
    - Paper: https://arxiv.org/abs/2502.08859 (EnigmaEval, Wang et al., 2025)
    - Dataset: https://huggingface.co/datasets/cais/EnigmaEval (gated, per-source licences)
    - The authors' harness (protocol authority, MIT), branch ``dev``:
      https://github.com/centerforaisafety/simple-evals/tree/6614edf59833140fb77e61758bbb2674b54a445e/enigmaeval
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final, cast

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, ContentImage, ContentText
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState, generate

from screamingface_engine_inspect.local_tasks.enigmaeval.vendor.simple_evals import (
    MIT_TIPS,
    STANDARD_TIPS,
    _pil_to_base64_png,
    evaluate_answer,
    extract_answer_from_response,
    get_answer_type,
)

# ── pins ───────────────────────────────────────────────────────────────────────────────────
DATASET: Final[str] = "cais/EnigmaEval"
#: The v2 release's HEAD on 2026-11-13 (last modified 2026-07-23).
DATASET_REVISION: Final[str] = "9ed38dabb105ad900ef850a937014d8653ae9f94"
#: The dataset's one split.
DATASET_SPLIT: Final[str] = "test"
#: The rows at the pinned revision; a dataset that grew or shrank would otherwise ship a
#: differently sized Benchmark under the same name.
ROW_COUNT: Final[int] = 1161

#: The source whose puzzles get the authors' MIT Mystery Hunt tips and no previous answers.
MIT_MYSTERY_HUNT: Final[str] = "MIT Mystery Hunt"
#: What the authors look for in the text to add the picture-order sentence. WHY the text, not
#: the picture count: it is the authors' rule; 11 puzzles with pictures do not name
#: ``[image_1]`` (no sentence) and 9 without pictures do (the sentence anyway), owner ruling on
#: OME-1874, 2026-11-13.
IMAGE_REFERENCE: Final[str] = "[image_1]"

#: The score of a right and a wrong answer.
CORRECT_SCORE: Final[float] = 1.0
INCORRECT_SCORE: Final[float] = 0.0


class EnigmaEvalRowError(ValueError):
    """A dataset row the Task cannot turn into a Case; the build fails, naming the row."""


# ── the authors' prompts, restated ─────────────────────────────────────────────────────────
# AIDEV-NOTE: restated, not copied, from the authors' ``PromptMaker`` (enigmaeval_utils.py
# L225-L231, L252-L284 and L321-L348 at the pinned commit; the dispatch is enigmaeval_eval.py
# L180-L190): their system f-string's first line ends in a
# space, which the repo's trailing-whitespace hook would strip from a copy. The space is the
# explicit " \n" below. test_local_task_enigmaeval.py pins the output to the authors' builder's.
#: ``PromptMaker.__init__`` wraps each tips file: a newline, the file, then a rule.
_STANDARD_TIPS_BLOCK: Final[str] = "\n" + STANDARD_TIPS + "\n---\n"
_MIT_TIPS_BLOCK: Final[str] = "\n" + MIT_TIPS + "\n---\n"

_SYSTEM_PROMPT: Final[str] = (
    "You will be presented with a puzzle to solve. The puzzle may not have specific "
    "instructions, but you know that the answer to the puzzle is a {answer_type}. \n"
    "Do not ask any questions about how to proceed, just do your best to solve the puzzle.\n"
    "Here are some tips for solving puzzles of this type:\n"
    "{tips}\n"
)
_USER_PROMPT: Final[str] = (
    "Your task is to solve the following puzzle.{preamble}\n"
    "\n"
    "Puzzle:\n"
    "{puzzle}\n"
    "\n"
    "Write out a step-by-step solution to the puzzle. At the end of your solution, write your "
    "answer in the following format:\n"
    "{answer_format}\n"
)
_IMAGES_SENTENCE: Final[str] = (
    " The attached images are presented in the order they are referenced in the text."
)
_PREV_ANSWERS_SENTENCE: Final[str] = (
    " This puzzle uses at least some of the following answers from other puzzles to arrive at "
    "its own solution: {prev_answers}.{preamble}"
)


def authors_prompts(
    question: str, answer: str, prev_answers: str | None, category: str
) -> tuple[str, str]:
    """The (user, system) prompt pair the authors' harness sends for one transcribed puzzle.

    The authors' dispatch, in their order: an MIT Mystery Hunt puzzle gets
    ``get_prompt_mit_transcribed`` (MIT tips, previous answers never named); any other gets
    ``get_prompt_standard_transcribed`` (standard tips, then the previous answers when the row
    has any). The gold answer shapes only the answer type: a comma makes it a pair (one comma)
    or a list (more), with the matching ``<answer>`` format line.

    Worked example: question ``"[Name] Meta: Taking The Rap\\n[image_1]"``, previous answers
    ``"BLINDFOLD, CONSOLIDATE, MUGSHOTS, ROAD BLOCK"``, a gold answer with no comma → user text
    ``"Your task is to solve the following puzzle. This puzzle uses at least some of the
    following answers from other puzzles to arrive at its own solution: BLINDFOLD, …, ROAD
    BLOCK. The attached images are presented in the order they are referenced in the text.
    \\n\\nPuzzle:\\n[Name] Meta: …\\n\\nWrite out … format:\\n<answer>answer</answer>\\n"``, and
    a system text naming "a word or short phrase" followed by the standard tips.
    """

    answer_type, answer_format = get_answer_type(answer)
    preamble: str = _IMAGES_SENTENCE if IMAGE_REFERENCE in question else ""
    if category == MIT_MYSTERY_HUNT:
        tips: str = _MIT_TIPS_BLOCK
    else:
        tips = _STANDARD_TIPS_BLOCK
        if prev_answers:
            preamble = _PREV_ANSWERS_SENTENCE.format(prev_answers=prev_answers, preamble=preamble)
    user: str = _USER_PROMPT.format(preamble=preamble, puzzle=question, answer_format=answer_format)
    system: str = _SYSTEM_PROMPT.format(answer_type=answer_type, tips=tips)
    return user, system


# ── dataset loader ─────────────────────────────────────────────────────────────────────────
def load_rows() -> list[dict[str, Any]]:
    """Load the ``test`` split at the pinned revision, in file order, refusing a wrong size."""

    import datasets  # recorded (and its revision forced) by the importer's Case Source recorder

    loaded: Any = datasets.load_dataset(DATASET, split=DATASET_SPLIT, revision=DATASET_REVISION)
    rows: list[dict[str, Any]] = [dict(row) for row in loaded]
    if len(rows) != ROW_COUNT:
        raise EnigmaEvalRowError(
            f"{DATASET}@{DATASET_REVISION} holds {len(rows)} rows, but the Benchmark declares "
            f"{ROW_COUNT}; refusing to prepare a differently sized Benchmark under that name"
        )
    return rows


def record_to_sample(row: Mapping[str, Any]) -> Sample:
    """One dataset row → the authors' message: their system prompt, then the user text and
    every picture, in the dataset's order.

    The pictures are the authors' (``_pil_to_base64_png``): each decoded picture re-saved as a
    PNG, a mode other than RGB, RGBA or L converted to RGB first. The gold answer is the target
    exactly as stored, so its commas and ``|`` keep their meaning for the scorer.

    Raises:
        EnigmaEvalRowError: the row lacks a task id, a category, an answer or a question (the
            authors would send a PDF-only puzzle a different prompt; none exists at the pin).
    """

    task_id: str = _required_text(row, "task_id", "?")
    category: str = _required_text(row, "category", task_id)
    answer: str = _required_text(row, "answer", task_id)
    question: str = _required_text(row, "question", task_id)
    prev_answers: object = row.get("prev_answers")
    if prev_answers is not None and not isinstance(prev_answers, str):
        raise EnigmaEvalRowError(f"row {task_id}: prev_answers must be text or null")
    user, system = authors_prompts(question, answer, prev_answers, category)
    pictures: list[str] = _pictures(row.get("images"), task_id)
    return Sample(
        id=task_id,
        input=[
            ChatMessageSystem(content=system),
            ChatMessageUser(
                content=[
                    ContentText(text=user),
                    *(ContentImage(image=picture) for picture in pictures),
                ]
            ),
        ],
        target=answer,
        metadata={
            "task_id": task_id,
            "category": category,
            "canary": _required_text(row, "canary", task_id),
        },
    )


def _pictures(images: object, task_id: str) -> list[str]:
    """The row's pictures as the authors send them: PNG ``data:`` URIs, in list order."""

    if images is None:
        return []
    if not isinstance(images, Sequence):
        raise EnigmaEvalRowError(f"row {task_id}: images must be a list")
    # WHY skip None: the authors' loader drops a picture its re-save returns None for.
    converted: list[str | None] = [_pil_to_base64_png(image) for image in images]
    return [picture for picture in converted if picture is not None]


def _required_text(row: Mapping[str, Any], field: str, task_id: str) -> str:
    """A row field that must be non-blank text, returned unchanged."""

    value: object = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EnigmaEvalRowError(f"row {task_id}: {field} must be non-empty text")
    return value


# ── the scorer ─────────────────────────────────────────────────────────────────────────────
@scorer(metrics=[mean(), stderr()])
def enigmaeval_exact_match() -> Scorer:
    """Grade one reply against the gold answer with the authors' reader and normaliser.

    Think of it as the hunt's answer checker: it reads only what is inside the first answer box
    and ignores case, spaces and punctuation, so ``RAT-TAIL FILE`` and ``rat tail file`` match.

    Stages, in execution order:

    1. Read: the first ``<answer>…</answer>`` in the reply, any case, across lines, stripped
       (the authors' ``extract_answer_from_response``). No box → no answer.
    2. Mark (the authors' ``evaluate_answer`` over ``standardize``): no answer is wrong. Each
       side is lowercased; a side with a comma becomes the SET of its parts, each part keeping
       only a–z and 0–9; a side without one keeps only a–z and 0–9. A gold answer with ``|``
       lists alternatives, and any one match is right.
    3. Score: right → 1.0, wrong → 0.0.

    Worked examples: gold ``"SUN, MOON"``, reply ``"… <answer>Moon, sun</answer>"`` → sets
    ``{"moon", "sun"}`` on both sides, 1.0; reply ``"<answer>sun moon</answer>"`` → the string
    ``"sunmoon"`` against a set, 0.0; gold ``"COLOR|COLOUR"``, reply ``"<answer>Colour
    </answer>"`` → ``"colour"`` is the second alternative, 1.0; a reply with no box, 0.0.

    Returns:
        The inspect scorer. The Score's value is 1.0 or 0.0; its answer is what the box held.
    """

    async def score(state: TaskState, target: Target) -> Score:
        # Stage 1 — read the first answer box.
        answer: str | None = extract_answer_from_response(state.output.completion)
        # Stage 2 — mark. WHY cast: the authors annotate ``model_answer: str`` and handle None.
        right: bool = evaluate_answer(target.text, cast(str, answer))
        # Stage 3 — score.
        return Score(
            value=CORRECT_SCORE if right else INCORRECT_SCORE,
            answer=answer,
            explanation=None if answer is not None else "no <answer> tags in the reply",
        )

    return score


# ── the Task ───────────────────────────────────────────────────────────────────────────────
@task
def enigmaeval() -> Task:
    """EnigmaEval v2: 1,161 puzzle-hunt puzzles in file order, one generate, exact match."""

    return Task(
        dataset=MemoryDataset(
            samples=[record_to_sample(row) for row in load_rows()], name="enigmaeval"
        ),
        solver=generate(),
        scorer=enigmaeval_exact_match(),
    )
