"""The one judge-verdict parser every rubric board configures. No model calls here.

FEATURE: one grading spine per benchmark (OME-1024; this module lands OME-1099 and
delivers the typed record OME-1025 asked for).
STORY: as the next rubric board, I declare my verdict dialect and get parsing for free —
I cannot drift a copy, and I cannot drop an audit field.

Mental model: a judge replies in text that *should* be JSON, and can never be trusted to
say WHICH criterion it was grading. Turning that reply into evidence is the same work on
every board — recover the JSON from however the judge presented it, demand the board's
verdict field, stamp the Engine-known identity on, keep the raw reply for audit. Only the
paperwork differs per board, so the work lives here once and each board supplies a
``VerdictShape``: its schema string, its verdict field (an enum status or a strict JSON
boolean), and its reason vocabulary — merged parsers, unchanged wire records.

Worked example (the bool dialect): raw ``'```json\\n{"criteria_met": true}\\n```'`` →
fences stripped → JSON recovered → ``criteria_met`` is a real boolean → a valid
``Verdict`` whose ``raw_output`` still holds the ORIGINAL fenced bytes. The same reply
with ``"criteria_met": "true"`` is invalid (``bad_status``) — recovery never softens what
counts as a verdict.

INVARIANT (OME-1023): every audit field on ``Verdict`` is a required constructor
argument — no defaults — so a caller omitting ``raw_output`` fails typecheck and runtime
construction. ``raw_output: ""`` was type-valid with the wrong meaning; absence is not.

INVARIANT: identity is stamped by the ENGINE, never read from the reply. A model that
invented an id could otherwise redirect a verdict onto another criterion.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Canonical failure codes, in detection order. Each board's shape maps every code it can
# hit onto its own wire ``reason`` string, so merging the parsers changed no records.
_FAILURE_CODES = (
    "empty",
    "not_json",
    "not_object",
    "bad_explanation",
    "missing_status",
    "bad_status",
)


@dataclass(frozen=True, slots=True)
class VerdictShape:
    """One board's verdict dialect — arguments, not code.

    Args (as fields):
        schema: the board's wire schema string, stamped on every record.
        status_field: the reply field carrying the verdict (``criterion_status``,
            ``criteria_met``).
        statuses: the accepted enum values (``("MET", "UNMET")``), or ``None`` for a
            strict JSON boolean — ``"true"``/``1`` never count (simple-evals parity).
        explanation_required: whether a reply without a text ``explanation`` is invalid
            (draco) or tolerated as empty text (the rubric boards).
        reasons: canonical failure code → this board's wire ``reason`` string.
    """

    schema: str
    status_field: str
    statuses: tuple[str, ...] | None
    explanation_required: bool
    reasons: Mapping[str, str]

    def __post_init__(self) -> None:
        required = {code for code in _FAILURE_CODES if code != "bad_explanation"}
        if self.explanation_required:
            required.add("bad_explanation")
        missing = required - set(self.reasons)
        if missing:
            raise ValueError(f"verdict shape must name a reason for {sorted(missing)}")


@dataclass(frozen=True, slots=True)
class Verdict:
    """One judge reply bound to Engine identity — the audit trail is mandatory.

    INVARIANT: NO field has a default (pinned by test). Every call site must hand over
    the full audit trail, so a parser cannot silently drop ``raw_output`` again.
    """

    schema: str
    #: Engine-stamped identity fields in wire order, e.g. ``(("case_id", 1), ("rubric_id", 2))``.
    identity: tuple[tuple[str, int | str], ...]
    producer_id: str
    #: The judge's ORIGINAL bytes — never the fence-stripped parse; a lossy parse is
    #: exactly what the audit trail exists to expose.
    raw_output: str
    valid: bool
    #: The board-dialect verdict fields when valid (status + explanation); empty otherwise.
    payload: tuple[tuple[str, object], ...]
    reason: str | None

    def __post_init__(self) -> None:
        if self.valid is (self.reason is not None):
            raise ValueError("a verdict is either valid or carries a reason, never both")

    def record(self) -> dict[str, object]:
        """Project into the wire dict the runtimes persist — byte-identical to the old copies."""

        value: dict[str, object] = {
            "schema": self.schema,
            **dict(self.identity),
            "producer_type": "model",
            "producer_id": self.producer_id,
            "valid": self.valid,
            "raw_output": self.raw_output,
        }
        if self.valid:
            value.update(self.payload)
        else:
            value["reason"] = self.reason
        return value


def parse_verdict(
    raw: str,
    *,
    shape: VerdictShape,
    identity: tuple[tuple[str, int | str], ...],
    producer_id: str,
) -> Verdict:
    """Turn one raw judge reply into a ``Verdict``, or a documented failure.

    Stages, in execution order:

    1. Recover the JSON from however the judge presented it (fenced, prose-prefixed, bare).
    2. Walk the failure checks in canonical order; the first hit becomes the board's
       ``reason`` string via the shape's vocabulary.
    3. A clean reply yields the board-dialect payload; either way the ORIGINAL bytes ride
       along as ``raw_output``.

    INVARIANT: this RETURNS failures instead of raising. The caller (a runtime's verdict
    route) decides what a failure means — retry first, then fail the Case loudly with
    this record as the evidence.
    """

    require_text(producer_id, "producer_id")
    decoded = recovered_object(raw)
    code = _failure_code(shape, raw, decoded)
    if code is not None:
        return Verdict(
            schema=shape.schema,
            identity=identity,
            producer_id=producer_id,
            raw_output=raw,
            valid=False,
            payload=(),
            reason=shape.reasons[code],
        )
    assert isinstance(decoded, Mapping)  # narrowed by _failure_code returning None
    return Verdict(
        schema=shape.schema,
        identity=identity,
        producer_id=producer_id,
        raw_output=raw,
        valid=True,
        payload=_payload(shape, decoded),
        reason=None,
    )


def _failure_code(shape: VerdictShape, raw: object, decoded: object) -> str | None:
    """The first canonical reason this reply is not a verdict, or None when it is one.

    INVARIANT: order matters — each check assumes the previous ones passed, and the
    boolean check must be identity (`is True / is False`), never truthiness:
    ``isinstance(True, int)`` is True in Python, so a ``1`` would otherwise pass.
    """

    def accepted_status(value: object) -> bool:
        if shape.statuses is None:
            return value is True or value is False
        return value in shape.statuses

    is_object = isinstance(decoded, Mapping)
    reply: Mapping[str, Any] = decoded if isinstance(decoded, Mapping) else {}
    checks = (
        (not isinstance(raw, str) or not raw.strip(), "empty"),
        (decoded is None, "not_json"),
        (not is_object, "not_object"),
        (
            shape.explanation_required and not isinstance(reply.get("explanation"), str),
            "bad_explanation",
        ),
        (shape.status_field not in reply, "missing_status"),
        (not accepted_status(reply.get(shape.status_field)), "bad_status"),
    )
    return next((code for failed, code in checks if failed), None)


def _payload(shape: VerdictShape, decoded: Mapping[str, Any]) -> tuple[tuple[str, object], ...]:
    """The board-dialect verdict fields off a reply `_failure_code` already accepted."""

    status: object = decoded[shape.status_field]
    explanation = decoded.get("explanation")
    if shape.statuses is None:
        # Bool dialect tolerates a missing/non-text explanation as empty text; the enum
        # dialect already required it (`bad_explanation`), so it is a str here.
        text = explanation if isinstance(explanation, str) else ""
        return ((shape.status_field, status), ("explanation", text))
    return (("explanation", explanation), (shape.status_field, status))


# --- JSON recovery — shared by every dialect and the check surface -----------------------


def recovered_object(raw: object) -> Any:
    """The judge's JSON value from however it chose to present it, or None.

    AIDEV-NOTE: the pinned rubric judge (gemini-3.1-pro-preview) wraps its JSON in a
    ```json fence — measured 2026-08-25; unhandled, it failed every Case at rubric 1.
    WHY the prose fallback rather than strictness: the alternative is burning retries and
    failing the Case on a reply that plainly contains the verdict.
    """

    if not isinstance(raw, str) or not raw.strip():
        return None
    text = _without_fences(raw.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _first_json_value(text, "{")


def recovered_array(reply: str) -> list[object] | None:
    """The first JSON array embedded in a judge reply, or None — the check surface's shape."""

    if not isinstance(reply, str):
        return None
    decoded = _first_json_value(_without_fences(reply), "[")
    return decoded if isinstance(decoded, list) else None


def _without_fences(text: str) -> str:
    if "```" not in text:
        return text
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("```")
    ).strip()


