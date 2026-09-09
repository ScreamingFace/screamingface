"""HealthBench's verdict dialect — a shape declaration over the shared spine parser.

The parsing work (JSON recovery, strict-boolean gate, identity stamping, mandatory audit
trail) lives once in ``spine.verdict`` (OME-1099); this module keeps only what is
HealthBench's to own: its schema string, its reason vocabulary, and the strict-bool
``criteria_met`` dialect that mirrors the reference ``grade_sample`` loop
(https://github.com/openai/simple-evals/blob/main/healthbench_eval.py).
"""

from __future__ import annotations

from screamingface_engine.benchmarks.spine.verdict import (
    VerdictShape,
    parse_verdict,
    require_positive_int,
)
from screamingface_engine.benchmarks.spine.verdict import (
    rubric_binding_key as binding_key,
)
from screamingface_engine.benchmarks.spine.verdict import (
    rubric_verdict_call as call,
)

SCHEMA = "screamingface.healthbench-rubric-verdict.v1"

# INVARIANT: only a REAL JSON boolean counts (statuses=None) — a string "true" or a 1 is
# an invalid reply, never a lenient yes; the reference loops until `label is True or
# label is False`, so anything else must trigger a retry, not a verdict.
SHAPE = VerdictShape(
    schema=SCHEMA,
    status_field="criteria_met",
    statuses=None,
    explanation_required=False,
    reasons={
        "empty": "empty",
        "not_json": "invalid_json",
        "not_object": "invalid_shape",
        "missing_status": "invalid_criteria_met",
        "bad_status": "invalid_criteria_met",
    },
)


def bind(raw: str, *, case_id: int, rubric_id: int, producer_id: str) -> dict[str, object]:
    """Turn one raw judge reply into HealthBench's verdict record, or a documented failure."""

    require_positive_int(case_id, "case_id")
    require_positive_int(rubric_id, "rubric_id")
    return parse_verdict(
        raw,
        shape=SHAPE,
        identity=(("case_id", case_id), ("rubric_id", rubric_id)),
        producer_id=producer_id,
    ).record()


__all__ = ["SCHEMA", "bind", "binding_key", "call"]
