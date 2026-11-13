# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""An answer inside a wrapper is graded against its key; a reply inspect reads keeps its reading.

What these tests pin (OME-1907, inspect_ai issue 5055): every row of the OME-1907 shapes table,
read through inspect's REAL ``parse_answers`` with our peel as the fallback; the same rule
through the real graders (the scorer adapter, mathvista's and bbh's scorers); the cap of 3
layers; a tripwire on the pinned inspect_ai; and the revision pin landing on exactly the rows
graded from option marks.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.model import ModelOutput  # noqa: E402
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from inspect_ai.solver._multiple_choice import parse_answers  # noqa: E402
from test_inspect_task_replay_benchmarks import _MCQ_CASES, _node, _scores  # noqa: E402

from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    OPTION_MARK_READERS,
    _option_marking_pins,
    imported_benchmark,
)
from screamingface_engine_inspect.local_tasks.bbh.bbh import BINARY_CHOICE, bbh_scorer  # noqa: E402
from screamingface_engine_inspect.named_deviations.wrapped_letter.mathvista import (  # noqa: E402
    mathvista_wrapped_scorer,
)
from screamingface_engine_inspect.named_deviations.wrapped_letter.wrapped_letter import (  # noqa: E402
    MAX_LAYERS,
    parse_wrapped_answers,
    peeled_copies,
)
from screamingface_engine_inspect.prepare import PreparedCase  # noqa: E402

#: Rows 1-6 of the OME-1907 table: inspect reads these today, and must read them the same.
_INSPECT_READS: list[tuple[str, bool, set[str]]] = [
    ("ANSWER: B", False, {"B"}),
    ("answer: b", False, {"B"}),
    ("ANSWER: B.", False, {"B"}),
    ("ANSWER: B)", False, {"B"}),
    ("**ANSWER: B**", False, {"B"}),
    ("ANSWER: A, B", True, {"A", "B"}),
]

#: Rows 7-20: inspect reads none of these; the peel reads the letter inside the wrapper.
_WRAPPED: list[tuple[str, bool, set[str]]] = [
    ("ANSWER: $B", False, {"B"}),
    ("ANSWER: $B$", False, {"B"}),
    ("ANSWER: **B**", False, {"B"}),
    ("ANSWER: __B__", False, {"B"}),
    ("ANSWER: `B`", False, {"B"}),
    ("ANSWER: (B)", False, {"B"}),
    ("ANSWER: [B]", False, {"B"}),
    ("ANSWER: \\boxed{B}", False, {"B"}),
    ("ANSWER: **A, B**", True, {"A", "B"}),
    ("ANSWER: $A, B$", True, {"A", "B"}),
    ("ANSWER: $\\boxed{B}$", False, {"B"}),
    ("ANSWER: **$B$**", False, {"B"}),
    ("**ANSWER:** B", False, {"B"}),
    ("__ANSWER:__ B", False, {"B"}),
]

#: Rows 21-24: refused by inspect and still refused. 21 and 23 are PR 5058's regression cases.
_REFUSED: list[str] = [
    "ANSWER: B because it is red",
    "The answer is B",
    "I don't know",
    "ANSWER: E",
]


def _state(reply: str, choices: int = 4, metadata: dict[str, object] | None = None) -> TaskState:
    """A TaskState carrying one reply over `choices` options, as the scorer adapter builds it."""

    return TaskState(
        model="stand-in",  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=1,
        epoch=1,
        input="Which seat is free?",
        messages=[],
        choices=[str(index) for index in range(choices)],
        output=ModelOutput.from_content(model="stand-in", content=reply),
        metadata=metadata or {},
    )


@pytest.mark.parametrize(("reply", "multiple_correct", "expected"), _INSPECT_READS)
def test_a_reply_inspect_reads_keeps_its_reading(
    reply: str, multiple_correct: bool, expected: set[str]
) -> None:
    """INVARIANT: the peel never runs when inspect reads an answer, so no grade moves."""

    state: TaskState = _state(reply)

    assert parse_answers(state, multiple_correct) == expected
    assert parse_wrapped_answers(state, multiple_correct) == expected


