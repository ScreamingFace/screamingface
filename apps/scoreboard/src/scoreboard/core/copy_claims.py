"""The port for the claim of a frozen copy (OME-1947).

The scoreboard tells the AI Gateway that a Score uses a frozen copy. The gateway then keeps that
copy. The adapter `scoreboard.gateway_copy_claims` implements the port.

INVARIANT: this module imports no HTTP library, no model and no route (contracts.md K10).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class ClaimResult(StrEnum):
    """The result of one claim. Each answer that is not exact is UNAVAILABLE."""

    CLAIMED = "claimed"
    ALREADY = "already"
    NOT_SEALED = "not_sealed"
    ABANDONED = "abandoned"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


KEPT: frozenset[ClaimResult] = frozenset({ClaimResult.CLAIMED, ClaimResult.ALREADY})
"""The results that let a Score keep its frozen copy."""


class CopyClaims(Protocol):
    """Sends the claim of one frozen copy to the AI Gateway."""

    async def claim(self, copy_id: str) -> ClaimResult: ...

    async def aclose(self) -> None: ...
