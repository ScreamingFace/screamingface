"""DRACO's verdict dialect — a shape declaration over the shared spine parser.

INVARIANT: Case, criterion, sequence, and producer identity come from Engine-owned URL4
bindings; the Judge supplies only the verdict payload and cannot relabel its Evidence.

The parsing work lives once in ``spine.verdict`` (OME-1099); this module keeps what is
DRACO's to own: its ``MET``/``UNMET`` enum dialect with a required explanation, its
reason vocabulary, and its own ``call``/``binding_key`` — DRACO's binding carries a
``sequence`` and an opaque criterion id, unlike the rubric boards' integer pair.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.draco.validation import require_text
from screamingface_engine.benchmarks.spine.verdict import (
    VerdictShape,
    parse_verdict,
    require_positive_int,
)
from url4 import Node, RelExpr, Text, render

SCHEMA = "screamingface.criterion-verdict.v1"

SHAPE = VerdictShape(
    schema=SCHEMA,
    status_field="criterion_status",
    statuses=("MET", "UNMET"),
    explanation_required=True,
    reasons={
        "empty": "empty",
        "not_json": "invalid_json",
        "not_object": "invalid_shape",
        "bad_explanation": "invalid_shape",
        "missing_status": "invalid_shape",
        "bad_status": "invalid_status",
    },
)


def call(
    judge: Node,
    criterion_id: str,
    *,
    case_id: str,
    sequence: int,
    route: str,
) -> RelExpr:
    """Wrap a Judge call with the case and criterion identities already known by the Engine."""

    if not isinstance(criterion_id, str) or not criterion_id:
        raise ValueError("criterion_id must be non-empty URL4 text")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be non-empty URL4 text")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("sequence must be a positive integer")
    if not isinstance(route, str) or not route.startswith("/"):
        raise ValueError("criterion verdict route must be an absolute URL4 path")
    return RelExpr(
        path=route,
        context=render(judge, check=False),
        # The case id is numeric, so the first colon is an unambiguous boundary even when an
        # opaque criterion id itself contains colons. The model never sees or supplies either id.
        intent=Text(f"{case_id}:{sequence}:{criterion_id}"),
    )


def binding_key(value: str) -> tuple[int, int, str]:
    """Decode ``case_id:sequence:criterion_id`` while preserving criterion-id colons."""

    case_text, first, remainder = value.partition(":")
    sequence_text, second, criterion_id = remainder.partition(":")
    if not first or not second:
        raise ValueError("criterion verdict binding must contain case_id:sequence:criterion_id")
    try:
        case_id = int(case_text)
        sequence = int(sequence_text)
    except ValueError as exc:
        raise ValueError(
            "criterion verdict case_id and sequence must be positive integers"
        ) from exc
    if case_id < 1:
        raise ValueError("criterion verdict case_id must be a positive integer")
    if sequence < 1:
        raise ValueError("criterion verdict sequence must be a positive integer")
    return case_id, sequence, require_text(criterion_id, "criterion_id")


def bind(
    raw: str,
    *,
    case_id: int,
    criterion_id: str,
    sequence: int,
    producer_id: str,
) -> dict[str, object]:
    """Validate ``raw`` and attach Engine-known case and criterion identifiers."""

    require_positive_int(case_id, "case_id")
    require_positive_int(sequence, "sequence")
    selected_id = require_text(criterion_id, "criterion_id")
    selected_producer = require_text(producer_id, "producer_id")
    return parse_verdict(
        raw,
        shape=SHAPE,
        identity=(("case_id", case_id), ("criterion_id", selected_id), ("sequence", sequence)),
        producer_id=selected_producer,
    ).record()


__all__ = ["SCHEMA", "bind", "binding_key", "call"]
