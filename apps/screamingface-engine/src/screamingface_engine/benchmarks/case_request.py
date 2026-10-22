"""Explicit Candidate request metadata, decoded before model input is evaluated.

A Candidate Invocation is LLM mode (spec ``2026-10-20-url4-benchmark-expression`` R2): its
quoted intent IS the model input, and its sources are what the Engine needs around the call —
the Case identity, its selected position, and the Recipe to evaluate::

    /benchmarks/candidate?web_search=false&q=(
      case_id=$item.id, case_index=$index, case_count='3', recipe=$candidate
    )!'$item.input'

url4 packs unweighted named sources into the endpoint context as ``name: value`` lines, in
source order (``url4/dag/nodes/_shared.py`` ``_gather``), with no escaping.

INVARIANT: ``recipe`` is the LAST source, so everything after ``recipe: `` is the Recipe — a
Recipe holding new lines or ``name: `` text can never be misread as a fact.
"""

from __future__ import annotations

from dataclasses import dataclass

from screamingface_engine.benchmarks.contract import CaseId, validate_case_id
from url4.core.errors import ResolutionError
from url4.peer.server import Request

RECIPE_SOURCE = "recipe"
CASE_FACTS = ("case_id", "case_index", "case_count")
# The fact lines a request may carry before the Recipe: none (a plain call), the identity
# alone, or the identity with its selected position.
_FACT_SHAPES = ((), CASE_FACTS[:1], CASE_FACTS)


@dataclass(frozen=True, slots=True)
class CandidateRequest:
    """One decoded Candidate Invocation: the model input, the Recipe, and the Case facts."""

    input_text: str
    recipe: str
    case_id: CaseId | None
    position: tuple[int, int] | None
    """1-based selected position and the selected count; ``None`` for an unnumbered call."""


def candidate_request(request: Request) -> CandidateRequest:
    """Decode the packed sources of one Candidate Invocation; refuse any other shape."""

    try:
        facts, recipe = _split(request.context or "")
        if not recipe.strip():
            raise ValueError("the Recipe is empty")
        case_id = None if not facts else validate_case_id(facts["case_id"])
        position = (
            _position(facts["case_index"], facts["case_count"]) if "case_index" in facts else None
        )
    except (TypeError, ValueError) as exc:
        raise ResolutionError(
            "Invalid Candidate Invocation sources", code="candidate_contract_error", permanent=True
        ) from exc
    return CandidateRequest(
        input_text=request.intent, recipe=recipe, case_id=case_id, position=position
    )


def _split(context: str) -> tuple[dict[str, str], str]:
    """The fact lines (by name) and the Recipe text, from the packed context."""

    head, marker, recipe = context.partition(f"{RECIPE_SOURCE}: ")
    if not marker or (head and not head.endswith("\n")):
        raise ValueError("the Recipe must be the last source")
    lines = head.split("\n")[:-1] if head else []
    names = tuple(line.partition(": ")[0] for line in lines)
    if names not in _FACT_SHAPES or any(": " not in line for line in lines):
        raise ValueError("unexpected Candidate Invocation sources")
    return {name: line.partition(": ")[2] for name, line in zip(names, lines, strict=True)}, recipe


def _position(raw_index: str, raw_count: str) -> tuple[int, int]:
    if not all(value.isascii() and value.isdigit() for value in (raw_index, raw_count)):
        raise ValueError("invalid case position")
    position, count = int(raw_index) + 1, int(raw_count)
    if not 1 <= position <= count <= 9_007_199_254_740_991:
        raise ValueError("invalid case position")
    return position, count


CASE_ATTEMPT_PARAM = "attempt"
"""The Candidate Invocation param naming Attempt 2 or later of a Case (OME-1458). Engine call
metadata, never model input: the adapter strips it before the policy check."""


def candidate_attempt(request: Request) -> int | None:
    """Decode the Attempt number of a Candidate Invocation; None for Attempt 1 and plain calls.

    WHY 2 or more only: Attempt 1 is spelled by absence, so the one-Attempt expression of every
    existing Benchmark renders unchanged and one Attempt can never be spelled two ways.
    """

    raw = request.params.get(CASE_ATTEMPT_PARAM)
    if raw is None:
        return None
    if not raw.isascii() or not raw.isdigit() or int(raw) < 2:
        raise ResolutionError(
            "Invalid Candidate Invocation attempt", code="candidate_contract_error", permanent=True
        )
    return int(raw)
