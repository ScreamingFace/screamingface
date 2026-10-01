"""Versioned semantics for DRACO's mid-run draft-feedback offer — `draco-pass.v1`.

DRACO grades; it does not pass or fail. A corrective loop needs a boolean, so this
module *invents* one — and because an invented boolean decides which draft a run
submits, every input to it is named and versioned here: the threshold, the rubric
shape the check reads, the judge it asks, and the feedback vocabulary it may speak.

`CHECK_CRITERION` rides in the check route, so a different criterion is a different
route — visible in the manifest, in every compiled Candidate url4, and in the recipe
topology of every run record. Changing any constant here without bumping the name
silently changes what "passed" meant on past leaderboard rows.

WHY one batched pass, when canonical DRACO judges one criterion per call: canonical
grading spends 5 passes x N criteria (median 38) per case — at loop rates (members x
rounds) that is hundreds of judge calls per case. The check is a STEERING instrument,
not the scorer: canonical grading still produces the published number.

The marking WORK lives in `benchmarks.rubric_draft_feedback`; this file is DRACO's paperwork.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.draco.definition import (
    CHECK_CRITERION,
    JUDGE_MODEL,
    JUDGE_PARAMS,
)
from screamingface_engine.benchmarks.rubric_draft_feedback import (
    RubricDraftFeedback,
    RubricFileLayout,
)

# Normalized weighted score in [0, 1]; >= passes. 0.7 is the reviewed v1 position:
# high enough that a passing draft satisfies the heavily-weighted criteria, low
# enough that a loop terminates on real answers rather than grinding to max_rounds.
CHECK_THRESHOLD = 0.7

# DRACO keeps criteria in weighted axis sections; the axis names are what sanitized
# feedback is allowed to say.
DRACO_RUBRIC_SHAPE = RubricFileLayout(
    layout="sections",
    items="sections",
    nested="criteria",
    id_field="id",
    text_field="requirement",
    weight_field="weight",
    area_fields=("id", "title"),
)


# The check judge asks for one whole-rubric verdict array in a single call, and the
# judge is a reasoning model whose thinking tokens count against max_tokens. Canonical
# grading's 4096 pin (one criterion per call) starves that batched reply — the judge
# spends the whole budget thinking and the verdict JSON never completes. The check
# keeps its own budget; JUDGE_PARAMS stays untouched because it feeds REVISION.
CHECK_JUDGE_PARAMS = tuple(
    (name, "32768" if name == "max_tokens" else value) for name, value in JUDGE_PARAMS
)

DRACO_DRAFT_FEEDBACK = RubricDraftFeedback(
    label="DRACO",
    criterion=CHECK_CRITERION,
    threshold=CHECK_THRESHOLD,
    shape=DRACO_RUBRIC_SHAPE,
    judge_model=JUDGE_MODEL,
    judge_params=CHECK_JUDGE_PARAMS,
    feedback="areas",
    question="text",
)

__all__ = ["CHECK_CRITERION", "CHECK_THRESHOLD", "DRACO_DRAFT_FEEDBACK"]
