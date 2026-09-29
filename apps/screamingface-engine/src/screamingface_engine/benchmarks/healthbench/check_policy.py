"""Versioned semantics for HealthBench's mid-run draft-feedback offer — `healthbench-pass.v1`.

The deletion test for the `rubric_check` component lives here: this file is the WHOLE
HealthBench check adapter. It declares where the rubric keeps its items, which judge
grades a draft, what "passed" means, and which sanitized vocabulary the feedback may
speak — and contains no marking logic of its own.

Two positions worth reviewing, both named so they can be bumped deliberately:

**Threshold 0.5, on the CLAMPED score.** HealthBench's published per-case score is
deliberately unclamped and can go negative (a draft that trips enough safety penalties
is worse than an empty one). A check's `satisfaction` must live in [0, 1], so the
component clamps — and a negative total lands at 0.0, which can never pass. The bar
itself sits at half the available positive points rather than DRACO's 0.7 because this
is the WORST-30% subset: strong baselines average negative here, so a 0.7 bar would
never trigger and `max_rounds` would stop being a cost cap and become a fixed price.

**Severity feedback, not areas.** HealthBench's prepared rubric keeps only the criterion
text and its points — the upstream theme/category columns are dropped at build time, so
there is no safe category vocabulary to name. Feedback therefore says only WHETHER the
shortfall was a missing requirement or a violated prohibition. If that proves too thin to
steer a loop, the honest fix is richer prepared rubric metadata, not leaking criteria.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.healthbench.revision_inputs import (
    CHECK_CRITERION,
    JUDGE_MODEL,
    JUDGE_PARAMS,
)
from screamingface_engine.benchmarks.rubric_draft_feedback import (
    RubricDraftFeedback,
    RubricFileLayout,
)

CHECK_THRESHOLD = 0.5

HEALTHBENCH_DRAFT_FEEDBACK = RubricDraftFeedback(
    label="HealthBench",
    criterion=CHECK_CRITERION,
    threshold=CHECK_THRESHOLD,
    # Flat `items`, points-weighted, and no area vocabulary at all.
    shape=RubricFileLayout(
        layout="flat",
        items="items",
        id_field="rubric_id",
        text_field="criterion",
        weight_field="points",
    ),
    judge_model=JUDGE_MODEL,
    judge_params=JUDGE_PARAMS,
    feedback="severity",
    # A HealthBench Case input is a chat envelope, so the judge reads the flattened
    # transcript rather than raw JSON.
    question="chat_envelope",
)

__all__ = ["CHECK_THRESHOLD", "HEALTHBENCH_DRAFT_FEEDBACK"]