def _first_json_value(text: str, opener: str) -> Any:
    start = text.find(opener)
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return value


# --- shared scalar validation ------------------------------------------------------------


def require_positive_int(value: object, label: str) -> int:
    """One Engine-assigned positive integer id, or the field-specific ValueError."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def require_text(value: object, label: str) -> str:
    """One non-empty text field, unnormalized — evidence needs an attributable producer."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


# --- shared rubric wiring (healthbench and gdpval were byte-identical copies) ------------


def rubric_binding_key(value: str) -> tuple[int, int]:
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


def rubric_verdict_call(judge: object, *, case_id: str, rubric_id: str, route: str, retry: int):
    """Wrap a judge call so a parse retry redraws a FRESH judge sample.

    The problem: a garbage reply is still a SUCCESSFUL model call, so ``;retry=`` on the
    judge itself would never fire — there is no error to retry. The trick: nest the judge
    INSIDE the verdict call as its context and put ``;retry=`` on the verdict, so a parse
    failure re-resolves the whole nested expression and re-asks the judge. This is the
    reference's own recovery loop (simple-evals ``grade_sample`` re-asks on bad JSON),
    bounded at ``retry`` attempts instead of forever.

    INVARIANT: the judge never sees ``case_id`` or ``rubric_id`` — the Engine writes both
    into the verdict route's intent, so identity is stamped rather than echoed.
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


__all__ = [
    "Verdict",
    "VerdictShape",
    "parse_verdict",
    "recovered_array",
    "recovered_object",
    "require_positive_int",
    "require_text",
    "rubric_binding_key",
    "rubric_verdict_call",
]
