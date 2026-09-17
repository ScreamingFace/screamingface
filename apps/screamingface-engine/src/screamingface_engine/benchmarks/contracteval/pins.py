"""What the ContractEval board pins — dataset, preparer, protocol, and sampling.

INVARIANT: every value here participates in the board's revision hash. Changing one changes
every route address, which is the point: an expression addressed to an old revision must never
resolve against a changed exam.

References:
    - Paper: https://arxiv.org/abs/2508.03080 · https://aclanthology.org/2025.nllp-1.19/
    - Reference harness: https://github.com/olivialiu121/ContractEval (MIT)
    - Dataset: https://huggingface.co/datasets/theatticusproject/cuad-qa (CUAD, CC BY 4.0)
"""

from __future__ import annotations

DATASET = "theatticusproject/cuad-qa"
DATASET_SPLIT = "test"
# WHY this revision is a `refs/convert/parquet` commit and not a `main` one: CUAD's `main`
# carries only `cuad-qa.py`, a loading SCRIPT, and its viewer is disabled ("requires arbitrary
# Python code execution"). `datasets` 4.x removed script loaders and `Dockerfile.benchmark` pins
# 5.0.0, so `load_dataset` against `main` cannot work at all. HuggingFace's auto-converted
# parquet branch is the only loadable form, and pinning its commit pins the bytes just as
# tightly as a `main` SHA would.
DATASET_REVISION = "d9c4ee0250ae2eb97bdb5b50773ab14ea62d0631"

# WHY: prepare's emission rules are part of the answer key; bump when they change.
PREPARER_REVISION = "cuad-test-v1"
# WHY: the exchange itself — single-shot verbatim extraction with an explicit abstain string.
PROTOCOL_REVISION = "single-shot-extract-v1"

# AIDEV-NOTE: the two constants below are ADVISORY — they are not applied by this board and are
# not in `compute_revision`. Sampling parameters reach a model from the SDK caller's
# `sf.Model(params=...)`, so these record what the reference used, for whoever writes a notebook
# or a run script. (MedXpertQA carries them the same way.) Do not "wire them up" without deciding
# what it means for a Fusion, whose members may each need different parameters.
#
# WHY 4096 and not the 100k the reference passes: the task is to QUOTE sentences from a contract,
# and the longest gold answer is a few hundred tokens. A large budget buys nothing here and lets
# a rambling model burn cost on a task whose correct output is short.
MAX_TOKENS = 4096
# The reference calls every model at temperature 0 (proprietary_model.py line 88).
#
# AIDEV-NOTE: do NOT blindly pass this to every model. Several current reasoning models REJECT
# `temperature` outright — via OpenRouter, `openai/gpt-5.5` answers 404 for any value and
# `anthropic/claude-opus-4.8` answers 400, while `gemini-3.1-pro-preview` and `qwen3.7-flash`
# accept it. The shipped notebook therefore omits temperature rather than pinning it.
TEMPERATURE = "0"

# WHY a guard and not a truncation budget: measured over all 4,182 rows with `tiktoken`
# cl100k_base, contexts run min 185 · p50 5,357 · p90 22,688 · max 63,389 tokens — nothing
# approaches this ceiling, and every panel model carries at least 128k. A truncation path would
# therefore be dead code whose only reachable effect is degrading comparability with the paper.
# INVARIANT: prepare RAISES above this rather than trimming, so a future dataset revision that
# grew a document fails the build instead of silently scoring a model against unseen text.
MAX_CONTEXT_TOKENS = 120_000

__all__ = [
    "DATASET",
    "DATASET_REVISION",
    "DATASET_SPLIT",
    "MAX_CONTEXT_TOKENS",
    "MAX_TOKENS",
    "PREPARER_REVISION",
    "PROTOCOL_REVISION",
    "TEMPERATURE",
]
