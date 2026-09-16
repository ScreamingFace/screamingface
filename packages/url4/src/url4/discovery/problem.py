"""The RFC 9457 problem a refused config becomes.

One shape for both carriers: a caller who sent headers and a caller who sent an attach
frame get the same `type`, the same codes and the same pointers, because by the time this
runs the two have already converged on one payload.
"""

from __future__ import annotations

from collections.abc import Sequence

from url4.discovery.scope import Violation

PROBLEM_TYPE = "https://url4.ai/problems/config-rejected"
"""Stable and dereferenceable-looking, per RFC 9457 §4.2: clients branch on `type`, so it
is part of the contract and does not move."""

PROBLEM_MEDIA_TYPE = "application/problem+json"


def config_rejected(violations: Sequence[Violation], *, instance: str | None = None) -> dict:
    """Build the 400 body. EVERY violation is listed, not just the first.

    A caller who sent four bad values should need one round trip to learn about all four;
    reporting them one at a time turns a fixable request into a guessing game.
    """
    return {
        "type": PROBLEM_TYPE,
        "title": "Configuration rejected",
        "status": 400,
        "detail": _detail(violations),
        **({"instance": instance} if instance else {}),
        # RFC 9457 §3.2 extension member. The array is the machine-readable half; `detail`
        # is the same information for a human reading a log.
        "violations": [v.as_dict() for v in violations],
    }


def _detail(violations: Sequence[Violation]) -> str:
    if len(violations) == 1:
        return violations[0].detail
    return f"{len(violations)} configuration values were rejected"


__all__ = ["PROBLEM_MEDIA_TYPE", "PROBLEM_TYPE", "config_rejected"]
