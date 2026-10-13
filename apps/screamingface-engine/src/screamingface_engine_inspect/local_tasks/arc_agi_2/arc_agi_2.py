# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai), absent in the
# default (extra-less) install the typecheck gate runs against; it is loaded only behind
# `inspect_available()`, like every other module in this package.
"""ARC-AGI-2 public eval as a LOCAL inspect Task — the ARC Prize harness's exam (OME-1476).

FEATURE: ARC-AGI-2 as a Benchmark. Think of it as a puzzle exam marked by two examiners with the
same answer key: the ARC Prize harness (arcprize/arc-agi-benchmarking) and us. A task shows a few
example pairs of coloured grids (lists of rows of the digits 0-9, up to 30x30) and asks for the
output grid of one or more test inputs. We ask exactly the harness's question, read the reply
with the harness's own parser, and add up the marks with the harness's arithmetic.

Execution order, as the importer and the Engine see it:

    1. ``arc_agi_2()`` → ``load_arc_agi_2_eval()``: download GitHub's zip of the data repo at
       commit f3283f72 through ``inspect_ai.util.download``, which refuses a wrong sha256 (the
       importer's Case Source recorder wraps that call, so the pin lands in the provenance).
    2. ``samples_from_zip``: the 120 public-eval tasks, sorted by task id, become 167 Samples —
       one per TEST GRID (spec D1), each with the harness's prompt as ``input``, the answer grid
       as ``target`` and ``task_id`` / ``grids_in_task`` as metadata. Counts are refused if off.
    3. the importer seals the Cases; ``epochs=Epochs(2, "max")`` becomes ``attempts=2`` with
       the ``max`` reducer: the Engine asks each Case twice and the Case is solved if either
       Attempt is (spec D2).
    4. at grading, ``arc_exact_match`` reads each Attempt's reply with the vendored parser and
       scores 1.0 only on the exact grid; a reply with no grid scores 0.0 (spec D5).
    5. the whole-run tally calls ``arc_per_task_accuracy`` over each Case's reduced Score: the
       Headline Score averages TASKS, each scoring grids solved / grids in the task (D3, D7).

Worked example (two-grid task ``t2``, one-grid task ``t9``): t2's grid 0 is solved by Attempt 2,
grid 1 by neither; t9's grid is solved. Task scores: t2 = 1 / 2 = 0.5, t9 = 1 / 1 = 1.0, so the
headline is (0.5 + 1.0) / 2 = 0.75 — a per-grid mean would say 2 / 3 = 0.667.

INVARIANT: ``PROMPT_TEMPLATE`` and ``build_prompt`` are Benchmark identity (they sit inside the
Case Digest). They restate the harness's ``system_prompt.txt`` and ``convert_task_pairs_to_prompt``
at arcprize/arc-agi-benchmarking@9e2828fb; ``tests/unit/inspect/test_local_task_arc_agi_2.py``
pins the template's sha256 to the upstream file's and a fixture prompt to the upstream builder's
output. WHY restated, not copied: the template file ends with no newline and the builder has a
whitespace-only line, which the repo's whitespace hooks would rewrite (see ``vendor/__init__``).

INVARIANT: ``arc_per_task_accuracy`` RESTATES the harness's scoring arithmetic
(``scoring/scoring.py:122-127`` per task, ``:160-234`` across tasks); it is not a copy, so the
conservation test computes that arithmetic independently and demands the same number.

References:
    - Paper: https://arxiv.org/abs/2505.11831
    - Reference harness: https://github.com/arcprize/arc-agi-benchmarking
    - Case Source: https://github.com/arcprize/ARC-AGI-2 (Apache-2.0)
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from inspect_ai import Epochs, Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import (
    Metric,
    SampleScore,
    Score,
    Scorer,
    Target,
    accuracy,
    metric,
    scorer,
)
from inspect_ai.solver import TaskState, generate

from screamingface_engine_inspect.local_tasks.arc_agi_2.vendor.parsing import (
    parse_and_validate_json,
)

# ── pins ─────────────────────────────────────────────────────────────────────────────────
DATA_COMMIT = "f3283f727488ad98fe575ea6a5ac981e4a188e49"
ZIP_URL = f"https://codeload.github.com/arcprize/ARC-AGI-2/zip/{DATA_COMMIT}"
#: GitHub's archive of the repo at DATA_COMMIT; byte-identical across downloads on 2026-10-12.
ZIP_SHA256 = "c3f9f6975d8432133419fd0e1677c42289666517af4e6f83d8a291690e14d49f"
EVAL_DIR = f"ARC-AGI-2-{DATA_COMMIT}/data/evaluation"
#: The public evaluation set at DATA_COMMIT: 75 tasks with one test grid, 43 with two, 2 with three.
EXPECTED_TASKS = 120
EXPECTED_GRIDS = 167
#: Two any-match Attempts per test grid: the harness's ``--num_attempts`` default.
ATTEMPTS = 2

# ── the prompt: arcprize/arc-agi-benchmarking@9e2828fb, prompts/system_prompt.txt ───────
PROMPT_TEMPLATE = (
    "You are participating in a puzzle solving competition. You are an expert at solving puzzles.\n"
    "\n"
    "Below is a list of input and output pairs with a pattern. Your goal is to identify the "
    "pattern or transformation in the training examples that maps the input to the output, then "
    "apply that pattern to the test input to give a final output.\n"
    "\n"
    "Respond in the format of the training output examples\n"
    "\n"
    "--Training Examples--\n"
    "{training_examples}\n"
    "--End of Training Examples--\n"
    "\n"
    "--Test Input--\n"
    "{test_input}\n"
    "--End of Test Input--\n"
    "\n"
    "Your response:"
)

Grid = list[list[int]]


def build_prompt(train: Sequence[dict[str, Any]], test_input: Grid) -> str:
    """The harness's ``convert_task_pairs_to_prompt``, restated: every example pair, then the
    test input, each grid written with ``json.dumps``' default separators."""

    # WHY the odd spacing ("-- \n\n INPUT: \n\n"): it is upstream's, and the prompt is identity.
    training_examples: str = ""
    for index, pair in enumerate(train):
        training_examples += f"--Example {index}-- \n\n INPUT: \n\n"
        training_examples += json.dumps(pair["input"]) + "\n\n"
        training_examples += "OUTPUT: \n\n"
        training_examples += json.dumps(pair["output"]) + "\n\n"
    return PROMPT_TEMPLATE.format(
        training_examples=training_examples, test_input=json.dumps(test_input)
    )


