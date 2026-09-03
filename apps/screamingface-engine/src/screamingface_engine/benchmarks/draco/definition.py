"""The DRACO boards this Engine serves, and what makes them different.

Both sit the SAME 100-case dataset (``perplexity-ai/draco``) over the SAME rubric
answer key — one Judge (Gemini-3.1-Pro Preview), one grading chain. They differ in
exactly one place:

    board         judge passes   grading
    ────────────  ─────────────  ──────────────────────────────────────────────────
    draco         5              the official five-pass reproduction (the paper
                                 judges every answer five times for stability)
    draco-3pass   3              the cache-seeded replay — the draco-cache-seed
                                 archive covers grading rounds 1-3 only, so this
                                 board re-runs the archived candidates fully from
                                 the shared response cache

Everything else is shared and cannot drift: the dataset and judge pinning live in
``exam.py``, and the revision math, route layout, and url4 expression tree live in
``exam.py`` too. Each board below is one call to ``draco_benchmark``.

INVARIANT: canonical ``draco``'s revision is FROZEN at ``62718f04ea1a980f``
(``test_draco_3pass_definition.py``; OME-993 moved it deliberately from
``66a463248586b277`` when the judge gained reasoning_effort=low; max_tokens stays the paper's 4096).
Its routes carry it and the scoreboard seeds it,
so an accidental change would orphan every existing submission. The 3-pass board is a
separate identity by construction — a different revision is a different benchmark, so
its scores are never compared against the five-pass ones (OME-775).

References:
    - DRACO (protocol authority): https://github.com/perplexity-ai/draco
    - Dataset: https://huggingface.co/datasets/perplexity-ai/draco
"""

from __future__ import annotations

from screamingface_engine.benchmarks.draco.exam import (
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

# Both boards replay the same 100 DRACO tasks over the same public dataset; they differ only in
# how many times each answer is judged.
DRACO_DATASET_URL = "https://huggingface.co/datasets/perplexity-ai/draco"

# ── Board 1 — the canonical five-pass reproduction ──────────────────────────────────
CANONICAL_EXAM, DRACO = draco_benchmark(
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
    focus="Research reports with citations",
    dataset_url=DRACO_DATASET_URL,
)

# ── Board 2 — the three-pass cache-seeded replay ────────────────────────────────────
THREE_PASS_EXAM, DRACO_3PASS = draco_benchmark(
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
    # The dataset and the subject are identical to the canonical board; the pass count is the
    # only thing a reader needs to tell them apart, so that is what the Focus column says.
    focus="Research reports, three judge passes",
    dataset_url=DRACO_DATASET_URL,
    protocol_revision="three-pass-reproduction-v1",
)

# ── canonical aliases (kept for the runtime and the tests that import them) ─────────
# These are the canonical board's values, re-exported so pre-factory callers keep
# working unchanged. The runtime now reads the exam instead; only legacy imports touch
# these.
BENCHMARK_ID = CANONICAL_EXAM.id
REVISION = CANONICAL_EXAM.revision
JUDGE_PASSES = CANONICAL_EXAM.judge_passes
JUDGE_SEEDS = tuple(range(1, JUDGE_PASSES + 1))
ROUTE_PREFIX = CANONICAL_EXAM.routes.prefix
CASES_ROUTE = CANONICAL_EXAM.routes.cases
TASKS_ROUTE = CANONICAL_EXAM.routes.tasks
VERDICT_ROUTE = CANONICAL_EXAM.routes.verdict
CRITERION_EVALUATION_ROUTE = CANONICAL_EXAM.routes.criterion_evaluation
CASE_EVALUATION_ROUTE = CANONICAL_EXAM.routes.case_evaluation
AGGREGATE_ROUTE = CANONICAL_EXAM.routes.aggregate
CHECK_SURFACE_ROUTE = CANONICAL_EXAM.routes.check_surface

__all__ = [
    "AGGREGATE_ROUTE",
    "ASSET_BUNDLE_ID",
    "BENCHMARK_ID",
    "CASE_COUNT",
    "CASE_EVALUATION_ROUTE",
    "CASES_ROUTE",
    "CANONICAL_EXAM",
    "CHECK_CRITERION",
    "CHECK_SURFACE_ROUTE",
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
    "TASKS_ROUTE",
    "THREE_PASS_EXAM",
    "VERDICT_ROUTE",
]
