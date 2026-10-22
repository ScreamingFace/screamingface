# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai,
# inspect_evals), absent in the default (extra-less) install the typecheck gate runs against;
# it is loaded only behind `inspect_available()`, like every other module in this package.
"""WorldSense as a LOCAL inspect Task: inspect_evals' exam with every trial kept.

Think of it as inspect_evals' own exam with the register of candidates fixed. WorldSense asks
several questions (trials) about one described world (a tuple), arranged so each possible
answer is right exactly once per tuple: that is how the paper cancels a model's habit of
always saying "TRUE". inspect_evals v0.20.0 names each Sample after its tuple, so every trial
of one tuple gets the same id, and its duplicate-id filter keeps only the first: 40,176 of the
87,048 trials, every one of them the "yes" side.

Execution order, as the importer and the Engine see it:

    1. `worldsense()` calls inspect_evals' own loader (`load_worldsense_dataset`: the pinned
       `trials.jsonl.bz2` at facebookresearch/worldsense@bd81d945, sha256-checked) with
       `record_to_sample` below in place of inspect_evals'.
    2. `record_to_sample` builds inspect_evals' Sample, named after the trial's own `Key`
       (NAMED DEVIATION). inspect_evals' duplicate-id filter still runs and now drops nothing.
    3. the solver is inspect_evals' bare `generate()`: the question already lists its options.
    4. the scorer is inspect_evals' `pattern_with_metadata` (the leading 1/2/3/TRUE/FALSE/
       POSSIBLE/IMPOSSIBLE of the reply), with inspect_evals' metrics beside it.

NAMED DEVIATION — the Sample id. Adopted from inspect_evals PR #2507 (merged 2026-09-24,
https://github.com/UKGovernmentBEIS/inspect_evals/pull/2507), which uses the dataset's own
per-trial `Key`, unique over all 87,048 rows. Worked example, tuple `..._6109` (Compl.trivial)
has three trials about Alice's courses whose answers are "1", "2" and "3"; v0.20.0 names all
three `create_stable_id(tuple_ID, problemname)` and keeps only the "1" trial, while ours names
them `worldsense_-276741083417243227`, `worldsense_2747235547611487721` and
`worldsense_2917042815647934077` and keeps all three. What the loss did: no Case ever had the
answer FALSE, IMPOSSIBLE or "2", and a model answering TRUE, POSSIBLE or "1" to every question
of its kind scored 0.917 (best constant per family, measured 2026-10-21). On all 87,048 the
same trick scores 0.462.

COPIED VERBATIM: `worldsense` and `record_to_sample` below are inspect_evals' own, names and
bodies unchanged, as merged with PR #2507 (merge commit 2cb54ae9, which is v0.20.0's file plus
only the PR's id line):
https://github.com/UKGovernmentBEIS/inspect_evals/blob/2cb54ae9815dcb1ffa79498f8874c30f64f0c15c/src/inspect_evals/worldsense/worldsense.py#L58-L120
Two things are ours, both marked `OURS`: the Task's `version=` and `metadata=` lines are left
out (they are inspect_evals' comparability label for ITS Sample set, which this is not; the
Benchmark revision is ours), and the loader, scorer and metrics are imported from the pinned
v0.20.0 instead of defined here.

INVARIANT: everything except the id is inspect_evals', built by inspect_evals' own functions,
so a question reads exactly as inspect_evals sends it. The id itself is never served (served
Cases are numbered 1, 2, …, so it is not inside the Case Digest): it only decides which trials
survive inspect_evals' duplicate-id filter, and the Case Digest seals the trials that survive.
`tests/unit/inspect/test_local_task_worldsense.py` pins it, and its TRIPWIRE fails when the
inspect_evals pin reaches the fix, saying to point the row back at inspect_evals' Task.

References:
    - Paper: https://arxiv.org/abs/2311.15930
    - inspect_evals Task: inspect_evals.worldsense.worldsense:worldsense
    - Case Source: https://github.com/facebookresearch/worldsense
"""

# ruff: noqa: E501 — `worldsense`'s docstring is inspect_evals' own, copied verbatim; its long
# lines stay as they wrote them.
from __future__ import annotations

from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import accuracy, stderr
from inspect_ai.solver import generate

# OURS: the loader, scorer and metrics are imported from the pinned v0.20.0 (PR #2507 left
# them unchanged).
from inspect_evals.worldsense.worldsense import (
    load_worldsense_dataset,
    pattern_with_metadata,
    ws_accuracy,
    ws_bias,
)

# ── COPIED VERBATIM: inspect_evals' worldsense and record_to_sample, as merged with PR #2507 ──


@task
def worldsense(problemnames: str | list[str] = [], shuffle: bool = True) -> Task:
    """
    Task for evaluating reasoning related to world descriptions. There are three problem types ("Infer", "Compl", "Consist") and two grades ("trivial", "normal"). A problemname is formed by concatenation "<type>.<grade>". See README for details.

    Args:
        problemnames (str | list[str], optional): A string or list of strings specifying the names of problems or tasks to filter the dataset. If provided, it filters the dataset to samples that contain matching metadata for the specified problem names.
        shuffle (bool): Whether to shuffle the dataset for evaluation. Defaults to True.

    Returns:
        Task: A task object configured with a dataset filtered by problem names (if specified), a solver, a scoring pattern for evaluating task responses, and custom metrics.
    """
    dataset = load_worldsense_dataset(sample_fields=record_to_sample, shuffle=shuffle)

    # filter dataset if requested
    problemnames = problemnames if isinstance(problemnames, list) else [problemnames]
    if len(problemnames) > 0:
        task_dataset = dataset.filter(
            name=f"{dataset.name}-{'-'.join(problemnames)}",
            predicate=lambda sample: (
                sample.metadata is not None and sample.metadata.get("problemname") in problemnames
            ),
        )
    else:
        task_dataset = dataset

    return Task(
        dataset=task_dataset,
        solver=generate(),
        scorer=pattern_with_metadata(r"^\(?\s*(1|2|3|TRUE|FALSE|IMPOSSIBLE|POSSIBLE)\s*\)?"),
        metrics=[accuracy(), stderr(), ws_accuracy(), ws_bias()],
        config=GenerateConfig(temperature=0.0),
        # OURS: inspect_evals' `version=` and `metadata=` lines are left out (module docstring).
    )


def record_to_sample(record: dict[str, Any]) -> Sample:
    goldresp_mapping: dict[str, str] = {
        "Emmanuel": "TRUE",
        "Megi": "FALSE",
        "Dieuwke": "POSSIBLE",
        "Pascal": "IMPOSSIBLE",
        "Mark": "1",
        "Youssef": "2",
        "Yoda": "3",
    }

    return Sample(
        input=record["text"],
        choices=record["expectedresp"],
        target=goldresp_mapping.get(record["goldresp_obfusc"], "None"),
        id=f"worldsense_{record['Key']}",
        metadata={
            "tuple_ID": record["tuple_ID"],
            "problemname": record["problemname"],
            "problemsize": record["problemsize"],
        },
    )
