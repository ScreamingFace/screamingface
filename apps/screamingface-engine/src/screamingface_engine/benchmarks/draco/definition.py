"""The DRACO benchmarks this Engine serves, and what makes them different.

Both sit the SAME 100-case dataset (``perplexity-ai/draco``) over the SAME rubric
answer key — one Judge (Gemini-3.1-Pro Preview), one grading chain. They differ in
exactly one place:

    benchmark         judge passes   grading
    ────────────  ─────────────  ──────────────────────────────────────────────────
    draco         5              the official five-pass reproduction (the paper
                                 judges every answer five times for stability)
    draco-3pass   3              the cache-seeded replay — the draco-cache-seed
                                 archive covers grading rounds 1-3 only, so this
                                 benchmark re-runs the archived candidates fully from
                                 the shared response cache

Everything else is shared and cannot drift: the dataset and judge pinning live in
``benchmark.py``, and the revision math, route layout, and url4 expression tree live in
``benchmark.py`` too. Each benchmark below is one call to ``draco_benchmark``.

INVARIANT: canonical ``draco``'s revision is FROZEN at ``62718f04ea1a980f``
(``test_draco_3pass_definition.py``; OME-993 moved it deliberately from
``66a463248586b277`` when the judge gained reasoning_effort=low; max_tokens stays the paper's 4096).
Its routes carry it and the scoreboard seeds it,
so an accidental change would orphan every existing submission. The 3-pass benchmark is a
separate identity by construction — a different revision is a different benchmark, so
its scores are never compared against the five-pass ones (OME-775).

References:
    - DRACO (protocol authority): https://github.com/perplexity-ai/draco
    - Dataset: https://huggingface.co/datasets/perplexity-ai/draco
"""

from __future__ import annotations

from screamingface_engine.benchmarks.draco.variant import (
    ASSET_BUNDLE_ID,
    CASE_COUNT,
    CHECK_CRITERION,
    DATASET,
    DATASET_PREPARER_REVISION,
    DATASET_REVISION,
    EXCLUDED_DOMAINS,
    JUDGE_MODEL,
    JUDGE_PARAMS,
    RETRIEVAL_POLICY_ID,
    draco_benchmark,
)
from screamingface_engine.benchmarks.provenance import FrontierScore, NotPublished

# Both benchmarks replay the same 100 DRACO tasks over the same public dataset; they differ only in
# how many times each answer is judged.
DRACO_DATASET_URL = "https://huggingface.co/datasets/perplexity-ai/draco"

# ── Benchmark 1 — the canonical five-pass reproduction ──────────────────────────────────
CANONICAL_VARIANT, DRACO = draco_benchmark(
    id="draco",
    title="DRACO",
    description=(
        "A 100-task DRACO reproduction with official score arithmetic. It uses the successor "
        "Judge model, provider-default reasoning, mixed native/Tavily retrieval, and a host-only "
        "approximation of the reference blocklist, so its scores are not paper-identical. Every "
        "answer is judged five times — the paper's stability protocol."
    ),
    judge_passes=5,
    protocol_revision="five-pass-reproduction-v1",
    # Open-ended deep-research reports frontier models still visibly fail (OME-1257).
    difficulty="hard",
    focus="Research reports with citations",
    dataset_url=DRACO_DATASET_URL,
    # Benchmark Provenance (OME-1455); sources in the PR 3 table.
    paper_url="https://arxiv.org/abs/2602.11685",
    authors="Zhong et al., 2026",
    citation=(
        "@misc{zhong2026dracocrossdomainbenchmarkdeep,\n"
        "      title={DRACO: a Cross-Domain Benchmark for Deep Research Accuracy, Com"
        "pleteness, and Objectivity}, \n"
        "      author={Joey Zhong and Hao Zhang and Clare Southern and Jeremy Yang an"
        "d Thomas Wang and Kate Jung and Shu Zhang and Denis Yarats and Johnny Ho and"
        " Jerry Ma},\n"
        "      year={2026},\n"
        "      eprint={2602.11685},\n"
        "      archivePrefix={arXiv},\n"
        "      primaryClass={cs.LG},\n"
        "      url={https://arxiv.org/abs/2602.11685}, \n"
        "}"
    ),
    harness_url=(
        "https://huggingface.co/datasets/perplexity-ai/draco/tree/ce076749809027649ebd331bcb70f42bf720d387"
    ),
    license="MIT",
    license_note=(
        "perplexity-ai/draco dataset card. The GitHub repo the docstring cites as protocol "
        "authority is not public, so the harness link is the dataset repo (rubrics and tasks) at "
        "the pinned revision."
    ),
    human_baseline=NotPublished(reason="the DRACO paper reports no human study"),
    # Frontier score: DRACO score, five judge passes, agentic deep research with retrieval.
    frontier_score=FrontierScore(
        score=0.705,
        model="Perplexity Deep Research (Claude Opus 4.6)",
        source_url="https://arxiv.org/abs/2602.11685",
        as_of="2026-02",
    ),
    notebook="06_draco",
)