@pytest.mark.parametrize(("reply", "multiple_correct", "expected"), _WRAPPED)
def test_a_letter_inside_a_wrapper_is_read(
    reply: str, multiple_correct: bool, expected: set[str]
) -> None:
    state: TaskState = _state(reply)

    assert parse_answers(state, multiple_correct) == set()
    assert parse_wrapped_answers(state, multiple_correct) == expected


@pytest.mark.parametrize("reply", _REFUSED)
def test_a_reply_inspect_refuses_stays_refused(reply: str) -> None:
    """WHY: words after the letter, no label, or a letter past the options are not answers;
    reading them is what broke inspect_ai PR 5058."""

    assert parse_wrapped_answers(_state(reply), multiple_correct=False) == set()


#: A draft answer at the start of a line, then the final answer mid-line, both wrapped. inspect
#: reads none of them; peeling every site would turn the draft into a line-start match, which
#: inspect's strict pass prefers over the final answer (review of PR 1783).
_RETRACTED_DRAFTS: list[str] = [
    "ANSWER: (A)\nRe-checking, A fails. Final ANSWER: $C$",
    "ANSWER: **A**\n\nWait, that's wrong. The final ANSWER: **C**",
    "**ANSWER:** A\nNo, wrong. Final **ANSWER:** C",
]


@pytest.mark.parametrize("reply", _RETRACTED_DRAFTS)
def test_a_retracted_draft_is_never_read_over_the_final_answer(reply: str) -> None:
    """INVARIANT: only the last `ANSWER:` is peeled, so the final answer wins, as inspect's
    "answer on the last line" reading intends. Reading the draft would only ever help the
    Candidate: a retracted A would score 1 on a key of A."""

    assert parse_answers(_state(reply), multiple_correct=False) == set()
    assert parse_wrapped_answers(_state(reply), multiple_correct=False) == {"C"}


def test_peeling_stops_after_three_layers() -> None:
    """WHY a cap: a reply of nested brackets is not peeled down to a stray letter."""

    within: str = "ANSWER: **(`B`)**"  # three layers: bold, brackets, backticks
    beyond: str = "ANSWER: $**(`B`)**$"  # the same inside a fourth, `$…$`

    assert len(peeled_copies(beyond)) == MAX_LAYERS == 3
    assert parse_wrapped_answers(_state(within), multiple_correct=False) == {"B"}
    assert parse_wrapped_answers(_state(beyond), multiple_correct=False) == set()


def test_the_stored_reply_is_never_rewritten() -> None:
    state: TaskState = _state("ANSWER: $B$")

    parse_wrapped_answers(state, multiple_correct=False)

    assert state.output.completion == "ANSWER: $B$"


def test_tripwire_the_pinned_inspect_ai_still_reads_a_wrapped_letter_as_no_answer() -> None:
    """When an inspect_ai bump starts reading `ANSWER: $B$`, this fails: point the rows back at
    inspect's own reading and drop the Named Deviation (inspect_ai issue 5055)."""

    assert parse_answers(_state("ANSWER: $B$"), multiple_correct=False) == set()