# ── dataset loader ───────────────────────────────────────────────────────────────────────
def task_to_samples(task_id: str, arc_task: dict[str, Any]) -> list[Sample]:
    """One ARC task → one Sample per test grid (spec D1), in the task's own grid order."""

    grids: list[dict[str, Any]] = list(arc_task["test"])
    return [
        Sample(
            id=f"{task_id}_{index}",
            input=build_prompt(arc_task["train"], grid["input"]),
            target=json.dumps(grid["output"]),
            # WHY metadata: the per-task metric groups Cases by task_id and divides by
            # grids_in_task, so a grid whose Attempts all failed still counts 0 (spec D7).
            metadata={"task_id": task_id, "test_index": index, "grids_in_task": len(grids)},
        )
        for index, grid in enumerate(grids)
    ]


def samples_from_zip(path: Path, *, expected_tasks: int, expected_grids: int) -> list[Sample]:
    """The public-eval tasks in the zip, sorted by task id, as Samples; refuses wrong counts."""

    prefix: str = f"{EVAL_DIR}/"
    samples: list[Sample] = []
    with zipfile.ZipFile(path) as archive:
        names: list[str] = sorted(
            name
            for name in archive.namelist()
            if name.startswith(prefix) and name.endswith(".json")
        )
        for name in names:
            task_id: str = name.removeprefix(prefix).removesuffix(".json")
            samples.extend(task_to_samples(task_id, json.loads(archive.read(name))))
    if (len(names), len(samples)) != (expected_tasks, expected_grids):
        raise ValueError(
            f"{ZIP_URL} holds {len(names)} tasks and {len(samples)} test grids, expected "
            f"{expected_tasks} and {expected_grids}"
        )
    return samples


