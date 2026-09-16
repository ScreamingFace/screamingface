"""What the imported proof boards pin — datasets, seeds, and the inspect packages.

INVARIANT: every value here participates in a board's revision hash (spec §6:
revision = sha over the pinned package identity + the imported case subset's
identity). Changing one changes every route address, so an expression addressed
to an old revision never resolves against a changed exam.

The dataset revisions are copied VERBATIM from the pinned inspect_evals release
(their module constants), so our snapshot and their published eval read the same
bytes — verified against inspect-evals 0.20.0 source on 2026-09-15.
"""

from __future__ import annotations

from importlib.metadata import version

# gsm8k — their gsm8k.py pins (hf_dataset path/data_dir/split/revision).
# https://huggingface.co/datasets/openai/gsm8k/tree/cc7b047b6e5bb11b4f1af84efc572db110a51b3c
GSM8K_DATASET = "openai/gsm8k"
GSM8K_DATA_DIR = "main"
GSM8K_SPLIT = "test"
GSM8K_DATASET_REVISION = "cc7b047b6e5bb11b4f1af84efc572db110a51b3c"
GSM8K_CASE_COUNT = 1319

# mmlu — their mmlu.py pins (mmlu_0_shot's EN_US path).
# https://huggingface.co/datasets/cais/mmlu/tree/c30699e8356da336a370243923dbaf21066bb9fe
MMLU_DATASET = "cais/mmlu"
MMLU_CONFIG = "all"
MMLU_SPLIT = "test"
MMLU_DATASET_REVISION = "c30699e8356da336a370243923dbaf21066bb9fe"
MMLU_CASE_COUNT = 14042
# WHY a seeded shuffle: the HF split is subject-grouped, so an unshuffled `limit=N`
# run would examine one subject only. The seed is exam identity (it fixes which
# cases a limit selects), so it rides the revision hash.
MMLU_SHUFFLE_SEED = 20260915

# WHY: prepare's emission rules are part of the exam; bump when they change.
PREPARER_REVISION = "inspect-single-shot-v1"
# WHY: the exchange itself — one candidate invocation, aggregate-side scoring.
PROTOCOL_REVISION = "inspect-single-shot-v1"


def pinned_inspect_packages() -> tuple[str, str]:
    """The installed inspect distributions as ``name==version`` identity strings.

    Spec §6 hashes "the pinned inspect-evals package digest"; with exact ``==``
    pins in the engine's ``inspect`` extra, the version string IS that identity.
    """

    return (
        f"inspect-ai=={version('inspect-ai')}",
        f"inspect-evals=={version('inspect-evals')}",
    )


__all__ = [
    "GSM8K_CASE_COUNT",
    "GSM8K_DATA_DIR",
    "GSM8K_DATASET",
    "GSM8K_DATASET_REVISION",
    "GSM8K_SPLIT",
    "MMLU_CASE_COUNT",
    "MMLU_CONFIG",
    "MMLU_DATASET",
    "MMLU_DATASET_REVISION",
    "MMLU_SHUFFLE_SEED",
    "MMLU_SPLIT",
    "PREPARER_REVISION",
    "PROTOCOL_REVISION",
    "pinned_inspect_packages",
]
