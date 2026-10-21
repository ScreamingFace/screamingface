# pyright: reportMissingImports=false
# WHY file-level: the local Task imports inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""BIG-Bench Hard as a LOCAL inspect Task, asked and marked the paper's way (OME-1696).

What these tests pin, and why:

- the tag retype changes nothing else: every other field of the Sample is upstream's, so the
  Cases are upstream's own questions and worked examples;
- yes/no and free-form questions are sent as upstream sends them; multiple-choice questions are
  sent under inspect's think-step-by-step instruction (Named Deviation 1);
- multiple-choice and yes/no answers are marked as upstream marks them; free-form answers by
  exact match, as the paper grades (Named Deviation 2): each wrong shape upstream passes is
  marked wrong, and the rule reproduces the paper's accuracy on the authors' Codex replies;
- real BBH questions of every answer kind grade through the production aggregate route with
  the network blocked: right replies score 1, wrong ones 0;
- the row: 6,508 Cases (one broken question left out by id), no judge, the subset name kept
  for regrouping.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.model import ChatMessageUser, ModelOutput  # noqa: E402
from inspect_ai.scorer import CORRECT, INCORRECT, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from inspect_evals.bbh.bbh import DatasetType  # noqa: E402
from inspect_evals.bbh.bbh import bbh_scorer as upstream_scorer  # noqa: E402
from inspect_evals.bbh.bbh import bbh_solver as upstream_solver  # noqa: E402
from test_inspect_task_replay_benchmarks import _node, _scores  # noqa: E402

from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from screamingface_engine_inspect.local_tasks.bbh.bbh import (  # noqa: E402
    _with_text_tag,
    bbh_scorer,
    bbh_solver,
    final_answer,
)
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES, PreparedCase  # noqa: E402

_MODEL: str = "none/none"


def _state(sample_input: str, kind: str, *, choices: list[str] | None = None) -> TaskState:
    """A TaskState the way inspect builds one for a BBH Sample; `_tagged` sets the tag's form."""

    return TaskState(
        model=_MODEL,  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=1,
        epoch=1,
        input=sample_input,
        messages=[ChatMessageUser(content=sample_input)],
        choices=choices,
        metadata={"dataset_type": kind, "dataset_name": "stand_in"},
    )


def _tagged(state: TaskState, tag: object) -> TaskState:
    """The same state with its answer-kind tag replaced (enum for upstream, text for ours)."""

    state.metadata = {**state.metadata, "dataset_type": tag}
    return state


def test_the_tag_becomes_the_enum_name_and_nothing_else_changes() -> None:
    """INVARIANT: the retype is the whole deviation. Input, target, choices, id and every other
    metadata key stay upstream's, so the Case Digest seals upstream's own question."""

    sample = Sample(
        id="date_understanding_001",
        input="Tomorrow is 11/12/2019. What is the date yesterday in MM/DD/YYYY?",
        choices=["11/10/2076", "11/10/2019"],
        target="B",
        metadata={
            "dataset_type": DatasetType.MULTIPLE_CHOICE,
            "dataset_name": "date_understanding",
        },
    )

    retyped: Sample = _with_text_tag(sample)

    assert retyped.metadata == {
        "dataset_type": "MULTIPLE_CHOICE",
        "dataset_name": "date_understanding",
    }
    assert (retyped.id, retyped.input, retyped.choices, retyped.target) == (
        sample.id,
        sample.input,
        sample.choices,
        sample.target,
    )


def test_a_tag_that_is_not_upstreams_enum_is_refused() -> None:
    """A changed upstream (a string tag, a new kind) would be marked by the fall-through
    exact-match scorer without a word; refusing it makes the change loud at import."""

    sample = Sample(input="q", target="a", metadata={"dataset_type": "MULTIPLE_CHOICE"})

    with pytest.raises(ValueError, match="not upstream's enum"):
        _with_text_tag(sample)


def _sent(solver: Any, state: TaskState) -> list[str]:
    """The messages a solver hands the model for one state."""

    sent: list[list[str]] = []

    async def record(state: TaskState, *_args: Any, **_kwargs: Any) -> TaskState:
        sent.append([str(message.content) for message in state.messages])
        state.output = ModelOutput.from_content(model=_MODEL, content="ANSWER: A")
        return state

    asyncio.run(solver(state, record))
    return sent[0]


