"""What every HealthBench benchmark pins identically — dataset, preparer, judge, check.

Two benchmarks ship from this package: the worst-30% challenge (`definition.py`) and the full
525-case professional variant (`professional.py`). They differ in which Cases they select and
in the benchmark-level mean — and in NOTHING else. These constants are that "nothing else",
kept in one place so the two benchmarks cannot drift apart by accident.

INVARIANT: every value here participates in both benchmarks' revision hashes. Changing one
changes every route address on both benchmarks — which is the point: an old expression must
never resolve against a changed benchmark.

References:
    - simple-evals (protocol authority): https://github.com/openai/simple-evals
    - Dataset: https://huggingface.co/datasets/openai/healthbench
    - Paper: https://arxiv.org/abs/2505.08775 (HealthBench, Arora et al., 2025)
"""

from __future__ import annotations

DATASET = "openai/healthbench-professional"
DATASET_REVISION = "349962fd46dd02343a0d8a606491baf59154ea1a"
# WHY: prepare.py's output participates in the answer key; bump this when the preparer's
# emission rules change so a rebuilt image can never serve old routes a different key.
PREPARER_REVISION = "hf-rows-v1"
# WHY: the official professional judge is ResponsesSampler(model="gpt-5.4-2026-03-05",
# reasoning_effort="low") — an OpenAI-internal snapshot pin we cannot reach; OpenRouter
# routes the floating slug. A silent snapshot bump can shift judge behavior between
# runs — a named deviation, mitigated by the Engine-rerun target (OME-762).
JUDGE_MODEL = "openrouter/openai/gpt-5.4"
# WHY: NO temperature pin — the official judge's reasoning branch sends ONLY
# reasoning={"effort":"low"} (not expressible through the gateway yet; named deviation),
# never temperature or an output cap. Provider-default temperature is LOAD-BEARING:
# ``;retry=`` re-sends identical bytes (opted out of the gateway cache since OME-1533, so the
# judge is asked again rather than the stored reply returned), so only a fresh sample can turn
# a malformed reply into a parseable one (the reference retries forever on fresh samples; the July
# port pinned temp 0 and needed a byte-salt url4 cannot express).
JUDGE_PARAMS = (
    # INVARIANT: Grading is retrieval-free even though the same route serves Candidates.
    ("web_search", "false"),
    # Engine-side safety bound only (DRACO precedent) — the official judge sends none.
    ("max_tokens", "4096"),
)
JUDGE_RETRIES = 2
# The pass criterion of the mid-run draft-feedback offer (OME-830), shared by both benchmarks so a
# corrective-loop recipe means the same thing whichever one it runs against.
CHECK_CRITERION = "healthbench-pass.v1"

__all__ = [
    "CHECK_CRITERION",
    "DATASET",
    "DATASET_REVISION",
    "JUDGE_MODEL",
    "JUDGE_PARAMS",
    "JUDGE_RETRIES",
    "PREPARER_REVISION",
]
