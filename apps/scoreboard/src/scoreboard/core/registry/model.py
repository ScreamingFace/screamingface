"""Value types of the system registry.

FEATURE: OME-1307 (E14) — a *system* is a named, fingerprinted recipe; a *revision* is one
fingerprint of it (erd.md §2.3).

INVARIANT: pure. Standard library only (C11-SB-2). Every type is frozen: the adapters map a
database row into one of these and never hand a Tortoise object to the core.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

BoardVisibility = Literal["public", "private"]
ResolutionOutcome = Literal["new", "existing", "renamed_notice", "revision", "private"]


@dataclass(frozen=True)
class SystemIdentity:
    fingerprint: str  # 64 lowercase hex
    candidate_url4: str  # canonical text; sha256(candidate_url4) == fingerprint


@dataclass(frozen=True)
class SystemRef:
    id: UUID
    name: str
    owner: str


@dataclass(frozen=True)
class RevisionRef:
    id: UUID
    system: SystemRef
    revision: int
    fingerprint: str
    candidate_url4: str
    created_at: datetime


@dataclass(frozen=True)
class SystemAlreadyNamed:
    name: str
    owner: str  # RAW identity. SB-submit publishes it with the SubmittedBy rule.
    code: Literal["system_already_named"] = "system_already_named"


@dataclass(frozen=True)
class Resolution:
    # PRD §3.1 shape `Resolution(system, revision, notice | None)`, plus `outcome` and `identity`.
    outcome: ResolutionOutcome
    identity: SystemIdentity
    system: SystemRef | None  # None only when outcome == "private"
    revision: RevisionRef | None  # None only when outcome == "private"
    notice: SystemAlreadyNamed | None


@dataclass(frozen=True)
class NamePin:
    name: str


@dataclass(frozen=True)
class RevisionPin:
    name: str
    revision: int


@dataclass(frozen=True)
class DatePin:
    name: str
    at: datetime  # UTC, tz-aware


Pin = NamePin | RevisionPin | DatePin