@pytest.mark.parametrize(
    ("kind", "sample_input"),
    [
        ("BINARY_CHOICE", "not ( True ) and ( True ) is"),
        ("EXACT_MATCH", "I have a car, and a toaster. How many objects do I have?"),
        ("DYCK", "Complete the rest of the sequence. Input: [ ["),
    ],
)
def test_a_free_form_or_yes_no_question_is_sent_as_upstream_sends_it(
    kind: str, sample_input: str
) -> None:
    """Upstream's solver (enum tag) and ours (text tag) hand the model the same messages for
    every subset that is not multiple choice: its prompt already lets the model reason."""

    theirs: list[str] = _sent(
        upstream_solver(), _tagged(_state(sample_input, kind), DatasetType[kind])
    )
    ours: list[str] = _sent(bbh_solver(), _tagged(_state(sample_input, kind), kind))

    assert ours == theirs


def test_a_multiple_choice_question_asks_the_model_to_think_step_by_step() -> None:
    """NAMED DEVIATION 1 pinned: the options are listed as upstream lists them, but under the
    instruction to reason first. Upstream's instruction, "The entire content of your response
    should be ... 'ANSWER: $LETTER'", contradicts its own chain-of-thought examples."""

    sample_input: str = "Tomorrow is 11/12/2019. What is the date yesterday?\nOPTIONS:"
    choices: list[str] = ["11/10/2076", "11/10/2019", "09/10/2019"]

    theirs: str = _sent(
        upstream_solver(),
        _tagged(
            _state(sample_input, "MULTIPLE_CHOICE", choices=choices), DatasetType.MULTIPLE_CHOICE
        ),
    )[-1]
    ours: str = _sent(
        bbh_solver(),
        _tagged(_state(sample_input, "MULTIPLE_CHOICE", choices=choices), "MULTIPLE_CHOICE"),
    )[-1]

    assert "The entire content of your response" in theirs
    assert "The entire content of your response" not in ours
    assert "Think step by step before answering." in ours
    # Same question, same options, same letters: only the instruction differs.
    assert ours.split("\n\n", 1)[1] == theirs.split("\n\n", 1)[1]


def _scored(scorer: Any, kind: str, tag: object, target: str, reply: str) -> object:
    """One scorer's value for one reply, the tag in the form that scorer expects."""

    state: TaskState = _tagged(_state("q", kind), tag)
    state.output = ModelOutput.from_content(model=_MODEL, content=reply)
    return asyncio.run(scorer(state, Target(target))).value


@pytest.mark.parametrize(
    ("target", "reply"),
    [
        ("False", "not True is False, and False and True is False.\nANSWER: False"),
        ("False", "ANSWER: True"),
        ("no", "Adam Thielen is a football player.\nANSWER: No"),
    ],
)
def test_a_yes_no_answer_is_marked_as_upstream_marks_it(target: str, reply: str) -> None:
    """The yes/no subsets keep upstream's rule, the word after ANSWER:, right or wrong."""

    assert _scored(bbh_scorer(), "BINARY_CHOICE", "BINARY_CHOICE", target, reply) == _scored(
        upstream_scorer(), "BINARY_CHOICE", DatasetType.BINARY_CHOICE, target, reply
    )


@pytest.mark.parametrize(
    ("kind", "target", "reply"),
    [
        # Dyck: upstream's key trims to "answer", so any reply ending in that word passes.
        ("DYCK", "ANSWER: ] ]", "ANSWER: ]"),
        ("DYCK", "ANSWER: ] ]", "ANSWER: ] ] ]"),
        ("DYCK", "ANSWER: ] ]", "I do not know the answer."),
        # multistep arithmetic: the minus sign trims off, and "ends with" accepts a longer number.
        ("EXACT_MATCH", "-25", "ANSWER: 25"),
        ("EXACT_MATCH", "25", "ANSWER: -25"),
        ("EXACT_MATCH", "25", "ANSWER: 125"),
        # object counting and word sorting: "ends with" accepts extra digits or words in front.
        ("EXACT_MATCH", "2", "ANSWER: 12"),
        ("EXACT_MATCH", "beth kenya", "ANSWER: elizabeth kenya"),
    ],
)
def test_a_wrong_free_form_answer_upstream_passes_is_marked_wrong(
    kind: str, target: str, reply: str
) -> None:
    """NAMED DEVIATION 2 pinned: each reply is wrong by the paper's exact match. Upstream's
    match(location="end") marks it right (asserted, so a fixed upstream shows up here); ours
    marks it wrong."""

    assert _scored(upstream_scorer(), kind, DatasetType[kind], target, reply) == CORRECT
    assert _scored(bbh_scorer(), kind, kind, target, reply) == INCORRECT


