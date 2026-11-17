# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai,
# inspect_evals), absent in the default (extra-less) install the typecheck gate runs against;
# it is loaded only behind `inspect_available()`, like every other module in this package.
"""HLE-Diamond as a LOCAL inspect Task: inspect_evals' hle exam over the Diamond questions.

Think of it as inspect_evals' own Humanity's Last Exam with the question booklet swapped.
HLE-Diamond (released 22 Sep 2026) is the authors' cleaned successor to HLE: 1,000 vetted
questions, half marked reasoning and half knowledge. It is a separate Hub dataset with
cais/hle's columns plus ``partition``. inspect_evals v0.20.0's hle Task can load only
``cais/hle`` or ``cais/hle-rolling``, so this module points the same Task at
``cais/hle-diamond``; the prompt, the answer key's shape and the judge stay inspect_evals'.

Execution order, as the importer and the Engine see it:

    1. ``hle_diamond()`` → ``load_hle_diamond()``: inspect_evals' ``hf_dataset`` reads the test
       split of ``cais/hle-diamond`` at the pinned commit (the dataset is gated, so the import
       needs a Hub login token) and turns each row into a Sample with ``record_to_sample``.
    2. ``record_to_sample`` is inspect_evals' hle ``record_to_sample`` (the system prompt
       ``system_mc``, the question, the picture when the row has one, the answer as the key),
       with one line of ours, marked ``OURS``: the row's ``partition`` (reasoning or
       knowledge) is kept in the Sample metadata, which stays private Grading Material.
       Nothing reads it today. The metadata is inside the Case Digest, so keeping it now
       means per-half scores can come later without changing the Cases.
    3. the solver, scorer spec, generation settings and epoch reducer are inspect_evals' hle
       Task's own, read from its ``default.yaml`` through its own helpers, never copied. The
       Benchmark row passes the same ``scorer`` spec the ``hle`` row passes (the primary
       ``grader`` judge only).

Worked example (a stand-in, not a real Diamond question): the row ``id 6700a1b2…``,
question "What is 6 times 7?", answer "42", partition "reasoning" becomes a Sample whose input
is the system prompt then the question, whose target is "42", and whose metadata carries
``partition: reasoning`` beside inspect_evals' uid, subject, category and answer type.

INVARIANT: the pins and the row-to-Sample mapping are Benchmark identity: they decide the
bytes inside the Case Digest, so an edit is a new Benchmark, not a tweak.
``tests/unit/inspect/test_local_task_hle_diamond.py`` pins them.

References:
    - Paper: https://arxiv.org/abs/2501.14249
    - inspect_evals Task reused: inspect_evals.hle.hle:hle (v0.20.0)
    - Case Source: https://huggingface.co/datasets/cais/hle-diamond
"""

from __future__ import annotations

from typing import Any

from inspect_ai import Epochs, Task, task
from inspect_ai.dataset import Dataset, Sample
from inspect_ai.model import GenerateConfig
from inspect_ai.solver import generate
from inspect_evals.hle.dataset import DEFAULT_SYSTEM_PROMPT
from inspect_evals.hle.dataset import record_to_sample as hle_record_to_sample
from inspect_evals.hle.hle import DEFAULT_TASK_ARGS
from inspect_evals.hle.metrics import attempt_preserving_mean
from inspect_evals.hle.run_config import default_run_config
from inspect_evals.hle.scorers import scorers_from_spec
from inspect_evals.utils.huggingface import hf_dataset

# ── pins ──────────────────────────────────────────────────────────────────────────────
DATASET_PATH = "cais/hle-diamond"
DATASET_REVISION = "04eeb7efa7e3e4f83a00cbd5ce436a38fd5dda23"


def record_to_sample(record: dict[str, Any]) -> Sample:
    """One Diamond row → inspect_evals' hle Sample, carrying its partition."""

    sample: Sample = hle_record_to_sample(record, system_prompt=DEFAULT_SYSTEM_PROMPT)
    # OURS (step 2). WHY index, not .get: every Diamond row has a partition; a row without
    # one means the dataset is not the pinned Diamond, and the import must fail loudly.
    sample.metadata = {**(sample.metadata or {}), "partition": record["partition"]}
    return sample


def load_hle_diamond() -> Dataset:
    """Read Diamond's test split at the pinned commit and turn each row into a Sample."""

    return hf_dataset(
        path=DATASET_PATH,
        split="test",
        sample_fields=record_to_sample,
        # WHY natural order: as inspect_evals' hle, shuffling belongs to inspect's own flag.
        revision=DATASET_REVISION,
    )


@task
def hle_diamond(scorer: dict[str, Any] = DEFAULT_TASK_ARGS["scorer"]) -> Task:
    """HLE-Diamond: 1,000 expert questions, asked and judged as inspect_evals' hle asks them."""

    # WHY resolve before the fetch: as inspect_evals' hle, a bad spec fails before any download.
    scorers: Any = scorers_from_spec(scorer)
    run_config: dict[str, Any] = default_run_config()
    return Task(
        dataset=load_hle_diamond(),
        solver=generate(**run_config.get("solver", {}).get("args", {})),
        scorer=scorers,
        config=GenerateConfig(**run_config.get("generate_config", {})),
        epochs=Epochs(1, attempt_preserving_mean()),
        # OURS: inspect_evals' `version=` and `metadata=` lines are left out; they label ITS
        # Sample set, which this is not. The Benchmark revision is ours.
    )
