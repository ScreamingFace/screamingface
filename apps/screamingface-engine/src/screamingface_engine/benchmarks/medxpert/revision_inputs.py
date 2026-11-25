"""What the MedXpertQA benchmark pins — dataset, preparer and protocol.

INVARIANT: every value here participates in the benchmark's revision hash. Changing one changes
every route address, which is the point: an expression addressed to an old revision must never
resolve against a changed benchmark.

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
# changed a label or dropped a row must fail the build rather than serve a different benchmark under
# this identity.
DATASET_REVISION = "7e7c465a68eb2b866926bfa59c8c9d17a8daba65"

# WHY: prepare's emission rules are part of the answer key; bump when they change.
PREPARER_REVISION = "text-test-v1"
# WHY: the exchange itself — two-turn zero-shot CoT, first-match commit extraction.
# v2 (OME-1786): turn 2 carries turn 1's answer text. Under v1 it carried turn 1's whole result
# record, accounting included, so the same Case sent different turn-2 bytes on a rerun.
# v3 (OME-1980): turn 2 continues the chat (user prompt, assistant answer, user trigger) and is
# answered by the one model that wrote the turn-1 answer; the reader keeps the text between the
# first and second trigger. Under v2 turn 2 was one JSON user message to the whole Candidate.
# v4 (OME-2018): turn 2's last message opens with the reply rule ("Finish the sentence below with
# the option letter only, and nothing else."), and the reader reads a letter wrapped in
# underscores. Under v3 turn 2 sent the bare trigger and the model explained again.
PROTOCOL_REVISION = "two-turn-cot-v4"

# AIDEV-NOTE (OME-1980): the harness's sampling (temperature 0, seed 0, 2048 or 8192 tokens) is
# NOT sent, by the owner's call: today's reasoning models reject temperature 0 or run out of
# tokens at 2048, and the AI Gateway does not drop a parameter a provider rejects. The Candidate's
# own settings apply; the Benchmark description says so. The unused MAX_TOKENS/TEMPERATURE
# constants that claimed otherwise were removed.

__all__ = [
    "DATASET",
    "DATASET_CONFIG",
    "DATASET_REVISION",
    "DATASET_SPLIT",
    "PREPARER_REVISION",
    "PROTOCOL_REVISION",
]
