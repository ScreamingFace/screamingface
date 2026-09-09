"""GDPval's verdict dialect — a shape declaration over the shared spine parser.

The parsing work (JSON recovery, strict-boolean gate, identity stamping, mandatory audit
trail — OME-1023's raw-reply rule included) lives once in ``spine.verdict`` (OME-1099);
this module keeps only what is GDPval's to own: its schema string and its prose reason
vocabulary, which reaches the wire on rejected verdicts and must stay byte-identical.
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

SCHEMA = "screamingface.gdpval-rubric-verdict.v1"

# INVARIANT: only a REAL JSON boolean counts (statuses=None) — a judge that cannot follow
# the reply format has not demonstrably followed the grading instruction either, and a
# lenient cast would silently convert that confusion into a scored answer.
SHAPE = VerdictShape(
    schema=SCHEMA,
    status_field="criteria_met",
    statuses=None,
    explanation_required=False,
    reasons={
        "empty": "empty judge reply",
        "not_json": "judge reply is not a JSON object",
        "not_object": "judge reply is not a JSON object",
        "missing_status": "judge reply lacks criteria_met",
        "bad_status": "judge reply criteria_met is not a JSON boolean",
    },
)


def bind(raw: str, *, case_id: int, rubric_id: int, producer_id: str) -> dict[str, object]:
    """Turn one raw judge reply into GDPval's verdict record, or a documented failure."""

    require_positive_int(case_id, "case_id")
    require_positive_int(rubric_id, "rubric_id")
    return parse_verdict(
        raw,
        shape=SHAPE,
        identity=(("case_id", case_id), ("rubric_id", rubric_id)),
        producer_id=producer_id,
    ).record()


__all__ = ["SCHEMA", "bind", "binding_key", "call"]
