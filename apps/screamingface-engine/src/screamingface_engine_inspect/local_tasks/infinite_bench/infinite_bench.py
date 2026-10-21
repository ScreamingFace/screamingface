# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai,
# inspect_evals), absent in the default (extra-less) install the typecheck gate runs against;
# it is loaded only behind `inspect_available()`, like every other module in this package.
"""InfiniteBench Math.Find as a LOCAL inspect Task, cut once for every model (OME-1602).

Think of it as inspect_evals' own exam with one sheet of the rules rewritten. Upstream's Task
asks which model is sitting the exam before it prints the question: its truncation solver calls
`get_model()` and cuts each long input to that model's context window. Task replay runs with
the model named `none`, so the Cases it sealed would be cut for a model that does not exist,
and the importer refuses that shape by name (F3). Here the cut is fixed: every input is cut to
the same 128k-token budget, whoever answers, so the Cases are the same for every Candidate.

Execution order, as the importer and the Engine see it:

    1. `infinite_bench_math_find()` loads the pinned `math_find.jsonl` through upstream's own
       loader pieces (dataset id, revision, features, `record_to_sample_math_find`), so the
       question text is exactly upstream's.
    2. the solver chain is upstream's, in upstream's order, except the cut: the system message,
       then `fixed_cut_solver` (this module) in place of `truncate_input_solver`, then the
       prompt template, then `generate()`.
    3. `fixed_cut` keeps the first and last halves of `MAX_CHARS` characters and joins them
       with `...` at the nearest whitespace or symbol, exactly as upstream's `truncate_raw_text`
       does for a model it has no tokenizer for. Worked example: a 600,000-character input
       keeps its first 223,125 and last 223,125 characters (`MAX_CHARS` = 446,250), each
       trimmed back to a boundary, with `...` between them.
    4. `math_find_scorer` grades: the FIRST number in the reply, compared with the answer by
       value, the official InfiniteBench rule (NAMED DEVIATION 2).

NAMED DEVIATION 1: inspect_evals cuts per model (tiktoken for a `gpt*` name, a character estimate
otherwise, with a 128k default and 200k for the Claude 3 models in its table). This Task always
uses the character estimate at 128k tokens, the budget inspect_evals gives every model outside
its table. In practice no Math.Find input reaches it: the longest is 120,155 characters (mean
118,028; measured at import, 2026-10-16), so every Case is inspect_evals' whole input. The fixed
cut is what makes that a guarantee, whoever answers, instead of a property of today's data.

NAMED DEVIATION 2: inspect_evals grades with inspect's `exact()`, which needs the WHOLE reply to
equal the answer, so "The largest number in the list is: 91" is wrong for the answer 91. The
official scorer (`get_score_one_math_find`,
https://github.com/OpenBMB/InfiniteBench/blob/51d9b37b0f1790ead936df2243abbf7f0420e439/src/compute_scores.py#L222-L241)
reads the first number in the reply with the unsigned pattern `\\d+\\.\\d+|\\d+` and compares it by
value. Adopted from inspect_evals PR #2346 (open; issue #2343;
https://github.com/UKGovernmentBEIS/inspect_evals/pull/2346), which found `exact()` up to 19.4
points below the official scores on InfiniteBench's published prediction files. Both sides are
compared as floats, as that PR does: our answer column is text, and every answer is a whole
number from 0 to 99. Worked example, answer 91: "The largest is 91." reads 91, right; "Between
90 and 91, 91." reads 90, wrong (the first number counts); "-91" reads 91, right, since the
official pattern carries no sign and no answer is negative.

INVARIANT: `MAX_TOKENS`, `TOKEN_BUFFER`, `TOKEN_TO_CHAR_RATIO` and the cut itself are Benchmark
identity: they sit inside the Case Digest, so an edit is a new Benchmark, not a tweak. The
grading rule is this file's source, hashed into the revision as the local Task's source pin.

References:
    - Paper: https://arxiv.org/abs/2402.13718
    - Upstream Task: inspect_evals.infinite_bench.infinite_bench:infinite_bench_math_find
    - Case Source: https://huggingface.co/datasets/xinrongzhang2022/InfiniteBench
"""

from __future__ import annotations

import re