# ── Benchmark 2 — the three-pass cache-seeded replay ────────────────────────────────────
THREE_PASS_VARIANT, DRACO_3PASS = draco_benchmark(
    id="draco-3pass",
    title="DRACO 3-Pass",
    description=(
        "The DRACO 100-case reproduction judged three times per answer instead of five. "
        "Identical dataset, criteria, Judge, and retrieval policy to the canonical board — "
        "only the judge-pass count differs. The draco-cache-seed archive covers exactly "
        "these three passes, so re-running its candidates is served fully from the shared "
        "response cache; scores carry their own benchmark revision and are not compared "
        "against five-pass results."
    ),
    judge_passes=3,
    # Same 100 tasks as the canonical benchmark — the tier travels with the dataset, not the
    # judge-pass count (OME-1257).
    difficulty="hard",
    # The dataset and the subject are identical to the canonical benchmark; the pass count is the
    # only thing a reader needs to tell them apart, so that is what the Focus column says.
    focus="Research reports, three judge passes",
    dataset_url=DRACO_DATASET_URL,
    protocol_revision="three-pass-reproduction-v1",
    # Benchmark Provenance (OME-1455); sources in the PR 3 table.
    paper_url="https://arxiv.org/abs/2602.11685",
    authors="Zhong et al., 2026",
    citation=(
        "@misc{zhong2026dracocrossdomainbenchmarkdeep,\n"
        "      title={DRACO: a Cross-Domain Benchmark for Deep Research Accuracy, Com"
        "pleteness, and Objectivity}, \n"
        "      author={Joey Zhong and Hao Zhang and Clare Southern and Jeremy Yang an"
        "d Thomas Wang and Kate Jung and Shu Zhang and Denis Yarats and Johnny Ho and"
        " Jerry Ma},\n"
        "      year={2026},\n"
        "      eprint={2602.11685},\n"
        "      archivePrefix={arXiv},\n"
        "      primaryClass={cs.LG},\n"
        "      url={https://arxiv.org/abs/2602.11685}, \n"
        "}"
    ),
    harness_url=(
        "https://huggingface.co/datasets/perplexity-ai/draco/tree/ce076749809027649ebd331bcb70f42bf720d387"
    ),
    license="MIT",
    license_note=(
        "perplexity-ai/draco dataset card. The GitHub repo the docstring cites as protocol "
        "authority is not public, so the harness link is the dataset repo (rubrics and tasks) at "
        "the pinned revision."
    ),
    human_baseline=NotPublished(reason="the DRACO paper reports no human study"),
    # Frontier score: DRACO score, five judge passes, agentic deep research with retrieval.
    frontier_score=FrontierScore(
        score=0.705,
        model="Perplexity Deep Research (Claude Opus 4.6)",
        source_url="https://arxiv.org/abs/2602.11685",
        as_of="2026-02",
    ),
    notebook="06_draco",
)

# ── canonical aliases (kept for the runtime and the tests that import them) ─────────
# These are the canonical benchmark's values, re-exported so pre-factory callers keep
# working unchanged. The runtime now reads the benchmark instead; only legacy imports touch
# these.
BENCHMARK_ID = CANONICAL_VARIANT.id
REVISION = CANONICAL_VARIANT.revision
JUDGE_PASSES = CANONICAL_VARIANT.judge_passes
JUDGE_SEEDS = tuple(range(1, JUDGE_PASSES + 1))
ROUTE_PREFIX = CANONICAL_VARIANT.routes.prefix
CASES_ROUTE = CANONICAL_VARIANT.routes.cases
JUDGE_REQUESTS_ROUTE = CANONICAL_VARIANT.routes.judge_requests
VERDICT_ROUTE = CANONICAL_VARIANT.routes.verdict
CRITERION_EVALUATION_ROUTE = CANONICAL_VARIANT.routes.criterion_evaluation
CASE_GRADE_ROUTE = CANONICAL_VARIANT.routes.case_evaluation
AGGREGATE_ROUTE = CANONICAL_VARIANT.routes.aggregate
DRAFT_FEEDBACK_ROUTE = CANONICAL_VARIANT.routes.check_surface

__all__ = [
    "AGGREGATE_ROUTE",
    "ASSET_BUNDLE_ID",
    "BENCHMARK_ID",
    "CASE_COUNT",
    "CASE_GRADE_ROUTE",
    "CASES_ROUTE",
    "CANONICAL_VARIANT",
    "CHECK_CRITERION",
    "DRAFT_FEEDBACK_ROUTE",
    "CRITERION_EVALUATION_ROUTE",
    "DATASET",
    "DATASET_PREPARER_REVISION",
    "DATASET_REVISION",
    "DRACO",
    "DRACO_3PASS",
    "EXCLUDED_DOMAINS",
    "JUDGE_MODEL",
    "JUDGE_PARAMS",
    "JUDGE_PASSES",
    "JUDGE_SEEDS",
    "RETRIEVAL_POLICY_ID",
    "REVISION",
    "ROUTE_PREFIX",
    "JUDGE_REQUESTS_ROUTE",
    "THREE_PASS_VARIANT",
    "VERDICT_ROUTE",
]
