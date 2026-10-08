from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

OperationalOutcome = Literal["connected", "insufficient_credits", "needs_reauth"]
OPERATIONAL_OUTCOMES = frozenset[OperationalOutcome](
    {"connected", "insufficient_credits", "needs_reauth"}
)


@dataclass(frozen=True)
class DispatchObservation:
    blob_id: UUID
    credential_revision: int
    dispatch_sequence: int


@dataclass(frozen=True)
class CredentialOperationalState:
    blob_id: UUID
    credential_revision: int
    next_dispatch_sequence: int
    last_outcome_sequence: int
    outcome: OperationalOutcome | None
    observed_at: datetime | None


__all__ = [
    "CredentialOperationalState",
    "DispatchObservation",
    "OPERATIONAL_OUTCOMES",
    "OperationalOutcome",
]
