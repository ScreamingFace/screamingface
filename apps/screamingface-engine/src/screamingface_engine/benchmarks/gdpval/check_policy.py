"""Versioned semantics for GDPval's mid-run draft-feedback offer — ``gdpval-pass.v1``.

This file is the WHOLE GDPval check adapter: it declares where the rubric keeps its criteria,
which judge grades a draft, what "passed" means, and which sanitized vocabulary the feedback may
speak. It contains no marking logic of its own.

Two positions worth reviewing, both named so they can be bumped deliberately:

**Threshold 0.5, on the CLAMPED score.** A per-case GDPval score is unclamped and can go negative
— rubrics carry penalties down to -85 — while a check's ``satisfaction`` must live in [0, 1], so
the component clamps and a negative total lands at 0.0, which can never pass. The bar sits at
half the winnable points. It is PROVISIONAL: unlike DRACO's 0.7, which was set against known
baselines, no candidate has yet been measured on this benchmark, so the first real runs should
confirm the bar separates drafts worth iterating from drafts worth stopping. A bar set too high
turns ``max_rounds`` from a cost cap into a fixed price.

**Severity feedback, not areas.** The prepared rubric keeps only the criterion text and its
points; GDPval's upstream ``tags`` and ``author_type`` columns are dropped at build time, so
there is no safe category vocabulary to name. Feedback therefore says only WHETHER the shortfall
was a missing requirement or a violated prohibition. If that proves too thin to steer a loop, the
honest fix is richer prepared rubric metadata, not leaking criteria.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.gdpval.revision_inputs import JUDGE_MODEL, JUDGE_PARAMS
from screamingface_engine.benchmarks.gdpval.variant import CHECK_CRITERION
from screamingface_engine.benchmarks.rubric_draft_feedback import (
    RubricDraftFeedback,
    RubricFileLayout,
)

CHECK_THRESHOLD = 0.5

GDPVAL_DRAFT_FEEDBACK = RubricDraftFeedback(
    label="GDPval",
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
    # A GDPval Case input is a chat envelope — the work request plus its flattened reference
    # text — so the judge reads the transcript rather than raw JSON.
    question="chat_envelope",
)

__all__ = ["CHECK_THRESHOLD", "GDPVAL_DRAFT_FEEDBACK"]
