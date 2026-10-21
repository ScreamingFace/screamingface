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
    2. `record_to_sample` builds inspect_evals' Sample, then names it after the trial's own
       `Key` (NAMED DEVIATION). inspect_evals' duplicate-id filter still runs and now drops
       nothing.
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

from __future__ import annotations

from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Dataset, Sample
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import accuracy, stderr
from inspect_ai.solver import generate
from inspect_evals.worldsense.worldsense import (
    load_worldsense_dataset,
    pattern_with_metadata,
    ws_accuracy,
    ws_bias,
)
from inspect_evals.worldsense.worldsense import record_to_sample as inspect_evals_record_to_sample


def record_to_sample(record: dict[str, Any]) -> Sample:
    """inspect_evals' Sample for one trial, named after the trial's own `Key` (NAMED DEVIATION)."""

    sample: Sample = inspect_evals_record_to_sample(record)
    # WHY the Key unhashed: inspect_evals' fix found the 8-hex `create_stable_id` digest
    # collides on two of the 87,048 Keys, which would drop a trial again.
    return sample.model_copy(update={"id": f"worldsense_{record['Key']}"})


@task
def worldsense(problemnames: str | list[str] = [], shuffle: bool = True) -> Task:
    """WorldSense: reason about small described worlds; every trial of the test set kept.

    The body is inspect_evals' v0.20.0 `worldsense`, with this module's `record_to_sample`.
    WHY no `version`/`metadata`: those are inspect_evals' comparability label for ITS Sample
    set, which this is not; the Benchmark revision is ours. The mutable default is
    inspect_evals' signature.
    """

    dataset: Dataset = load_worldsense_dataset(sample_fields=record_to_sample, shuffle=shuffle)

    names: list[str] = problemnames if isinstance(problemnames, list) else [problemnames]
    task_dataset: Dataset = (
        dataset.filter(
            name=f"{dataset.name}-{'-'.join(names)}",
            predicate=lambda sample: (
                sample.metadata is not None and sample.metadata.get("problemname") in names
            ),
        )
        if names
        else dataset
    )

    return Task(
        dataset=task_dataset,
        solver=generate(),
        scorer=pattern_with_metadata(r"^\(?\s*(1|2|3|TRUE|FALSE|IMPOSSIBLE|POSSIBLE)\s*\)?"),
        metrics=[accuracy(), stderr(), ws_accuracy(), ws_bias()],
        config=GenerateConfig(temperature=0.0),
    )