from inspect_ai import Task, task
from inspect_ai.model import ChatMessageUser
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, accuracy, scorer, stderr
from inspect_ai.solver import Generate, Solver, TaskState, generate, prompt_template, solver
from inspect_ai.solver import system_message as system_message_solver
from inspect_evals.infinite_bench.constants import TASK_METADATA, ft
from inspect_evals.infinite_bench.infinite_bench import (
    DATASET_PATH,
    INFINITE_BENCH_DATASET_REVISION,
    record_to_sample_math_find,
)
from inspect_evals.infinite_bench.truncate_input import find_nearest_boundary
from inspect_evals.infinite_bench.utils import create_system_msg
from inspect_evals.utils.huggingface import hf_dataset

TASK_NAME = "math_find"

# ── the cut: upstream's character estimate at its default budget ──────────────────────
#: The token budget upstream gives a model missing from its context-size table.
MAX_TOKENS = 128 * 1000
#: Upstream's safety margin under the window (`constants.TOKEN_BUFFER`).
TOKEN_BUFFER = 500
#: Upstream's characters-per-token estimate (`constants.TOKEN_TO_CHAR_RATIO`).
TOKEN_TO_CHAR_RATIO = 3.5
#: The longest input a Case keeps: int((128,000 - 500) * 3.5) = 446,250 characters.
MAX_CHARS = int((MAX_TOKENS - TOKEN_BUFFER) * TOKEN_TO_CHAR_RATIO)


def fixed_cut(text: str) -> str:
    """Cut one over-long input to `MAX_CHARS`, keeping its start and end, as upstream does.

    WHY a copy of upstream's `truncate_raw_text` body and not a call: upstream's reads the
    budget from a model name, and this Task must never name one. Copied from
    https://github.com/UKGovernmentBEIS/inspect_evals/blob/360484a06383f9260279938262d78ed646ddbca1/src/inspect_evals/infinite_bench/truncate_input.py
    (v0.20.0, the pinned version).
    """

    if len(text) <= MAX_CHARS:
        return text
    half: int = MAX_CHARS // 2
    kept: str = text[:half] + text[-half:]
    left: int = find_nearest_boundary(kept, half, "left")
    right: int = find_nearest_boundary(kept, half, "right")
    return kept[:left].rstrip() + "..." + kept[right:].lstrip()


@solver
def fixed_cut_solver() -> Solver:
    """Cut the last user message to the fixed budget; upstream's solver, minus `get_model()`."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for index in range(len(state.messages) - 1, -1, -1):
            message = state.messages[index]
            if isinstance(message, ChatMessageUser):
                if isinstance(message.content, str):
                    state.messages[index] = ChatMessageUser(content=fixed_cut(message.content))
                break
        return state

    return solve


# ── the marking: the official first-number rule ────────────────────────────────────────
#: The official pattern, copied as is: a decimal before an integer (alternation takes the first
#: branch that fits, so "3.5" must not match as "3"), and no sign.
FIRST_NUMBER: re.Pattern[str] = re.compile(r"\d+\.\d+|\d+")


def first_number(reply: str) -> str | None:
    """The first unsigned integer or decimal in the reply, or None when it has no digit."""

    found: re.Match[str] | None = FIRST_NUMBER.search(reply)
    return found.group(0) if found else None


@scorer(metrics=[accuracy(), stderr()])
def math_find_scorer() -> Scorer:
    """Right when the reply's first number equals the answer by value (NAMED DEVIATION 2)."""

    async def score(state: TaskState, target: Target) -> Score:
        given: str | None = first_number(state.output.completion)
        if given is None:
            # WHY the reason: a reply with no number is a format failure, per inspect_evals' fix.
            return Score(value=INCORRECT, reason="invalid_response_format")
        right: bool = float(given) == float(target.text)
        return Score(value=CORRECT if right else INCORRECT, answer=given)

    return score


@task
def infinite_bench_math_find() -> Task:
    """InfiniteBench Math.Find: find one of seven key numbers in a very long list."""

    dataset = hf_dataset(
        path=DATASET_PATH,
        name="default",
        data_files={TASK_NAME: TASK_METADATA[TASK_NAME]["data_file"]},
        split=TASK_NAME,
        features=ft,
        sample_fields=record_to_sample_math_find,
        revision=INFINITE_BENCH_DATASET_REVISION,
    )
    return Task(
        dataset=dataset,
        solver=[
            system_message_solver(create_system_msg(TASK_NAME)),
            fixed_cut_solver(),
            prompt_template(TASK_METADATA[TASK_NAME]["prompt_template"]),
            generate(),
        ],
        scorer=math_find_scorer(),
    )
