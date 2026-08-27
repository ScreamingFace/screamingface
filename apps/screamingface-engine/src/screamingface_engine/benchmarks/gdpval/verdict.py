"""Parse one judge reply into a verdict record, or a documented failure. No model calls here.

The judge is asked for ``{"explanation": ..., "criteria_met": true/false}``. Models sometimes
answer with something else, and a judge can never be trusted to say WHICH criterion it was
grading. This module handles both problems deterministically:

- ``binding_key`` decodes the ``case_id:rubric_id`` intent the Engine threads through the route.
- ``bind`` parses one reply, stamping the Engine-known ids onto it, or returns a ``valid: false``
  record. Either way the raw reply is kept for audit (OME-1023).

INVARIANT: only a REAL JSON boolean counts. A string ``"true"`` or a ``1`` is an invalid reply,
never a lenient yes — a judge that cannot follow the reply format has not demonstrably followed
the grading instruction either, and a lenient cast would silently convert that confusion into a
scored answer.

INVARIANT: ``bind`` RETURNS failures instead of raising. The caller decides what a failure means
— retry first (the expression re-resolves the nested judge call for a fresh sample), then fail
the Case loudly with this record as the evidence.
"""

from __future__ import annotations

import json
from typing import Any

SCHEMA = "screamingface.gdpval-rubric-verdict.v1"


def call(judge: object, *, case_id: str, rubric_id: str, route: str, retry: int):
    """Wrap a judge call so a parse retry redraws a FRESH judge sample.

    The problem: a judge sometimes answers with something that is not the JSON we asked for.
    That is still a SUCCESSFUL model call, so ``;retry=`` on the judge itself would never fire —
    there is no error to retry.

    The trick: nest the judge INSIDE the verdict call as its context, and put ``;retry=`` on the
    verdict. The flow becomes:

        judge answers -> verdict route parses -> garbage? -> verdict RAISES ->
        ``;retry=`` re-resolves the whole nested expression -> the judge is asked AGAIN ->
        a fresh sample (temperature 0.2) that may parse this time.

    INVARIANT: the judge never sees ``case_id`` or ``rubric_id``. The Engine writes both into
    the verdict route's intent, so identity is stamped rather than echoed.
    """

    from url4 import Node, RelExpr, Text, render, src

    if not isinstance(judge, Node):
        raise ValueError("verdict call needs a URL4 judge node")
    if not isinstance(route, str) or not route.startswith("/"):
        raise ValueError("rubric verdict route must be an absolute URL4 path")
    if isinstance(retry, bool) or not isinstance(retry, int) or retry < 0:
        raise ValueError("retry must be a non-negative integer")
    return src(
        RelExpr(
            path=route,
            context=render(judge, check=False),
            intent=Text(f"{case_id}:{rubric_id}"),
        ),
        name="verdict",
        weight=0.0,
        retry=retry,
    )


def binding_key(value: str) -> tuple[int, int]:
    """Decode ``case_id:rubric_id`` — both Engine-assigned positive integers."""

    case_text, separator, rubric_text = value.partition(":")
    if not separator:
        raise ValueError("rubric verdict binding must contain case_id:rubric_id")
    try:
        case_id = int(case_text)
        rubric_id = int(rubric_text)
    except ValueError as exc:
        raise ValueError("rubric verdict case_id and rubric_id must be positive integers") from exc
    if case_id < 1 or rubric_id < 1:
        raise ValueError("rubric verdict case_id and rubric_id must be positive integers")
    return case_id, rubric_id


def bind(raw: str, *, case_id: int, rubric_id: int, producer_id: str) -> dict[str, object]:
    """Turn one raw judge reply into a verdict record, or a documented failure.

    AIDEV-NOTE: identity is stamped by the ENGINE, not read from the reply. The judge never saw
    ``case_id`` or ``rubric_id``; if a reply contains them they are ignored, because a model that
    invented an id would otherwise be able to redirect a verdict onto another criterion.
    """

    _require_positive(case_id, "case_id")
    _require_positive(rubric_id, "rubric_id")
    if not isinstance(producer_id, str) or not producer_id.strip():
        raise ValueError("producer_id must be a non-empty string")

    record: dict[str, object] = {
        "schema": SCHEMA,
        "case_id": case_id,
        "rubric_id": rubric_id,
        "producer_type": "model",
        "producer_id": producer_id.strip(),
        # WHY keep the raw text on EVERY verdict, not only rejected ones (OME-1023): a disputed
        # verdict on a paid run is unfalsifiable unless the reply that produced it can be
        # re-read — and the original bytes, not the fence-stripped parse, are what expose a
        # lossy parse. HealthBench and DRACO persist it the same way.
        "raw_output": raw,
    }
    decoded = _decode_object(raw)
    reason = _invalid_reason(raw, decoded)
    if reason is not None:
        return {**record, "valid": False, "reason": reason}
    assert decoded is not None  # narrowed by _invalid_reason returning None
    return {
        **record,
        "valid": True,
        "criteria_met": decoded["criteria_met"],
        "explanation": str(decoded.get("explanation", "")),
    }


def _require_positive(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")


def _decode_object(raw: object) -> dict[str, Any] | None:
    """Recover the judge's JSON object from however it chose to present it.

    AIDEV-NOTE: the pinned judge (gemini-3.1-pro-preview) wraps its JSON in a ```json fence —
    measured 2026-08-25, and it failed every Case at rubric 1 until this was handled. DRACO hit
    the same behaviour with the same model and strips fences for the same reason.

    INVARIANT: recovering the object is NOT the same as relaxing what counts as a verdict.
    `_invalid_reason` still demands a real JSON boolean, so a fenced reply carrying
    `"criteria_met": "true"` remains invalid.
    """

    if not isinstance(raw, str) or not raw.strip():
        return None
    text = _without_fences(raw.strip())
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = _first_json_value(text)
    return decoded if isinstance(decoded, dict) else None


def _without_fences(text: str) -> str:
    if "```" not in text:
        return text
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("```")
    ).strip()


def _first_json_value(text: str) -> Any:
    """The first JSON object embedded in prose, or None.

    WHY a fallback rather than strictness: the alternative is spending two retries and failing
    the Case on a reply that plainly contains the verdict.
    """

    start = text.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return value


def _invalid_reason(raw: object, decoded: dict[str, Any] | None) -> str | None:
    """The first reason this reply is not a verdict, or ``None`` when it is one.

    INVARIANT: order matters — each check assumes the previous ones passed. The bool check must
    come last AND be an ``isinstance(..., bool)``: ``isinstance(True, int)`` is True in Python,
    so a truthiness test would accept a ``1`` as a verdict.
    """

    checks = (
        (not isinstance(raw, str) or not raw.strip(), "empty judge reply"),
        (decoded is None, "judge reply is not a JSON object"),
        (decoded is not None and "criteria_met" not in decoded, "judge reply lacks criteria_met"),
        (
            decoded is not None
            and "criteria_met" in decoded
            and not isinstance(decoded["criteria_met"], bool),
            "judge reply criteria_met is not a JSON boolean",
        ),
    )
    return next((reason for failed, reason in checks if failed), None)


__all__ = ["SCHEMA", "bind", "binding_key", "call"]
