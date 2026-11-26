"""The pure routing policy, version 1 (contracts C6, Unit 5.2).

FEATURE: Router Recipe extension. One decision over classifier evidence serves both adapters: the
Router DAG (``router-policy``: ``best``/``exact`` x ``one``/``all``) and named profiles
(``unique-argmax-v1``). The adapters turn the result into a C5 draft or a profile answer.

INVARIANT: pure. No HTTP, url4, configuration or recorder import; no clock and no I/O. The policy
never sorts, normalizes or invents scores, never promotes a runner-up, never retries, and a
classifier failure never runs the default.
INVARIANT: ``selected`` holds zero-based candidate indices in classifier order (returned order
for scores, reply order for llm, KEYWORDS order for regex).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

# WHY from the C5 codec: the policy's outcome, reason and parse words are the ones the record
# carries, so one vocabulary keeps a decision and its record from drifting apart.
from screamingface_engine.router_decision import Outcome, Reason
from screamingface_engine.router_vocabulary import Parse, best_reason, exact_reason

ROUTER_EVIDENCE_INVALID = "router_evidence_invalid"
ROUTING_AMBIGUOUS = "routing_ambiguous"
ROUTING_INVALID_SCORES = "routing_invalid_scores"

Phase = Literal["classify", "decide"]


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """The one internal policy value both C2 policy variants decode into."""

    kind: Literal["router-policy", "unique-argmax-v1"]
    match: Literal["best", "exact"] = "best"
    select: Literal["one", "all"] = "one"


@dataclass(frozen=True, slots=True)
class ScoringEvidence:
    """A scoring classifier's result, scores in returned order (not yet trusted)."""

    model: str
    contract: str
    scores: Sequence[tuple[str, object]]


@dataclass(frozen=True, slots=True)
class SelectorEvidence:
    """An llm or regex selector's reading of the question."""

    source: Literal["llm", "regex"]
    labels: tuple[str, ...]
    unknown: tuple[str, ...]
    parse: Parse


@dataclass(frozen=True, slots=True)
class ClassifierFailure:
    """The classifier call failed: its bounded code and permanence."""

    code: str
    permanent: bool


Evidence = ScoringEvidence | SelectorEvidence | ClassifierFailure


@dataclass(frozen=True, slots=True)
class PolicyFailure:
    phase: Phase
    code: str
    permanent: bool


@dataclass(frozen=True, slots=True)
class PolicyResult:
    """The C6 result: an outcome and reason, or a failure; never both."""

    outcome: Outcome
    reason: Reason | None
    selected: tuple[int, ...]
    unknown_labels: tuple[str, ...]
    failure: PolicyFailure | None = None


def decide(
    rule: PolicyRule, evidence: Evidence, *, labels: Sequence[str], has_default: bool
) -> PolicyResult:
    """Apply C6 to ``evidence`` for the candidate ``labels`` (in candidate order)."""

    if isinstance(evidence, ClassifierFailure):
        return _failed("classify", evidence.code, permanent=evidence.permanent)
    if rule.kind == "unique-argmax-v1":
        return _unique_argmax(evidence, labels)
    reader = _best if rule.match == "best" else _exact
    return reader(rule, evidence, labels, has_default)


def _best(
    _rule: PolicyRule, evidence: Evidence, labels: Sequence[str], has_default: bool
) -> PolicyResult:
    scores = _numbers(evidence)
    if scores is None or not _complete(scores, labels):
        return _invalid()
    unknown = tuple(label for label, _ in scores if label not in labels)
    reason = best_reason(scores, unknown)
    if reason != "unique_max":
        return _fallback(reason, unknown, has_default)
    (leader,) = _leaders(scores)
    return PolicyResult("selected", "unique_max", (labels.index(leader),), unknown)


def _exact(
    rule: PolicyRule, evidence: Evidence, labels: Sequence[str], has_default: bool
) -> PolicyResult:
    if not isinstance(evidence, SelectorEvidence) or not _consistent(evidence, labels):
        return _invalid()
    # INVARIANT: one C6 reason table, shared with the C5 codec that re-checks it.
    reason = exact_reason(rule.select, evidence.parse, len(evidence.labels))
    if reason != "exact":
        return _fallback(reason, evidence.unknown, has_default)
    selected = tuple(labels.index(label) for label in evidence.labels)
    return PolicyResult("selected", "exact", selected, evidence.unknown)


def _unique_argmax(evidence: Evidence, labels: Sequence[str]) -> PolicyResult:
    scores = _numbers(evidence)
    if scores is None or sorted(label for label, _ in scores) != sorted(labels):
        return _failed("decide", ROUTING_INVALID_SCORES)
    leaders = _leaders(scores)
    if len(leaders) != 1:
        return _failed("decide", ROUTING_AMBIGUOUS)
    return PolicyResult("selected", None, (labels.index(leaders[0]),), ())


def _numbers(evidence: Evidence) -> list[tuple[str, float]] | None:
    """The scores as numbers, or ``None`` unless each is a finite non-boolean in [0, 1]."""

    if not isinstance(evidence, ScoringEvidence) or not evidence.scores:
        return None
    numbers: list[tuple[str, float]] = []
    for label, score in evidence.scores:
        if not (
            isinstance(score, int | float)
            and not isinstance(score, bool)
            and math.isfinite(score)
            and 0 <= score <= 1
        ):
            return None
        numbers.append((label, float(score)))
    return numbers


def _leaders(scores: Sequence[tuple[str, float]]) -> list[str]:
    top = max(score for _, score in scores)
    return [label for label, score in scores if score == top]


def _complete(scores: Sequence[tuple[str, float]], labels: Sequence[str]) -> bool:
    """Unique returned labels, every candidate label present."""

    returned = [label for label, _ in scores]
    return len(set(returned)) == len(returned) and set(labels) <= set(returned)


def _consistent(evidence: SelectorEvidence, labels: Sequence[str]) -> bool:
    """The selector evidence is one its source can produce, and names only candidates."""

    recognized, unknown, parse = evidence.labels, evidence.unknown, evidence.parse
    allowed: tuple[Parse, ...] = (
        ("ok", "no_match") if evidence.source == "regex" else ("ok", "unrecognized", "unparsed")
    )
    return (
        parse in allowed
        and len(set(recognized)) == len(recognized)
        and all(label in labels for label in recognized)
        and (parse != "ok" or (bool(recognized) and not unknown))
        and (parse != "unrecognized" or bool(unknown))
        and (parse != "no_match" or not recognized)
        and (evidence.source == "llm" or not unknown)
    )


def _fallback(reason: Reason, unknown: tuple[str, ...], has_default: bool) -> PolicyResult:
    return PolicyResult("default" if has_default else "no_selection", reason, (), unknown)


def _invalid() -> PolicyResult:
    return _failed("decide", ROUTER_EVIDENCE_INVALID)


def _failed(phase: Phase, code: str, *, permanent: bool = True) -> PolicyResult:
    return PolicyResult("failed", None, (), (), PolicyFailure(phase, code, permanent))


__all__ = [
    "ROUTER_EVIDENCE_INVALID",
    "ROUTING_AMBIGUOUS",
    "ROUTING_INVALID_SCORES",
    "ClassifierFailure",
    "Evidence",
    "Outcome",
    "Parse",
    "Phase",
    "PolicyFailure",
    "PolicyResult",
    "PolicyRule",
    "Reason",
    "ScoringEvidence",
    "SelectorEvidence",
    "decide",
]
