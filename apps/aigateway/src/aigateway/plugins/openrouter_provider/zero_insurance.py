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

from .billing_facts import (
    is_empty,
    pipeline_has_paid_stage,
    reports_a_charge,
    usage_shows_billed_work,
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
        # WHY `choices` too: a 429 has no choice at all; any choice is output.
        and all(is_empty(raw_response.get(field)) for field in ("choices", "output", "content"))
        and not usage_shows_billed_work(raw_response)
        and not pipeline_has_paid_stage(raw_response)
        and not reports_a_charge(raw_response)
    )


__all__ = ["proves_insured_zero"]