@pytest.mark.parametrize(
    ("kind", "target", "reply"),
    [
        ("DYCK", "ANSWER: ] ]", "Close both brackets.\nANSWER: ] ]"),
        ("EXACT_MATCH", "-25", "So the answer is -25.\nANSWER: -25"),
        ("EXACT_MATCH", "2", "A car and a toaster.\nANSWER: 2"),
        ("EXACT_MATCH", "beth kenya", "b comes before k.\nANSWER: beth kenya"),
    ],
)
def test_a_right_free_form_answer_is_marked_right_by_both(
    kind: str, target: str, reply: str
) -> None:
    """The strict rule takes nothing away from a reply upstream's prompt asks for."""

    assert _scored(bbh_scorer(), kind, kind, target, reply) == CORRECT
    assert _scored(upstream_scorer(), kind, DatasetType[kind], target, reply) == CORRECT


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        # The last ANSWER: line wins over earlier ones and over "the answer is".
        ("ANSWER: 3\nNo, wait.\nSo the answer is 4.\nANSWER: 4", "4"),
        # No ANSWER: line: the paper's keyword, one trailing period dropped.
        ('So, we need "]", "]". So the answer is ] ].', "] ]"),
        # Only the committing line is read, never what follows it.
        ("ANSWER: 7\nThat is seven objects.", "7"),
        # The label is found ignoring case, and emphasis around the answer is trimmed: inspect's
        # multiple-choice parser reads these forms too.
        ("Answer: 25", "25"),
        ("**ANSWER: -25**.", "-25"),
        ("**ANSWER:** `] ]`", "] ]"),
        # A label that ends its line: the answer is the next non-empty line.
        ("ANSWER:\n\n-25", "-25"),
        # Case is kept inside the answer: the paper compares the exact string.
        ("ANSWER: Beth kenya", "Beth kenya"),
        # Neither keyword: the whole reply, stripped.
        ("  ] ]  ", "] ]"),
    ],
)
def test_the_final_answer_is_read_from_the_committing_line(reply: str, expected: str) -> None:
    assert final_answer(reply) == expected


def test_a_tag_the_scorer_does_not_know_is_refused() -> None:
    """Upstream falls through to its last rule for any tag; ours names its four kinds and
    refuses a fifth, so a new upstream kind is never marked by a rule nobody chose for it."""

    with pytest.raises(ValueError, match="not one of upstream's four kinds"):
        _scored(bbh_scorer(), "NEW_KIND", "NEW_KIND", "x", "ANSWER: x")


#: The authors' Codex (code-davinci-002) chain-of-thought replies for the four free-form subsets,
#: from github.com/suzgunmirac/BIG-Bench-Hard at 9ee07bd (MIT), each cut to its answer line.
_CODEX_REPLIES: Path = Path(__file__).parents[1] / "data" / "bbh_codex_cot_free_form_replies.json"


def _codex_subsets() -> dict[str, Any]:
    subsets: dict[str, Any] = json.loads(_CODEX_REPLIES.read_text(encoding="utf-8"))["subsets"]
    return subsets


@pytest.mark.parametrize("subset", sorted(_codex_subsets()))
def test_the_rule_reproduces_the_papers_accuracy_on_the_authors_codex_replies(subset: str) -> None:
    """NAMED DEVIATION 2's evidence: the authors publish no grading code, only Codex's replies
    and their accuracy per subset. Our rule must give exactly those numbers (Dyck 56.8,
    multistep 47.6, object counting 93.2, word sorting 40.4).

    The replies carry no ANSWER: line (the paper's prompts have none), so this pins the
    fallback to the paper's own keyword. Each key is given in the form a real Case stores it:
    the authors' key, with upstream's `ANSWER: ` prefix on Dyck. (Upstream's own rule is not
    compared here: it reads replies in its ANSWER: format, which these are not; its holes are
    pinned by the wrong-answer test above.)"""

    data: dict[str, Any] = _codex_subsets()[subset]
    replies: list[list[str]] = data["replies"]
    dyck: bool = subset == "dyck_languages"
    kind: str = "DYCK" if dyck else "EXACT_MATCH"

    ours: int = sum(
        _scored(bbh_scorer(), kind, kind, f"ANSWER: {key}" if dyck else key, reply) == CORRECT
        for reply, key in replies
    )

    assert len(replies) == 250
    assert round(100 * ours / len(replies), 1) == data["reported_accuracy"]


