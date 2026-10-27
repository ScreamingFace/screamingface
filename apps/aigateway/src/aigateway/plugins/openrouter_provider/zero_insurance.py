"""Proof for OpenRouter Zero Completion Insurance (OME-1446, amended by OME-1746).

FEATURE: cost of intelligence (OME-1287). A native HTTP 429 is a rejection with no output, and
Zero Completion Insurance guarantees no OpenRouter-credit charge for it.

INVARIANT: the proof reads only the facts that tell if OpenRouter billed the call: no output, no
billed work in ``usage``, no non-zero money field anywhere, and no paid pipeline stage. Every
other field of the reply is ignored, so a new or changed field never makes the cost unknown
(owner decision 2026-10-27, spec 2026-10-06-OME-1446 amendment).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .billing_facts import reports_a_charge, usage_shows_billed_work

# WHY: these stages run a paid plugin or server tool. A prepared request without plugins or tools
# should never show one, but if it does, the stage can be billed.
_PAID_STAGE_TYPES = frozenset({"plugin", "server_tools"})
_OUTPUT_FIELDS = ("choices", "output", "content")


def _pipeline_has_no_paid_stage(raw_response: Mapping[str, Any]) -> bool:
    router = raw_response.get("openrouter_metadata")
    pipeline = router.get("pipeline") if isinstance(router, Mapping) else None
    if not isinstance(pipeline, list):
        return True
    return all(
        not isinstance(stage, Mapping) or stage.get("type") not in _PAID_STAGE_TYPES
        for stage in pipeline
    )


def proves_insured_zero(
    raw_response: Mapping[str, Any],
    *,
    http_status: int | None,
    request_has_potential_auxiliary_charge: bool | None,
) -> bool:
    """Whether the request and the 429 reply prove that OpenRouter billed nothing."""
    return (
        http_status == 429
        and request_has_potential_auxiliary_charge is False
        and all(raw_response.get(field) in (None, "", [], ()) for field in _OUTPUT_FIELDS)
        and not usage_shows_billed_work(raw_response)
        and not reports_a_charge(raw_response)
        and _pipeline_has_no_paid_stage(raw_response)
    )


__all__ = ["proves_insured_zero"]
