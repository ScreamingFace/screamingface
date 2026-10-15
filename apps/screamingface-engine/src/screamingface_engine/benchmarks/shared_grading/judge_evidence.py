"""The one judge-verdict parser every rubric benchmark configures. No model calls here.

FEATURE: one shared grading code per benchmark (OME-1024; this module lands OME-1099 and
delivers the typed record OME-1025 asked for).
STORY: as the next rubric benchmark, I declare my verdict dialect and get parsing for free —
I cannot drift a copy, and I cannot drop an audit field.

Mental model: a judge replies in text that *should* be JSON, and can never be trusted to
say WHICH criterion it was grading. Turning that reply into evidence is the same work on
every benchmark — recover the JSON from however the judge presented it, demand the benchmark's
verdict field, stamp the Engine-known identity on, keep the raw reply for audit. Only the
paperwork differs per benchmark, so the work lives here once and each benchmark supplies a
``JudgeReplyFormat``: its schema string, its verdict field (an enum status or a strict JSON
boolean), and its reason vocabulary — merged parsers, unchanged wire records.

Worked example (the bool dialect): raw ``'```json\\n{"criteria_met": true}\\n```'`` →
fences stripped → JSON recovered → ``criteria_met`` is a real boolean → a valid
``JudgeEvidence`` whose ``raw_output`` still holds the ORIGINAL fenced bytes. The same reply
with ``"criteria_met": "true"`` is invalid (``bad_status``) — recovery never softens what
counts as a verdict.

INVARIANT (OME-1023): every audit field on ``JudgeEvidence`` is a required constructor
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

# Canonical failure codes, in detection order. Each benchmark's shape maps every code it can
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
class JudgeReplyFormat:
    """One benchmark's verdict dialect — arguments, not code.

    Args (as fields):
        schema: the benchmark's wire schema string, stamped on every record.
        status_field: the reply field carrying the verdict (``criterion_status``,
            ``criteria_met``).
        statuses: the accepted enum values (``("MET", "UNMET")``), or ``None`` for a
            strict JSON boolean — ``"true"``/``1`` never count (simple-evals parity).
        explanation_required: whether a reply without a text ``explanation`` is invalid
            (draco) or tolerated as empty text (the rubric benchmarks).
        reasons: canonical failure code → this benchmark's wire ``reason`` string.
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
class JudgeEvidence:
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
    #: The benchmark-dialect verdict fields when valid (status + explanation); empty otherwise.
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


def parse_judge_evidence(
    raw: str,
    *,
    shape: JudgeReplyFormat,
    identity: tuple[tuple[str, int | str], ...],
    producer_id: str,
) -> JudgeEvidence:
    """Turn one raw judge reply into a ``JudgeEvidence``, or a documented failure.

    Stages, in execution order:

    1. Recover the JSON from however the judge presented it (fenced, prose-prefixed, bare).
    2. Walk the failure checks in canonical order; the first hit becomes the benchmark's
       ``reason`` string via the shape's vocabulary.
    3. A clean reply yields the benchmark-dialect payload; either way the ORIGINAL bytes ride
       along as ``raw_output``.

    INVARIANT: this RETURNS failures instead of raising. The caller (a runtime's verdict
    route) decides what a failure means — retry first, then fail the Case loudly with
    this record as the evidence.
    """

    require_text(producer_id, "producer_id")
    decoded = extract_json_object(raw)
    code = _failure_code(shape, raw, decoded)
    if code is not None:
        return JudgeEvidence(
            schema=shape.schema,
            identity=identity,
            producer_id=producer_id,
            raw_output=raw,
            valid=False,
            payload=(),
            reason=shape.reasons[code],
        )
    assert isinstance(decoded, Mapping)  # narrowed by _failure_code returning None
    return JudgeEvidence(
        schema=shape.schema,
        identity=identity,
        producer_id=producer_id,
        raw_output=raw,
        valid=True,
        payload=_payload(shape, decoded),
        reason=None,
    )


def _failure_code(shape: JudgeReplyFormat, raw: object, decoded: object) -> str | None:
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


def _payload(shape: JudgeReplyFormat, decoded: Mapping[str, Any]) -> tuple[tuple[str, object], ...]:
    """The benchmark-dialect verdict fields off a reply `_failure_code` already accepted."""

    status: object = decoded[shape.status_field]
    explanation = decoded.get("explanation")
    if shape.statuses is None:
        # Bool dialect tolerates a missing/non-text explanation as empty text; the enum
        # dialect already required it (`bad_explanation`), so it is a str here.
        text = explanation if isinstance(explanation, str) else ""
        return ((shape.status_field, status), ("explanation", text))
    return (("explanation", explanation), (shape.status_field, status))


# --- JSON recovery — shared by every dialect ---------------------------------------------------


def extract_json_object(raw: object) -> Any:
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


def require_text(value: object, label: str) -> str:
    """One non-empty text field, unnormalized — evidence needs an attributable producer."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


__all__ = [
    "JudgeEvidence",
    "JudgeReplyFormat",
    "parse_judge_evidence",
    "extract_json_object",
    "require_text",
]
