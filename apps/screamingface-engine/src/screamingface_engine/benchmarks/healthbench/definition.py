"""The two HealthBench benchmarks this Engine serves, and what makes them different.

Both sit the SAME benchmark over the SAME prepared answer key — 525 physician-rubric-graded
conversations, one AI judge, one grading chain. They differ in exactly two places:

    benchmark            cases                    benchmark-level score
    ───────────────  ───────────────────────  ────────────────────────────────────
    worst30          the frozen hardest 157   UNCLIPPED mean — negatives kept, so a
                                              hard benchmark still ranks its entrants
    professional     all 525                  the OFFICIAL clipped mean, comparable
                                              to published HealthBench numbers

Everything else is shared and cannot drift: the dataset and judge pinning live in
``pins.py``, and the revision math, route layout, and url4 expression tree live in
``benchmark.py``. Each benchmark below is one call to ``healthbench_benchmark``.

FEATURE: worst30 is the entry challenge — open-source Fusions try to beat our open-fusion
baseline on the hardest rows. Professional is the comparability benchmark — one number a
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

from screamingface_engine.benchmarks.healthbench.scoring import clipped_mean, unclipped_mean
from screamingface_engine.benchmarks.healthbench.subset import WORST30_CASE_IDS, subset_sha
from screamingface_engine.benchmarks.healthbench.variant import case_ids_sha, healthbench_benchmark
from screamingface_engine.benchmarks.provenance import FrontierScore, HumanBaseline, NotPublished

# Both benchmarks grade the same physician-written rubrics over the same public dataset; they
# differ in which conversations they serve and how they average the per-case scores.
HEALTHBENCH_DATASET_URL = "https://huggingface.co/datasets/openai/healthbench"

# ── Benchmark 1 — the worst-30% challenge ────────────────────────────────────────────────
WORST30_VARIANT, HEALTHBENCH_WORST30 = healthbench_benchmark(
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
    # WHY the HF ids, not the Engine Case ids: this benchmark's identity IS the frozen
    # worst-30% selection out of the dataset, so its fingerprint is taken over the
    # dataset's own stable row ids (subset.py).
    selection_sha=subset_sha(),
    # By construction the 30% of the benchmark top models score worst on (OME-1257).
    difficulty="hard",
    focus="Clinical safety, hardest cases",
    dataset_url=HEALTHBENCH_DATASET_URL,
    # Benchmark Provenance (OME-1455); sources in the PR 3 table.
    paper_url="https://arxiv.org/abs/2604.27470",
    authors="Hicks et al., 2026",
    citation=(
        "@misc{hicks2026healthbenchprofessionalevaluatinglarge,\n"
        "      title={HealthBench Professional: Evaluating Large Language Models on R"
        "eal Clinician Chats}, \n"
        "      author={Rebecca Soskin Hicks and Mikhail Trofimov and Dominick Lim and"
        " Rahul K. Arora and Foivos Tsimpourlas and Preston Bowman and Michael Sharma"
        "n and Chi Tong and Kavin Karthik and Arnav Dugar and Akshay Jagadeesh and Kh"
        "aled Saab and Johannes Heidecke and Ashley Alexander and Nate Gross and Kara"
        "n Singhal},\n"
        "      year={2026},\n"
        "      eprint={2604.27470},\n"
        "      archivePrefix={arXiv},\n"
        "      primaryClass={cs.CL},\n"
        "      url={https://arxiv.org/abs/2604.27470}, \n"
        "}"
    ),
    harness_url=(
        "https://github.com/openai/simple-evals/blob/652c89d0ca9df547706735883097e9537d40dc47/healthbench_eval.py"
    ),
    license="MIT",
    license_note=(
        "openai/healthbench-professional dataset card; the simple-evals harness is MIT. The "
        "worst-30% selection is ours, frozen (subset.py)."
    ),
    content_warning=(
        "Clinical conversations, including emergencies and self-harm scenarios, graded on safety."
    ),
    human_baseline=NotPublished(
        reason=("the worst-30% selection is ours; no human was measured on it"),
    ),
    frontier_score=NotPublished(
        reason=(
            "the worst-30% selection is ours (frozen in subset.py); nothing is published on it"
        ),
    ),
    notebook="08_healthbench",
)

# ── Benchmark 2 — the full professional variant ─────────────────────────────────────────────
# INVARIANT: the pinned dataset revision holds exactly this many professional rows, and
# ``prepare.emit`` refuses to prepare anything else — a dataset that grew or shrank would
# otherwise ship a differently-sized benchmark under this identity.
PROFESSIONAL_CASE_COUNT = 525
# WHY a contiguous range: Engine Case ids ARE the 1-based positions prepare.py numbers by,
# so "the whole benchmark" is every position. A gap here would silently make this a subset.
PROFESSIONAL_CASE_IDS = tuple(range(1, PROFESSIONAL_CASE_COUNT + 1))

PROFESSIONAL_VARIANT, HEALTHBENCH_PROFESSIONAL = healthbench_benchmark(
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
    # WHY the Case ids, not dataset row ids: this benchmark's selection IS "every position in
    # the prepared file", so the id list is the honest fingerprint of what it serves.
    selection_sha=case_ids_sha(PROFESSIONAL_CASE_IDS),
    # Physician-rubric clinical safety: published frontier scores sit well under
    # saturation, so the full benchmark is frontier work too (OME-1257).
    difficulty="hard",
    focus="Clinical safety, full official exam",
    dataset_url=HEALTHBENCH_DATASET_URL,
    # Benchmark Provenance (OME-1455); sources in the PR 3 table.
    paper_url="https://arxiv.org/abs/2604.27470",
    authors="Hicks et al., 2026",
    citation=(
        "@misc{hicks2026healthbenchprofessionalevaluatinglarge,\n"
        "      title={HealthBench Professional: Evaluating Large Language Models on R"
        "eal Clinician Chats}, \n"
        "      author={Rebecca Soskin Hicks and Mikhail Trofimov and Dominick Lim and"
        " Rahul K. Arora and Foivos Tsimpourlas and Preston Bowman and Michael Sharma"
        "n and Chi Tong and Kavin Karthik and Arnav Dugar and Akshay Jagadeesh and Kh"
        "aled Saab and Johannes Heidecke and Ashley Alexander and Nate Gross and Kara"
        "n Singhal},\n"
        "      year={2026},\n"
        "      eprint={2604.27470},\n"
        "      archivePrefix={arXiv},\n"
        "      primaryClass={cs.CL},\n"
        "      url={https://arxiv.org/abs/2604.27470}, \n"
        "}"
    ),
    harness_url=(
        "https://github.com/openai/simple-evals/blob/652c89d0ca9df547706735883097e9537d40dc47/healthbench_eval.py"
    ),
    license="MIT",
    license_note="openai/healthbench-professional dataset card; the simple-evals harness is MIT.",
    content_warning=(
        "Clinical conversations, including emergencies and self-harm scenarios, graded on safety."
    ),
    # Human baseline: Specialty-matched physicians writing responses with unbounded time and….
    human_baseline=HumanBaseline(score=0.437, source_url="https://arxiv.org/abs/2604.27470"),
    # Frontier score: HealthBench Professional rubric score, length-adjusted (primary metric….
    frontier_score=FrontierScore(
        score=0.647,
        model="GPT-6 Astra",
        source_url="https://deploymentsafety.openai.com/gpt-6-astra",
        as_of="2026-09",
    ),
    notebook="08_healthbench",
)

# AIDEV-NOTE: a benchmark exposes exactly two names — the `Benchmark` (what the runtime installs:
# `.id`, `.revision`, `.routes.*`, `.case_ids`, `.mean`) and the `Benchmark` (what the
# catalogue publishes). Reach a route through `<BENCHMARK>_EXAM.routes.cases`, never through a
# module-level alias: an unprefixed constant here would silently mean one of the two.
__all__ = [
    "HEALTHBENCH_PROFESSIONAL",
    "HEALTHBENCH_WORST30",
    "PROFESSIONAL_CASE_COUNT",
    "PROFESSIONAL_CASE_IDS",
    "PROFESSIONAL_VARIANT",
    "WORST30_VARIANT",
]
