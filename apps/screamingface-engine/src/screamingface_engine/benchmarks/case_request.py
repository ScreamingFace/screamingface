"""Explicit candidate request metadata, decoded before model input is evaluated."""

import json

from screamingface_engine.benchmarks.contract import CaseId, validate_case_id
from url4.core.errors import ResolutionError
from url4.peer.server import Request

CONTEXT_FORMAT = "case-v1"
CONTEXT_FORMAT_PARAM = "context_format"


def candidate_input(request: Request) -> tuple[str, CaseId | None]:
    if "context_format" not in request.params:
        return request.context or "", None
    try:
        if request.params["context_format"] != CONTEXT_FORMAT:
            raise ValueError("unsupported candidate context format")
        payload = json.loads(request.context)
        if not isinstance(payload, dict) or set(payload) not in (
            {"input", "case_id"},
            {"input", "case_id", "case_index", "case_count"},
        ):
            raise ValueError("expected candidate input and case_id")
        case_id = validate_case_id(payload["case_id"])
        value = payload["input"]
        if not isinstance(value, str | dict):
            raise ValueError("candidate input must be text or an object")
        # WHY: URL4 StructNode serializes object contexts with json.dumps defaults.
        # Matching it here preserves the pre-envelope model input byte for byte.
        return json.dumps(value) if isinstance(value, dict) else value, case_id
    except (TypeError, ValueError) as exc:
        raise ResolutionError(
            "Invalid candidate case context", code="candidate_contract_error", permanent=True
        ) from exc


def candidate_position(request: Request) -> tuple[int, int] | None:
    """Decode explicit selection metadata; plain candidate requests remain unnumbered."""
    if "context_format" not in request.params:
        return None
    payload = json.loads(request.context)
    if "case_index" not in payload:
        return None
    try:
        values = (payload["case_index"], payload["case_count"])
        if any(
            type(value) not in {int, str} or not str(value).isascii() or not str(value).isdigit()
            for value in values
        ):
            raise ValueError("invalid case position")
        index, count = map(int, values)
        position = index + 1
        if not 1 <= position <= count <= 9_007_199_254_740_991:
            raise ValueError("invalid case position")
        return position, count
    except (TypeError, ValueError) as exc:
        raise ResolutionError(
            "Invalid candidate case position", code="candidate_contract_error", permanent=True
        ) from exc


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
