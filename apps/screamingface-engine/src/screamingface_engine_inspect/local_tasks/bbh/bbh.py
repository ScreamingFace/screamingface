# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai,
# inspect_evals), absent in the default (extra-less) install the typecheck gate runs against;
# it is loaded only behind `inspect_available()`, like every other module in this package.
"""BIG-Bench Hard as a LOCAL inspect Task: upstream's exam, asked and marked the paper's way.

Think of it as inspect_evals' own exam with three things changed on the answer sheet. The
questions, the 3-shot worked examples and the dataset pin are upstream's. What changes:

    - the label on each question saying which kind of answer it expects, `dataset_type`, is
      written as text (`"MULTIPLE_CHOICE"`) instead of a Python enum. Case Preparation seals
      Sample metadata as JSON, an enum is not JSON, and the importer refuses upstream's Task.
    - the multiple-choice instruction asks the model to think step by step (NAMED DEVIATION 1).
    - the free-form answers are marked by exact match, as the paper marks them (NAMED
      DEVIATION 2).

Execution order, as the importer and the Engine see it:

    1. `bbh()` builds upstream's own Task in the chain-of-thought setting: upstream's loader
       fetches all 23 tasks (27 subsets: two tasks come in three sizes each) and the 3-shot
       prompts from the pinned Hub revision, writes each question's prompt and drops the two
       broken `ruin_names` questions, so the 6,509 questions and their worked examples are
       upstream's own. (The row leaves out one more, by id: see its declaration in
       `prepare.py`.)
    2. each Sample's tag is rewritten to its enum name; nothing else in the Sample changes.
    3. `bbh_solver` asks: inspect's `multiple_choice(cot=True)` for the 17 multiple-choice
       subsets (it lists the options as A) B) ... under an instruction to think step by step),
       `generate()` for the rest, as upstream.
    4. `bbh_scorer` marks: `choice()` for multiple choice and `answer(pattern="word")` (the
       word after `ANSWER:`) for the 6 yes/no-style subsets, as upstream; `exact_answer_score`
       for the 4 free-form subsets (Dyck languages, multistep arithmetic, object counting,
       word sorting).

NAMED DEVIATION 1 — the multiple-choice instruction. Upstream wraps each multiple-choice question
in inspect's default template, whose first line reads "The entire content of your response
should be of the following format: 'ANSWER: $LETTER'". The worked examples under it reason
step by step, and the paper ends each question with "Let's think step by step." A model that
obeys the first line answers without reasoning: the paper's answer-only setting, not its
chain-of-thought one. `cot=True` is inspect's own template that agrees with the examples: "The
last line of your response should be ... Think step by step before answering." 4,071 of the
6,508 Cases are multiple choice.

NAMED DEVIATION 2 — free-form marking. Upstream marks these with `match(location="end")`: it
lowercases, trims punctuation off both ends, then asks whether the reply ENDS WITH the key.
That gives free points on all 750 free-form Cases:

    - Dyck languages: the key `ANSWER: ] ]` trims to `answer`, so "I do not know the answer."
      is correct;
    - multistep arithmetic: the key `-25` trims to `25`, so `ANSWER: 25` is correct, and so is
      `ANSWER: 125` (it ends with 25);
    - object counting: `ANSWER: 12` is correct for the key `2`;
    - word sorting: `ANSWER: elizabeth kenya` is correct for the key `beth kenya`.

The paper (https://arxiv.org/abs/2210.09261, §3 "Evaluation protocol") extracts the final
answer after "the answer is" and grades by exact match. Its authors publish no grading code,
but they publish Codex's replies with their accuracy per subset
(https://github.com/suzgunmirac/BIG-Bench-Hard/tree/9ee07bd481feebf959a6b59d61ea57bdcf30964d,
`code-davinci-002-outputs/`). `exact_answer_score` reproduces those numbers on all four
subsets; upstream's rule gives Dyck 100.0 where the authors report 56.8.

Worked example: an `object_counting` question with the key `2`. The reply "A car and a
toaster.\\nANSWER: 2" reads `2` after `ANSWER:` and is correct; "ANSWER: 12" reads `12` and is
wrong (upstream marks it correct). A Dyck reply "So the answer is ] ]." with no `ANSWER:` line
falls back to the paper's keyword, reads `] ]` once the trailing period is dropped, and
matches the key `ANSWER: ] ]` with upstream's `ANSWER: ` prefix removed.

The run score is the plain mean over Cases (chosen at import, OME-1696). Upstream scores the
run with `grouped(accuracy(), "dataset_name")`: one accuracy per subset beside an overall
`all`, which equals that mean. The paper's headline is the unweighted mean over the 23 tasks;
on the authors' Codex replies the two differ by under 0.1 point (73.97 against 73.9). Each Case
keeps its subset name, so both can be regrouped from a full run.

INVARIANT: the tag names, the instruction and the marking are Benchmark identity. The names
and the instruction ride the Case Digest; the marking is this file, inside the local Task's
source pin.

References:
    - Paper: https://arxiv.org/abs/2210.09261
    - Authors' data, prompts and Codex replies:
      https://github.com/suzgunmirac/BIG-Bench-Hard/tree/9ee07bd481feebf959a6b59d61ea57bdcf30964d
    - Upstream Task: inspect_evals.bbh.bbh:bbh
      (https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/bbh)
    - Case Source: https://huggingface.co/datasets/Joschka/big_bench_hard
"""

