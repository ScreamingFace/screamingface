"""The Run registry's vocabulary (E5 P1 spec §4.1, §4.2, R5).

FEATURE: first-class Runs (OME-1785). Plain frozen values: the registry port speaks them, the
Tortoise adapter maps rows onto them, and the routes map them onto the wire.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, NewType, get_args

from screamingface_engine.runs.ids import RUN_ID_PATTERN

CandidateState = Literal[
    "pending", "scheduled", "running", "succeeded", "failed", "timed_out", "stopped", "lost"
]
RunState = Literal["running", "complete", "partial", "errored", "canceled", "interrupted"]

CANDIDATE_STATES: frozenset[str] = frozenset(get_args(CandidateState))
RUN_STATES: frozenset[str] = frozenset(get_args(RunState))
# INVARIANT (spec R4): a terminal Candidate never moves again; the first terminal outcome wins.
_TERMINAL_CANDIDATE: frozenset[CandidateState] = frozenset(
    {"succeeded", "failed", "timed_out", "stopped", "lost"}
)

OwnerKey = NewType("OwnerKey", str)


def owner_key(owner: str) -> OwnerKey:
    """The stored owner (spec D6): sha256 of the verified email, trimmed and lowercased.

    WHY normalise: the edge can pass one person's email in different cases on different login
    paths; without it one researcher would own two disjoint sets of Runs. Local mode passes
    `local`, which normalises to itself.
    """
    # WHY NFC and casefold, not lower(): one email can arrive in composed or decomposed Unicode,
    # and `lower()` misses folds such as "ß" == "SS".
    normalised = unicodedata.normalize("NFC", owner.strip()).casefold()
    if not normalised:
        raise ValueError("a Run owner must not be blank")
    return OwnerKey(hashlib.sha256(normalised.encode()).hexdigest())


def is_aware(value: object) -> bool:
    """Whether ``value`` is a timezone-aware datetime. WHY `utcoffset()`: a tzinfo that gives no
    offset still makes a naive datetime, which `tzinfo is None` would miss."""
    return isinstance(value, datetime) and value.utcoffset() is not None


def is_terminal_candidate(state: CandidateState) -> bool:
    """Whether a Candidate is done: it never moves again (spec R4)."""
    if state not in CANDIDATE_STATES:
        # WHY: an unknown state read as non-terminal would let a later outcome overwrite a
        # finished Candidate; fail loudly, as `is_terminal_run` and `derive_state` do.
        raise ValueError(f"unknown Candidate state: {state!r}")
    return state in _TERMINAL_CANDIDATE


def is_terminal_run(state: RunState) -> bool:
    """Whether a Run is finished. Only `running` is not."""
    if state not in RUN_STATES:
        # WHY: the Literal is erased at runtime; an unknown state must fail loudly, not read as
        # finished.
        raise ValueError(f"unknown Run state: {state!r}")
    return state != "running"


@dataclass(frozen=True, slots=True)
class RunSpec:
    """What `POST /runs` registers (spec §4.1). Candidates are named in evaluation order; a
    start names one by its index in this tuple (`X-SF-Run-Candidate`)."""

    client_key: str
    benchmark: str
    case_count: int
    candidates: tuple[str, ...]
    client_version: str

    def __post_init__(self) -> None:
        # AIDEV-NOTE: domain rules only. Request types (a list of strings, an integer count) are
        # the route schema's to check (E8), before a RunSpec is built.
        names = tuple(name.strip() for name in self.candidates)
        if not names:
            raise ValueError("a Run needs at least one Candidate")
        if not all(names):
            raise ValueError("a Candidate name must not be blank")
        # WHY compared stripped: names that differ only by surrounding space read as one name.
        if len(set(names)) != len(names):
            raise ValueError("Candidate names must be unique within a Run")
        if self.case_count < 0:
            raise ValueError("case_count must not be negative")
        # INVARIANT: what was validated is what is stored, so `client_key` compares exactly.
        object.__setattr__(self, "candidates", names)
        for field in ("client_key", "benchmark", "client_version"):
            value = getattr(self, field).strip()
            if not value:
                raise ValueError(f"{field} must not be blank")
            object.__setattr__(self, field, value)


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    """One Candidate of a Run. `attempt_id` is the bound topic, once the Candidate has started."""

    index: int
    name: str
    state: CandidateState
    attempt_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cost_usd: Decimal | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class RunRecord:
    """A Run as the registry returns it. It never carries the owner (spec §4.1)."""

    id: str
    state: RunState
    created_at: datetime
    finished_at: datetime | None
    benchmark: str
    case_count: int
    candidates: tuple[CandidateRecord, ...]


# WHY a cap: one `GET /runs` page is one bounded query, never a scan of an owner's whole history.
MAX_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class RunQuery:
    """`GET /runs` filters. `cursor` is the last Run id of the previous page; pages run newest
    first by `created_at`, the id breaking ties."""

    state: RunState | None = None
    since: datetime | None = None
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        if self.state is not None and self.state not in RUN_STATES:
            raise ValueError(f"state must be one of {sorted(RUN_STATES)}")
        if not 1 <= self.limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if self.since is not None and not is_aware(self.since):
            raise ValueError("since must be a timezone-aware datetime")
        if self.cursor is not None and not RUN_ID_PATTERN.fullmatch(self.cursor):
            raise ValueError("cursor must be a Run id")


@dataclass(frozen=True, slots=True)
class RunPage:
    runs: tuple[RunRecord, ...]
    next_cursor: str | None
