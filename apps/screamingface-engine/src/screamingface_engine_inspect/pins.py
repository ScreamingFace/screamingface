"""The imported boards' LOCKFILE — treat this module exactly like ``uv.lock``.

Like a lockfile, this is frozen, reviewable DATA, not logic: one small set of rows
per imported board, and the diff to these rows IS the exam changing. Every value
participates in the board's revision hash (spec §6: revision = sha over the pinned
package identity + the imported case subset's identity), so changing one changes
every route address — an expression addressed to an old revision never resolves
against a changed exam.

Also like a lockfile, the rows are of three kinds, written by different authors:

1. COPIED from the eval's source (dataset path / config / split): the values the
   eval's own task passes to ``hf_dataset(...)``. They live inside function bodies
   upstream, not exported constants, so they are transcribed here with the source
   named — verified against inspect-evals 0.20.0 on 2026-09-15.
2. CAPTURED at import time (dataset revision sha, case count): most inspect_evals
   tasks do NOT pin a HF revision — they fetch the Hub's latest. These rows record
   what HEAD resolved to when we froze the exam, the way a lockfile records the
   resolved version, and the count is the bake's drift guard (prepare refuses a
   dataset that no longer yields exactly this many rows). They cannot be derived
   from any code; they are observations.
3. OURS by policy (shuffle seed, preparer/protocol revisions): decisions this repo
   makes about how the exam is administered, not facts about upstream.

WHY frozen data instead of resolving at build or run time: a reviewable diff is the
security property. Builds fetch by the recorded sha and runs never fetch at all
(assets are baked into the image, OME-925), so a drifted or compromised upstream
can change nothing without a visible edit to this file. Import time — the moment a
row is first written — is the ONLY trust window, which is why new rows arrive as a
generated, human-reviewed diff (pin generator: follow-up on OME-1116).
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

# --- importer: generated pin rows land above this line ---

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
