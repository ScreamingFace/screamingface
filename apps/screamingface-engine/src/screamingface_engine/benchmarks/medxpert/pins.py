"""What the MedXpertQA board pins — dataset, preparer, protocol, and sampling.

INVARIANT: every value here participates in the board's revision hash. Changing one changes every
route address, which is the point: an expression addressed to an old revision must never resolve
against a changed exam.

References:
    - Paper: https://arxiv.org/abs/2501.18362 (MedXpertQA)
    - Dataset: https://huggingface.co/datasets/TsinghuaC3I/MedXpertQA
    - Official harness: https://github.com/TsinghuaC3I/MedXpertQA (eval/)
"""

from __future__ import annotations

DATASET = "TsinghuaC3I/MedXpertQA"
DATASET_CONFIG = "Text"
DATASET_SPLIT = "test"
# WHY pinned: the gold answer key is published data that can be re-pushed. A revision bump that
# changed a label or dropped a row must fail the build rather than serve a different exam under
# this identity.
DATASET_REVISION = "7e7c465a68eb2b866926bfa59c8c9d17a8daba65"

# WHY: prepare's emission rules are part of the answer key; bump when they change.
PREPARER_REVISION = "text-test-v1"
# WHY: the exchange itself — two-turn zero-shot CoT, first-match commit extraction.
PROTOCOL_REVISION = "two-turn-cot-v1"

# WHY 8192 and not the official harness's smaller default: reasoning models exhaust a 2,048
# budget before committing and return empty content, which does not lower their score — it
# removes them from the denominator, so a starved model looks like it answered a smaller, easier
# exam. Measured in the prior experimental run.
MAX_TOKENS = 8192
# The official protocol is deterministic sampling.
TEMPERATURE = "0"

__all__ = [
    "DATASET",
    "DATASET_CONFIG",
    "DATASET_REVISION",
    "DATASET_SPLIT",
    "MAX_TOKENS",
    "PREPARER_REVISION",
    "PROTOCOL_REVISION",
    "TEMPERATURE",
]
