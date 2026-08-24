"""What the GDPval text-subset board pins — dataset, preparer, and the judge.

INVARIANT: every value here participates in the board's revision hash. Changing one changes
every route address, which is the point: an expression addressed to the old revision must never
resolve against a changed exam.

References:
    - Paper: https://arxiv.org/abs/2510.04374 (GDPval, Patwardhan et al., OpenAI, 2025)
    - Dataset: https://huggingface.co/datasets/openai/gdpval
"""

from __future__ import annotations

DATASET = "openai/gdpval"
# WHY pinned: the gold subset is published data that can be re-pushed. The frozen selection in
# `subset.py` addresses tasks by id, so a revision bump that dropped or renamed one must fail the
# build rather than silently bake a smaller exam. This is the revision the reference
# implementation (UKGovernmentBEIS/inspect_evals) pins.
DATASET_REVISION = "a3848a2a812d5d4d0f08003fac3c8eac40805962"

# WHY: prepare.py's output participates in the answer key; bump this when the preparer's emission
# rules change — reference delimiter, envelope shape, rubric mapping — so a rebuilt image can
# never serve old routes a different key.
PREPARER_REVISION = "text-subset-v1"

__all__ = ["DATASET", "DATASET_REVISION", "PREPARER_REVISION"]