from __future__ import annotations

from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Scorer,
    Target,
    accuracy,
    answer,
    choice,
    grouped,
    scorer,
    stderr,
)
from inspect_ai.solver import Generate, Solver, TaskState, generate, multiple_choice, solver
from inspect_evals.bbh.bbh import DatasetType
from inspect_evals.bbh.bbh import bbh as upstream_bbh

#: The prompt setting the paper's headline numbers use: 3-shot chain of thought.
PROMPT_TYPE = "chain_of_thought"

#: The tag values, upstream's `DatasetType` member names.
MULTIPLE_CHOICE = DatasetType.MULTIPLE_CHOICE.name
BINARY_CHOICE = DatasetType.BINARY_CHOICE.name

#: The line upstream's prompts ask the model to end on, and the prefix upstream's Dyck converter
#: puts on every Dyck key (`ANSWER: ] ]`).
ANSWER_LABEL = "ANSWER:"
#: The paper's answer keyword (§3), read when a reply has no `ANSWER:` line. The worked
#: examples write both, "So the answer is ] ]." and then "ANSWER: ] ]".
PAPER_KEYWORD = "the answer is "


def _with_text_tag(sample: Sample) -> Sample:
    """One upstream Sample with its answer-kind tag rewritten from the enum to its name."""

    metadata: dict[str, object] = dict(sample.metadata or {})
    # WHY Any: in the extra-less typecheck install DatasetType is unresolved, so isinstance
    # cannot narrow an `object` to it.
    tag: Any = metadata["dataset_type"]
    # WHY refuse: every upstream converter sets the enum, so anything else is a changed
    # upstream, and the dispatch below would mark it with the wrong scorer.
    if not isinstance(tag, DatasetType):
        raise ValueError(f"sample {sample.id}: dataset_type is {tag!r}, not upstream's enum")
    metadata["dataset_type"] = tag.name
    return sample.model_copy(update={"metadata": metadata})


def final_answer(reply: str) -> str:
    """The reply's final answer, read the paper's way: the rest of the committing line.

    The committing line is the last `ANSWER:` line, else the last "the answer is". Surrounding
    spaces and one trailing period are dropped; nothing else is normalised, because the paper
    compares the exact string. A reply with neither keeps its whole (stripped) text, so it
    matches only a key it equals.
    """

    for keyword in (ANSWER_LABEL, PAPER_KEYWORD):
        index: int = reply.rfind(keyword)
        if index >= 0:
            reply = reply[index + len(keyword) :].split("\n", 1)[0]
            break
    text: str = reply.strip()
    return text[:-1] if text.endswith(".") else text


async def exact_answer_score(state: TaskState, target: Target) -> Score:
    """Exact match of the final answer against the key, case included, as the paper grades."""

    given: str = final_answer(state.output.completion)
    # WHY removeprefix: upstream's Dyck converter stores its key as `ANSWER: ] ]`; the other
    # free-form keys carry no prefix, so this leaves them as they are.
    key: str = target.text.removeprefix(f"{ANSWER_LABEL} ")
    return Score(value=CORRECT if given == key else INCORRECT, answer=given)


@solver
def bbh_solver() -> Solver:
    """Ask: options plus a think-step-by-step instruction for multiple choice, else generate."""

    # NAMED DEVIATION 1: upstream calls multiple_choice() with inspect's answer-only template.
    multiple_choice_solve: Solver = multiple_choice(cot=True)
    generate_solve: Solver = generate()

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.metadata["dataset_type"] == MULTIPLE_CHOICE:
            return await multiple_choice_solve(state, generate)
        return await generate_solve(state, generate)

    return solve


@scorer(metrics=[grouped(accuracy(), "dataset_name"), stderr()])
def bbh_scorer() -> Scorer:
    """Mark: the chosen letter, the word after ANSWER:, or an exact match of the final answer."""

    choice_score: Scorer = choice()
    answer_score: Scorer = answer(pattern="word")

    async def score(state: TaskState, target: Target) -> Score | None:
        dataset_type: object = state.metadata["dataset_type"]
        if dataset_type == MULTIPLE_CHOICE:
            return await choice_score(state, target)
        if dataset_type == BINARY_CHOICE:
            return await answer_score(state, target)
        # NAMED DEVIATION 2: upstream calls match(location="end") here (EXACT_MATCH and DYCK).
        return await exact_answer_score(state, target)

    return score


@task
def bbh() -> Task:
    """BIG-Bench Hard: all 23 tasks, upstream's 6,509 questions, 3-shot chain-of-thought."""

    source: Task = upstream_bbh(prompt_type=PROMPT_TYPE)
    dataset = MemoryDataset(
        samples=[_with_text_tag(sample) for sample in source.dataset],
        name=source.dataset.name,
        location=source.dataset.location,
    )
    return Task(
        dataset=dataset,
        solver=bbh_solver(),
        scorer=bbh_scorer(),
        config=source.config,
    )
