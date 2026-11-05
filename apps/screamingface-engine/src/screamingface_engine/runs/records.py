"""The Run registry's vocabulary (E5 P1 spec §4.1, §4.2, R5).

FEATURE: first-class Runs (OME-1785). Plain frozen values: the registry port speaks them, the
Tortoise adapter maps rows onto them, and the routes map them onto the wire.
"""

from __future__ import annotations

import hashlib
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

# The widths of the registry's columns (`runs/models/`). WHY checked here: Postgres refuses a value
# too long for its column while SQLite keeps it, so the rule both databases share comes first.
MAX_CLIENT_KEY_LENGTH = 128
MAX_BENCHMARK_LENGTH = 255
MAX_CLIENT_VERSION_LENGTH = 64
MAX_CANDIDATE_NAME_LENGTH = 255
MAX_CANDIDATES = 256
MAX_CASE_COUNT = 2**31 - 1
_TEXT_LIMITS = {
    "client_key": MAX_CLIENT_KEY_LENGTH,
    "benchmark": MAX_BENCHMARK_LENGTH,
    "client_version": MAX_CLIENT_VERSION_LENGTH,
}


def owner_key(owner: str) -> OwnerKey:
    """The stored owner (spec D6): sha256 of the verified email, trimmed and lowercased.

    WHY this rule: it is aigateway's account key (`CloudflareIdentity.username`), so one verified
    email is one identity in both services. Local mode passes `local`, which is unchanged by it.
    """
    # WHY no Unicode normalisation: the edge sends the email as UTF-8 bytes, which Starlette reads
    # as Latin-1 text, so a non-ASCII address reaches here as that text and no fold can merge it
    # with an ASCII one; the route test pins that over HTTP (spec D6).
    normalised = owner.strip().lower()
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
        names = _candidate_names(self.candidates)
        if not 0 <= self.case_count <= MAX_CASE_COUNT:
            raise ValueError(f"case_count must be between 0 and {MAX_CASE_COUNT}")
        # INVARIANT: what was validated is what is stored, so `client_key` compares exactly.
        object.__setattr__(self, "candidates", names)
        for field, limit in _TEXT_LIMITS.items():
            object.__setattr__(self, field, _text(field, getattr(self, field), limit))


def _candidate_names(candidates: tuple[str, ...]) -> tuple[str, ...]:
    names = tuple(name.strip() for name in candidates)
    if not names:
        raise ValueError("a Run needs at least one Candidate")
    if len(names) > MAX_CANDIDATES:
        raise ValueError(f"a Run has at most {MAX_CANDIDATES} Candidates")
    if not all(names):
        raise ValueError("a Candidate name must not be blank")
    if any(len(name) > MAX_CANDIDATE_NAME_LENGTH for name in names):
        raise ValueError(f"a Candidate name is at most {MAX_CANDIDATE_NAME_LENGTH} characters")
    if any("\x00" in name for name in names):
        raise ValueError("a Candidate name has no NUL")
    # WHY compared stripped: names that differ only by surrounding space read as one name.
    if len(set(names)) != len(names):
        raise ValueError("Candidate names must be unique within a Run")
    return names


def _text(field: str, value: str, limit: int) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} must not be blank")
    if len(stripped) > limit:
        raise ValueError(f"{field} is at most {limit} characters")
    # WHY: PostgreSQL text cannot hold a NUL, where SQLite can; one rule for both stores.
    if "\x00" in stripped:
        raise ValueError(f"{field} has no NUL")
    return stripped


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