#: Real BBH questions, one or two per answer kind, as Case Preparation writes them (the
#: 3-shot prompt is cut from `input` to keep the file short; grading never reads it). WHY real:
#: the targets carry upstream's exact casing and spacing, which is what the marking reads.
_REAL_CASES: list[PreparedCase] = [
    {
        "case": {
            "id": 1,
            "case_id": "1",
            "input": "QUESTION: Tomorrow is 11/12/2019. What is the date yesterday in MM/DD/YYYY?",
        },
        "grading_material": {
            "target": "B",
            "choices": [
                "11/10/2076",
                "11/10/2019",
                "09/10/2019",
                "11/06/2019",
                "11/11/2019",
                "11/17/2019",
            ],
            "metadata": {"dataset_type": "MULTIPLE_CHOICE", "dataset_name": "date_understanding"},
        },
    },
    {
        "case": {"id": 2, "case_id": "2", "input": "QUESTION: not ( True ) and ( True ) is"},
        "grading_material": {
            "target": "False",
            "metadata": {"dataset_type": "BINARY_CHOICE", "dataset_name": "boolean_expressions"},
        },
    },
    {
        "case": {
            "id": 3,
            "case_id": "3",
            "input": 'QUESTION: Is the following sentence plausible? "Adam Thielen got on base."',
        },
        "grading_material": {
            "target": "no",
            "metadata": {"dataset_type": "BINARY_CHOICE", "dataset_name": "sports_understanding"},
        },
    },
    {
        "case": {
            "id": 4,
            "case_id": "4",
            "input": "QUESTION: I have a car, and a toaster. How many objects do I have?",
        },
        "grading_material": {
            "target": "2",
            "metadata": {"dataset_type": "EXACT_MATCH", "dataset_name": "object_counting"},
        },
    },
    {
        "case": {
            "id": 5,
            "case_id": "5",
            "input": "QUESTION: Sort the following words alphabetically: List: kenya beth",
        },
        "grading_material": {
            "target": "beth kenya",
            "metadata": {"dataset_type": "EXACT_MATCH", "dataset_name": "word_sorting"},
        },
    },
    {
        "case": {
            "id": 6,
            "case_id": "6",
            "input": "QUESTION: Complete the rest of the sequence, making sure that the "
            "parentheses are closed properly. Input: [ [",
        },
        "grading_material": {
            "target": "ANSWER: ] ]",
            "metadata": {"dataset_type": "DYCK", "dataset_name": "dyck_languages"},
        },
    },
]


@pytest.mark.asyncio
async def test_real_questions_of_every_kind_grade_right_and_wrong_with_no_network(
    tmp_path: Path, no_network: None
) -> None:
    """Through the production aggregate route: a right reply scores 1 and a wrong one 0 for
    each answer kind, with outbound network blocked."""

    benchmark = imported_benchmark("bbh")
    node = _node(benchmark, _REAL_CASES, tmp_path)

    right: list[str] = [
        "Yesterday was 11/10/2019.\nANSWER: B",
        "not True is False.\nANSWER: False",
        "Adam Thielen plays football.\nANSWER: no",
        "ANSWER: 2",
        "ANSWER: beth kenya",
        "ANSWER: ] ]",
    ]
    wrong: list[str] = [
        "ANSWER: A",
        "ANSWER: True",
        "ANSWER: yes",
        "ANSWER: 3",
        "ANSWER: kenya beth",
        "ANSWER: ]",
    ]

    assert await _scores(node, benchmark, right) == [1.0] * 6
    assert await _scores(node, benchmark, wrong) == [0.0] * 6


def test_the_row_serves_6508_cases_with_no_judge() -> None:
    benchmark = imported_benchmark("bbh")
    spec = TASK_REPLAY_CASES["bbh"]

    assert benchmark.benchmark.case_count == 6508
    assert benchmark.judge is None
    # "Monsters, Inc": its key matches none of its options, in the authors' own data.
    assert spec.excluded_sample_ids == ("movie_recommendation_164",)
    # The subset name rides each Case, so per-task accuracies can be regrouped.
    assert spec.keep_sample_metadata is True
