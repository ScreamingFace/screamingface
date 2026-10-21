# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai,
# huggingface_hub, pyarrow), absent in the default (extra-less) install the typecheck gate runs
# against; it is loaded only behind `inspect_available()`, like every other module in this package.
"""MedMCQA as a LOCAL inspect Task — our own eval in inspect's shape (OME-1696).

Think of it as a medical entrance exam printed the way inspect prints every multiple-choice
exam: one question, four options lettered A to D, and the answer key is the letter. inspect_evals
has no MedMCQA, so this module is the question booklet and the marking scheme both; the
importer seals the Cases by digest and the plugin's shared serving path does the rest.

Execution order, as the importer and the Engine see it:

    1. `medmcqa()` → `load_medmcqa_validation()`: fetch the pinned validation file from the Hub
       (commit pin + sha256, refused on mismatch) and turn each of its 4,183 rows into a Sample:
       the question as `input`, the four options `opa`..`opd` as `choices` in that order, and
       the letter of the correct option (`cop` 0..3 → A..D) as `target`.
    2. the solver is inspect's standard `multiple_choice()`: it lists the options as A) .. D)
       under inspect's answer-with-a-letter template and calls the model once.
    3. the scorer is inspect's `choice()`: the letter on the reply's `ANSWER:` line against the
       key. No judge.

Worked example: row `45258d3d` asks "Which of the following is not true for myelinated nerve
fibers:" with `cop` 0, so its key is `A` ("Impulse through myelinated fibers is slower than
non-myelinated fibers"). A reply ending `ANSWER: A` scores 1; `ANSWER: B` scores 0.

WHY the validation split: the test split's answers are withheld (its `cop` is -1), so the
validation ("dev") split is what LLM papers report on (Med-PaLM 2, Medprompt).

WHY inspect's standard template, no chain of thought: it is the one every multiple-choice
Benchmark here uses, and the widely cited zero-shot LLM numbers on this split were measured
that way (owner decision, OME-1696). Options are served in the dataset's order, unshuffled.

INVARIANT: the pins and the row-to-Sample mapping are Benchmark identity: they decide the bytes
inside the Case Digest, so an edit is a new Benchmark, not a tweak. `tests/unit/inspect/
test_local_task_medmcqa.py` pins them.

References:
    - Paper: https://arxiv.org/abs/2203.14371 (CHIL 2022, PMLR 174)
    - Homepage: https://medmcqa.github.io
    - Case Source: https://huggingface.co/datasets/openlifescienceai/medmcqa
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice

# ── pins ──────────────────────────────────────────────────────────────────────────────
DATASET = "openlifescienceai/medmcqa"
DATASET_REVISION = "91c6572c454088bf71b679ad90aa8dffcd0d5868"
DATASET_FILE = "data/validation-00000-of-00001.parquet"
DATASET_SHA256 = "b768a1ea34afc9f80d3106d9b21f80fa8a00ec450a1f6cd641af72ca9e591021"

#: The option columns, in the order the dataset letters them (`cop` 0 is `opa`).
OPTION_FIELDS: tuple[str, ...] = ("opa", "opb", "opc", "opd")
#: The answer letters, by `cop` index.
LETTERS: str = "ABCD"


def load_medmcqa_validation() -> MemoryDataset:
    """Download the pinned validation file, refuse a wrong sha256, turn each row into a Sample."""

    import pyarrow.parquet as parquet  # the `datasets` dependency the inspect extra installs
    from huggingface_hub import hf_hub_download  # recorded by the importer's Case Source recorder

    path: str = hf_hub_download(
        repo_id=DATASET, filename=DATASET_FILE, revision=DATASET_REVISION, repo_type="dataset"
    )
    actual: str = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if actual != DATASET_SHA256:
        raise ValueError(f"{DATASET_FILE} has sha256 {actual}, expected {DATASET_SHA256}")
    rows: list[dict[str, Any]] = parquet.read_table(path).to_pylist()
    return MemoryDataset(samples=[record_to_sample(row) for row in rows], name="medmcqa_validation")


def record_to_sample(row: dict[str, Any]) -> Sample:
    """One validation row → the question, its four options in dataset order, the key letter."""

    cop: object = row["cop"]
    # WHY refuse: a withheld (-1) or out-of-range key has no letter, and a Sample without a
    # real key would be marked wrong whatever the model answers.
    if not isinstance(cop, int) or not 0 <= cop < len(OPTION_FIELDS):
        raise ValueError(f"row {row['id']}: cop is {cop!r}, not an option index 0..3")
    return Sample(
        id=row["id"],
        input=row["question"],
        choices=[row[field] for field in OPTION_FIELDS],
        target=LETTERS[cop],
    )


@task
def medmcqa() -> Task:
    """MedMCQA validation: 4,183 four-option questions from Indian medical entrance exams."""

    return Task(
        dataset=load_medmcqa_validation(),
        solver=multiple_choice(),
        scorer=choice(),
    )
