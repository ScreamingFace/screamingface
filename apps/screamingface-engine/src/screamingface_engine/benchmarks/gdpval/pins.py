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
# build rather than silently bake a smaller exam.
#
# WHY THIS revision specifically: it is "Release GDPval v2 (rubrics + deliverables)" (2026-02-10),
# the commit that ADDED `rubric_json`. This board grades those rubrics, so any earlier revision is
# unusable to it.
#
# AIDEV-NOTE: do NOT copy the pin from UKGovernmentBEIS/inspect_evals
# (`a3848a2a812d5d4d0f08003fac3c8eac40805962`, 2025-09-25). That reference implementation never
# reads the rubrics — it uploads deliverables to OpenAI's grading service — so its pin predates
# them and carries `rubric_json: null` on all 220 rows. Baking from it fails the build at case 1,
# which is how this was found.
DATASET_REVISION = "11e7900cdcac61bc4daf59e65feb238acda98fbf"

# WHY: prepare.py's output participates in the answer key; bump this when the preparer's emission
# rules change — reference delimiter, envelope shape, rubric mapping — so a rebuilt image can
# never serve old routes a different key.
PREPARER_REVISION = "text-subset-v1"

# WHY this judge: GDPval's official grading is blinded expert PAIRWISE comparison against a human
# professional's deliverable — unreachable here — and OpenAI's automated stand-in is a hosted
# service, not a model we can call. So the judge is OUR choice, and this board reuses DRACO's pin
# rather than inventing a third: one judge across two rubric-graded boards is one variable to
# reason about when scores move. Named as a deviation in the board description.
JUDGE_MODEL = "openrouter/google/gemini-3.1-pro-preview"
JUDGE_PARAMS = (
    # INVARIANT: grading is retrieval-free. The same model may serve as a Candidate elsewhere;
    # its judge call must not search, and sending no search field keeps the request eligible for
    # the exact-response cache.
    ("web_search", "false"),
    # WHY non-zero, and why that matters here: an unparseable reply is retried by re-resolving
    # the nested judge call. At temperature 0 the retry would re-send identical bytes and fail
    # identically; 0.2 redraws a fresh sample while staying near-deterministic. Copied from
    # DRACO, where the same reasoning applies.
    ("temperature", "0.2"),
    # Engine-side safety bound. A verdict is a sentence and a boolean; this only stops a
    # runaway generation from billing without limit.
    ("max_tokens", "4096"),
)
# WHY 2: the reference loops forever on malformed replies. A GDPval run makes ~4,498 judge calls
# per candidate, so an unbounded retry on a systematically broken prompt would burn a run's
# budget before anyone noticed. Two redraws clear transient garbage; a third failure is a real
# defect and should fail the Case loudly.
JUDGE_RETRIES = 2

__all__ = [
    "DATASET",
    "DATASET_REVISION",
    "JUDGE_MODEL",
    "JUDGE_PARAMS",
    "JUDGE_RETRIES",
    "PREPARER_REVISION",
]
