"""Explicit candidate request metadata, decoded before model input is evaluated."""

import json

from screamingface_engine.benchmarks.contract import CaseId, validate_case_id
from url4.core.errors import ResolutionError
from url4.peer.server import Request

CONTEXT_FORMAT = "case-v1"


def candidate_input(request: Request) -> tuple[str, CaseId | None]:
    if "context_format" not in request.params:
        return request.context or "", None
    try:
        if request.params["context_format"] != CONTEXT_FORMAT:
            raise ValueError("unsupported candidate context format")
        payload = json.loads(request.context)
        if not isinstance(payload, dict) or set(payload) not in (
            {"input", "case_id"},
            {"input", "case_id", "case_position", "case_count"},
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
    if "case_position" not in payload:
        return None
    try:
        values = (payload["case_position"], payload["case_count"])
        if any(
            type(value) not in {int, str} or not str(value).isascii() or not str(value).isdigit()
            for value in values
        ):
            raise ValueError("invalid case position")
        position, count = map(int, values)
        if not 1 <= position <= count <= 9_007_199_254_740_991:
            raise ValueError("invalid case position")
        return position, count
    except (TypeError, ValueError) as exc:
        raise ResolutionError(
            "Invalid candidate case position", code="candidate_contract_error", permanent=True
        ) from exc
