"""The GDPval board this Engine serves, and what its number does and does not mean.

FEATURE: a fourth benchmark family, and the first drawn from work that professionals actually do
— 44 occupations across the nine largest sectors of US GDP, tasks written by practitioners
averaging 14 years of experience. GDPval appears in frontier-model launch tables, so a
fusion-beats-solo result here carries weight our other boards cannot buy.

INVARIANT — this board's score is NOT GDPval's published metric, and the description says so.
The official metric is a blinded expert PAIRWISE win rate against a human professional's
deliverable, graded at over an hour per comparison. That is unreachable here. This board grades
the published per-criterion rubrics instead, which is a different question answered by a
different judge. The valid claim is fusion versus solo ON THIS BOARD; parity with a published
GDPval number is not.

References:
    - Paper: https://arxiv.org/abs/2510.04374 (GDPval, Patwardhan et al., OpenAI, 2025)
    - Dataset: https://huggingface.co/datasets/openai/gdpval
"""

from __future__ import annotations

from screamingface_engine.benchmarks.gdpval.exam import gdpval_benchmark
from screamingface_engine.benchmarks.gdpval.scoring import mean
from screamingface_engine.benchmarks.gdpval.subset import TEXT_SUBSET_TASK_IDS, subset_sha

GDPVAL_DATASET_URL = "https://huggingface.co/datasets/openai/gdpval"

# WHY a contiguous range: Engine Case ids ARE the 1-based positions `prepare.py` numbers by, and
# this board serves every baked Case. A gap here would silently make it a subset of a subset.
TEXT_CASE_COUNT = len(TEXT_SUBSET_TASK_IDS)
TEXT_CASE_IDS = tuple(range(1, TEXT_CASE_COUNT + 1))

TEXT_EXAM, GDPVAL_TEXT = gdpval_benchmark(
    id="gdpval-text",
    title="GDPval Text Subset",
    description=(
        "The prose-only slice of GDPval's 220-task open gold set: 102 real professional work "
        "requests whose reference material and expected deliverable are documents rather than "
        "spreadsheets or slide decks. An AI judge grades the answer against the task's "
        "expert-written rubric, one criterion at a time; penalties subtract, so a case can score "
        "below zero. Benchmark score = the plain average of the case scores. "
        "Two deliberate differences from published GDPval numbers: submissions are plain text "
        "where 83 of these tasks expected a formatted document, so criteria checking the "
        "delivered file are excluded from scoring; and grading is per-criterion rubric judging "
        "rather than GDPval's official blinded expert pairwise comparison against a human "
        "professional's deliverable. Scores are therefore not comparable to the published "
        "GDPval leaderboard."
    ),
    case_ids=TEXT_CASE_IDS,
    protocol_revision="text-per-item-v1",
    scoring="rubric-mean-v1",
    mean=mean,
    # WHY the GDPval task ids rather than the Engine Case ids: this board's identity IS a
    # selection out of the 220, so the dataset's own stable ids are the honest fingerprint.
    selection_sha=subset_sha(),
    focus="Real professional work, prose deliverables",
    dataset_url=GDPVAL_DATASET_URL,
)

# AIDEV-NOTE: a board exposes exactly two names — the `Exam` (what the runtime installs) and the
# `Benchmark` (what the catalogue publishes). Reach a route through `TEXT_EXAM.routes.*`.
__all__ = ["GDPVAL_TEXT", "TEXT_CASE_COUNT", "TEXT_CASE_IDS", "TEXT_EXAM"]
