"""The two HealthBench boards this Engine serves, and what makes them different.

Both sit the SAME exam over the SAME baked answer key — 525 physician-rubric-graded
conversations, one AI judge, one grading chain. They differ in exactly two places:

    board            cases                    exam-level score
    ───────────────  ───────────────────────  ────────────────────────────────────
    worst30          the frozen hardest 157   UNCLIPPED mean — negatives kept, so a
                                              hard board still ranks its entrants
    professional     all 525                  the OFFICIAL clipped mean, comparable
                                              to published HealthBench numbers

Everything else is shared and cannot drift: the dataset and judge pinning live in
``pins.py``, and the revision math, route layout, and url4 expression tree live in
``exam.py``. Each board below is one call to ``healthbench_benchmark``.

FEATURE: worst30 is the entry challenge — open-source Fusions try to beat our open-fusion
baseline on the hardest rows. Professional is the comparability board — one number a
reader can check against the HealthBench paper.

INVARIANT: worst30's revision is FROZEN at ``39cfd96b068f7230``
(``test_healthbench_definition.py``). Its routes carry it and the scoreboard seeds it, so
an accidental change would orphan every existing submission.

References:
    - simple-evals (protocol authority): https://github.com/openai/simple-evals
    - Dataset: https://huggingface.co/datasets/openai/healthbench
    - Paper: https://arxiv.org/abs/2505.08775 (HealthBench, Arora et al., 2025)
"""

from __future__ import annotations

from screamingface_engine.benchmarks.healthbench.exam import case_ids_sha, healthbench_benchmark
from screamingface_engine.benchmarks.healthbench.scoring import clipped_mean, unclipped_mean
from screamingface_engine.benchmarks.healthbench.subset import WORST30_CASE_IDS, subset_sha

# Both boards grade the same physician-written rubrics over the same public dataset; they
# differ in which conversations they serve and how they average the per-case scores.
HEALTHBENCH_DATASET_URL = "https://huggingface.co/datasets/openai/healthbench"

# ── Board 1 — the worst-30% challenge ────────────────────────────────────────────────
WORST30_EXAM, HEALTHBENCH_WORST30 = healthbench_benchmark(
    id="healthbench-worst30",
    title="HealthBench Worst-30% Challenge",
    description=(
        "The 157 hardest conversations from HealthBench Professional — the 30% that "
        "top models score worst on. An AI judge grades each answer against a "
        "physician-written rubric; safety mistakes subtract points, so per-case scores "
        "can be negative. Challenge score = plain average of the 157 case scores, "
        "negatives kept (the official HealthBench score floors negative averages at 0, "
        "which would flatten this hard subset to all-zeros)."
    ),
    case_ids=WORST30_CASE_IDS,
    protocol_revision="worst30-per-item-v2",  # v2: aggregate intent carries the selected count
    scoring="unclipped-mean-v1",
    mean=unclipped_mean,
    # WHY the HF ids, not the Engine Case ids: this board's identity IS the frozen
    # worst-30% selection out of the dataset, so its fingerprint is taken over the
    # dataset's own stable row ids (subset.py).
    selection_sha=subset_sha(),
    focus="Clinical safety, hardest cases",
    dataset_url=HEALTHBENCH_DATASET_URL,
)

# ── Board 2 — the full professional exam ─────────────────────────────────────────────
# INVARIANT: the pinned dataset revision holds exactly this many professional rows, and
# ``prepare.emit`` refuses to bake anything else — a dataset that grew or shrank would
# otherwise ship a differently-sized exam under this identity.
PROFESSIONAL_CASE_COUNT = 525
# WHY a contiguous range: Engine Case ids ARE the 1-based positions prepare.py numbers by,
# so "the whole exam" is every position. A gap here would silently make this a subset.
PROFESSIONAL_CASE_IDS = tuple(range(1, PROFESSIONAL_CASE_COUNT + 1))

PROFESSIONAL_EXAM, HEALTHBENCH_PROFESSIONAL = healthbench_benchmark(
    id="healthbench-professional",
    title="HealthBench Professional",
    description=(
        "The complete 525-conversation HealthBench Professional exam. An AI judge grades "
        "each answer against a physician-written rubric; safety mistakes subtract points, "
        "so an individual case can score below zero. Benchmark score = the official "
        "HealthBench metric — the average of the 525 case scores, floored at 0 — so it "
        "lines up with published HealthBench numbers."
    ),
    case_ids=PROFESSIONAL_CASE_IDS,
    protocol_revision="professional-per-item-v1",
    scoring="official-clipped-mean-v1",
    mean=clipped_mean,
    # WHY the Case ids, not dataset row ids: this board's selection IS "every position in
    # the baked file", so the id list is the honest fingerprint of what it serves.
    selection_sha=case_ids_sha(PROFESSIONAL_CASE_IDS),
    focus="Clinical safety, full official exam",
    dataset_url=HEALTHBENCH_DATASET_URL,
)

# AIDEV-NOTE: a board exposes exactly two names — the `Exam` (what the runtime installs:
# `.id`, `.revision`, `.routes.*`, `.case_ids`, `.mean`) and the `Benchmark` (what the
# catalogue publishes). Reach a route through `<BOARD>_EXAM.routes.cases`, never through a
# module-level alias: an unprefixed constant here would silently mean one of the two.
__all__ = [
    "HEALTHBENCH_PROFESSIONAL",
    "HEALTHBENCH_WORST30",
    "PROFESSIONAL_CASE_COUNT",
    "PROFESSIONAL_CASE_IDS",
    "PROFESSIONAL_EXAM",
    "WORST30_EXAM",
]