def load_arc_agi_2_eval(cache_dir: Path | None = None) -> MemoryDataset:
    """Download the pinned zip (sha256-checked by inspect), turn its eval tasks into Samples."""

    from inspect_ai._util.appdirs import inspect_cache_dir

    # WHY imported here, by module attribute: the importer's Case Source recorder rebinds
    # ``inspect_ai.util.download`` while it watches, and a late lookup is what it rebinds.
    from inspect_ai.util import download

    folder: Path = cache_dir if cache_dir is not None else inspect_cache_dir("arc_agi_2")
    path: Path = download(ZIP_URL, ZIP_SHA256, folder / f"ARC-AGI-2-{DATA_COMMIT}.zip")
    samples: list[Sample] = samples_from_zip(
        path, expected_tasks=EXPECTED_TASKS, expected_grids=EXPECTED_GRIDS
    )
    return MemoryDataset(samples=samples, name="arc_agi_2_public_eval")


# ── reply reader: the harness's own parser ──────────────────────────────────────────────
def read_grid(completion: str) -> Grid | None:
    """The grid the harness would read from this reply, or None when it reads none."""

    try:
        return parse_and_validate_json(completion)
    except ValueError:
        # WHY None, not a raise: the harness would now ask the model to extract the grid, or
        # re-ask; we do neither (spec D5), so an unreadable reply is a wrong answer.
        return None


# ── scorer and whole-run metric ─────────────────────────────────────────────────────────
@scorer(metrics=[accuracy()])
def arc_exact_match() -> Scorer:
    """1.0 when the reply's grid equals the answer grid exactly, else 0.0 — one Attempt's mark."""

    async def score(state: TaskState, target: Target) -> Score:
        grid: Grid | None = read_grid(state.output.completion)
        if grid is None:
            return Score(value=0.0, answer="", explanation="no grid found")
        # INVARIANT: whole-grid equality, as the harness's ``attempt.answer == output``.
        solved: bool = grid == json.loads(target.text)
        return Score(value=1.0 if solved else 0.0, answer=json.dumps(grid))

    return score


@metric
def arc_per_task_accuracy() -> Metric:
    """The ARC Prize headline: the mean over TASKS of grids solved / grids in the task."""

    def compute(scores: list[SampleScore]) -> float:
        solved: dict[str, float] = {}
        grids: dict[str, int] = {}
        for sample in scores:
            metadata: dict[str, Any] = sample.sample_metadata or {}
            # WHY the fallback: the no-network lane's stand-in Cases carry no metadata; each
            # then counts as its own one-grid task, so the metric degrades to the plain mean.
            task_id: str = str(metadata.get("task_id", f"case:{sample.sample_id}"))
            grids[task_id] = int(metadata.get("grids_in_task", 1))
            solved[task_id] = solved.get(task_id, 0.0) + sample.score.as_float()
        # A failed Case never reaches here; dividing by grids_in_task counts it 0 (spec D7).
        return sum(solved[task_id] / grids[task_id] for task_id in grids) / len(grids)

    return compute


# ── the Task ─────────────────────────────────────────────────────────────────────────────
@task
def arc_agi_2() -> Task:
    """ARC-AGI-2 public eval: 120 tasks, 167 test grids, two any-match Attempts per grid."""

    return Task(
        dataset=load_arc_agi_2_eval(),
        solver=generate(),
        scorer=arc_exact_match(),
        metrics=[arc_per_task_accuracy()],
        # WHY "max", not "pass_at_2": pass_at_2 over a Case whose second Attempt failed is nan,
        # and the tally refuses the run (OME-1527); max credits the Attempt that graded.
        epochs=Epochs(ATTEMPTS, "max"),
    )