@pytest.mark.asyncio
async def test_the_scorer_adapter_grades_a_wrapped_letter_through_the_real_grader() -> None:
    """End to end on mmlu_pro (inspect's `choice`) and a lab_bench row (`precision_choice`):
    the key-B Case's wrapped right answer scores 1, the key-A Case's wrapped wrong one 0."""

    cases: list[PreparedCase] = _MCQ_CASES  # stand-in Cases: key B, then key A
    for key in ("mmlu_pro", "lab_bench_litqa"):
        benchmark = imported_benchmark(key)
        with tempfile.TemporaryDirectory() as root:
            node = _node(benchmark, cases, Path(root))
            scores: list[object] = await _scores(node, benchmark, ["ANSWER: $B", "ANSWER: **B**"])
        assert scores == [1.0, 0.0], key


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "question_type", "key", "expected"),
    [
        ("ANSWER: $B$", "multi_choice", "B", CORRECT),
        ("ANSWER: (B)", "multi_choice", "B", CORRECT),
        ("ANSWER: **42**", "free_form", "42", CORRECT),
        ("ANSWER: C", "multi_choice", "B", INCORRECT),
        ("ANSWER: **C**", "multi_choice", "B", INCORRECT),
        ("ANSWER: 1.50", "free_form", "1.5", INCORRECT),
    ],
)
async def test_mathvista_grades_a_wrapped_answer_and_keeps_every_other_mark(
    reply: str, question_type: str, key: str, expected: str
) -> None:
    """WHY the last three: a wrong letter stays wrong with or without a wrapper, and an
    unwrapped free-form answer keeps the eval's exact match (`1.50` is not `1.5`)."""

    scorer = mathvista_wrapped_scorer()
    state: TaskState = _state(reply, metadata={"question_type": question_type})

    score: Score | None = await scorer(state, Target(key))

    assert score is not None and score.value == expected
    assert score.explanation is not None and reply in score.explanation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "expected"),
    [("ANSWER: **Yes**", CORRECT), ("ANSWER: Yes", CORRECT), ("ANSWER: **No**", INCORRECT)],
)
async def test_bbh_yes_no_subsets_read_a_wrapped_word(reply: str, expected: str) -> None:
    scorer = bbh_scorer()
    state: TaskState = _state(reply, metadata={"dataset_type": BINARY_CHOICE})

    score: Score | None = await scorer(state, Target("Yes"))

    assert score is not None and score.value == expected


def test_the_option_marking_pin_lands_on_exactly_the_rows_whose_scorer_is_listed() -> None:
    """The pin follows ``OPTION_MARK_READERS``, and only it. WHY not more: no declaration says
    which rows' Cases carry options (the adapter learns it per Case, from the Grading Material),
    so the list is kept by hand; the next test makes a new choice scorer impossible to miss."""

    pinned: set[str] = {spec.key for spec in BENCHMARKS if _option_marking_pins(spec)}
    readers: set[str] = {spec.key for spec in BENCHMARKS if spec.scorer in OPTION_MARK_READERS}

    assert pinned == readers
    assert len(pinned) == 46
    assert {"mmlu_pro", "bbh", "lab_bench_litqa"} <= pinned
    assert not {"stereoset", "sad_influence", "mathvista"} & pinned


#: Choice scorers that read the reply themselves, not the option marks, so the peel in the
#: scorer adapter never changes their grade (read 2026-11-13, inspect_evals 0.20.0).
_CHOICE_SCORERS_NOT_READING_MARKS: frozenset[str] = frozenset(
    {
        # its own prefix rule on the raw reply ("B", "(B)", "B London").
        "inspect_evals.sad.sad:lenient_mcq_choice",
        # the first character after the last "ANSWER: ".
        "inspect_evals.stereoset.stereoset:multiple_choice_scorer",
    }
)


def test_every_choice_scorer_is_classified_as_reading_marks_or_not() -> None:
    """A row added with a new choice scorer fails here until someone decides whether it reads
    the option marks (add it to ``OPTION_MARK_READERS``, so the rule pins its revision) or the
    reply (add it above). WHY by name: it is the one signal assembly has without importing."""

    choice_scorers: set[str] = {
        spec.scorer for spec in BENCHMARKS if "choice" in spec.scorer.rpartition(":")[2]
    }
    in_use: set[str] = {spec.scorer for spec in BENCHMARKS}

    assert choice_scorers <= OPTION_MARK_READERS | _CHOICE_SCORERS_NOT_READING_MARKS
    assert OPTION_MARK_READERS <= in_use, "a listed reader no row uses any more"
