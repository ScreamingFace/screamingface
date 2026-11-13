"""The Run registry's vocabulary (E5 P1 spec §4.1, §4.2, R5; E5 P2 spec §4.4).

FEATURE: first-class Runs (OME-1785) and a detached Run (OME-1837). Plain frozen values: the
registry port speaks them, the Tortoise adapter maps rows onto them, and the routes map them onto
the wire.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, NewType, get_args

from screamingface_engine.runs.ids import RUN_ID_PATTERN

CandidateState = Literal[
    "pending", "scheduled", "running", "succeeded", "failed", "timed_out", "stopped", "lost"
]
RunState = Literal["running", "complete", "partial", "errored", "canceled", "interrupted"]
# What stopped a Run (E5 P2 spec D12); the first stop's reason is kept.
StopReason = Literal["canceled", "orphaned", "deadline"]
STOP_REASONS: frozenset[str] = frozenset(get_args(StopReason))

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
# A start is one run-queue message and one spec line for its runner, each bounded at 1 MiB (the
# broker's default `max_payload`, `child_protocol.MAX_SPEC_BYTES`). Half of that, counted as
# JSON carries the text, leaves room for the rest of the message. INVARIANT: a Run is never
# registered with a Candidate the Engine could not start.
MAX_START_URL4_BYTES = 512 * 1024
# WHY 320: the longest address RFC 5321 allows (64 + 1 + 255).
MAX_OWNER_EMAIL_LENGTH = 320
_SHA256 = re.compile(r"[0-9a-f]{64}")
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
class CandidateStart:
    """What the Engine needs to start one Candidate after its Client has gone (E5 P2 spec D8):
    the url4 expression and the flags a start carries. The route checks each flag as the start
    route does; this keeps what every start needs."""

    name: str
    url4: str
    answer_seed: int | None = None
    capture: bool = False
    use_cache: bool = True
    replay_frozen_copy: str | None = None

    def __post_init__(self) -> None:
        if not self.url4.strip():
            raise ValueError("a start's url4 must not be blank")
        if not _storable_text(self.url4):
            raise ValueError("a start's url4 has no NUL and no lone surrogate")
        # WHY the cheap bound first: a start is also built on every read, and no character
        # takes more than twelve bytes in JSON (an astral one is two `\uXXXX` halves), so only
        # a long url4 is measured.
        if len(self.url4) * 12 > MAX_START_URL4_BYTES and (
            len(json.dumps(self.url4)) > MAX_START_URL4_BYTES
        ):
            raise ValueError(f"a start's url4 is at most {MAX_START_URL4_BYTES} bytes as JSON")


@dataclass(frozen=True, slots=True)
class ContextRef:
    """The Client's context as the Run keeps it (E5 P2 spec D9b): the blob lives in the
    run-results store, and its checksum and size live on the Run, so the Client can tell a
    context that was replaced in the store."""

    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("a context's sha256 is 64 lowercase hex digits")
        if self.size_bytes < 0:
            raise ValueError("a context's size must not be negative")


@dataclass(frozen=True, slots=True)
class RunSpec:
    """What `POST /runs` registers (spec §4.1). Candidates are named in evaluation order.

    A P2 Run also carries every Candidate's start (E5 P2 spec D1), so the Engine starts them;
    ``run_id`` is the id the route minted to store the context under, and ``deadline`` a detached
    Run's own (the store applies the default when it is absent).
    """

    client_key: str
    benchmark: str
    case_count: int
    candidates: tuple[str, ...]
    client_version: str
    starts: tuple[CandidateStart, ...] = ()
    detach: bool = False
    deadline: timedelta | None = None
    run_id: str | None = None
    owner_email: str | None = None
    context: ContextRef | None = None

    def __post_init__(self) -> None:
        # AIDEV-NOTE: domain rules only. Request types (a list of strings, an integer count) are
        # the route schema's to check (E8), before a RunSpec is built.
        names = _candidate_names(self.candidates)
        if not 0 <= self.case_count <= MAX_CASE_COUNT:
            raise ValueError(f"case_count must be between 0 and {MAX_CASE_COUNT}")
        # INVARIANT: what was validated is what is stored, so `client_key` compares exactly.
        object.__setattr__(self, "candidates", names)
        for name, limit in _TEXT_LIMITS.items():
            object.__setattr__(self, name, _text(name, getattr(self, name), limit))
        self._check_starts(names)
        if self.run_id is not None and not RUN_ID_PATTERN.fullmatch(self.run_id):
            raise ValueError("run_id must be a Run id")
        if self.owner_email is not None:
            email = _text("owner_email", self.owner_email, MAX_OWNER_EMAIL_LENGTH)
            object.__setattr__(self, "owner_email", email)

    def _check_starts(self, names: tuple[str, ...]) -> None:
        if self.starts:
            if tuple(start.name.strip() for start in self.starts) != names:
                raise ValueError("the starts must name the Candidates, in their order")
            # INVARIANT: a start is stored under its Candidate's name, so it compares by that
            # name when the same `client_key` is sent again.
            stored = tuple(
                replace(start, name=name) for start, name in zip(self.starts, names, strict=True)
            )
            object.__setattr__(self, "starts", stored)
        # WHY: only the Engine's driver starts a detached Run's Candidates, and it needs starts.
        if self.detach and not self.starts:
            raise ValueError("detach needs every Candidate's start")
        if self.deadline is not None:
            if not self.detach:
                raise ValueError("a deadline needs detach (E5 P2 spec D11)")
            if self.deadline <= timedelta(0):
                raise ValueError("a deadline must be positive")


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
    if not all(_storable_text(name) for name in names):
        raise ValueError("a Candidate name has no NUL and no lone surrogate")
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
    if not _storable_text(stripped):
        raise ValueError(f"{field} has no NUL and no lone surrogate")
    return stripped


def _storable_text(text: str) -> bool:
    """Whether PostgreSQL text can hold ``text``.

    WHY: it holds neither a NUL nor a lone surrogate (half of a truncated emoji). SQLite keeps a
    surrogate only in a JSON column and fails on it elsewhere; one rule for both stores, so a
    body that can never be stored is a 422, not a 503 that invites a retry or a 500.
    """
    if "\x00" in text:
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    """One Candidate of a Run. `attempt_id` is the bound topic, once the Candidate has started.

    ``start`` and ``record`` are read by `get` only (E5 P2 spec §4.4); every other read leaves
    them `None`.
    """

    index: int
    name: str
    state: CandidateState
    attempt_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cost_usd: Decimal | None = None
    error_code: str | None = None
    start: CandidateStart | None = None
    record: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RunRecord:
    """A Run as the registry returns it. It never carries the owner or the owner's email (spec
    §4.1)."""

    id: str
    state: RunState
    created_at: datetime
    finished_at: datetime | None
    benchmark: str
    case_count: int
    candidates: tuple[CandidateRecord, ...]
    # Whether a stop has flagged the Run. Not on the wire: `state` and `stopped_by` say it.
    canceled: bool = False
    detached: bool = False
    deadline_at: datetime | None = None
    stopped_by: StopReason | None = None
    context: ContextRef | None = None


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
        # WHY: a time out of range once in UTC is one Postgres cannot encode; it is the
        # caller's 422 on both stores, not a 503 that invites a retry.
        if self.since is not None:
            try:
                self.since.astimezone(UTC)
            except OverflowError:
                raise ValueError("since is out of range in UTC") from None
        if self.cursor is not None and not RUN_ID_PATTERN.fullmatch(self.cursor):
            raise ValueError("cursor must be a Run id")


@dataclass(frozen=True, slots=True)
class RunPage:
    runs: tuple[RunRecord, ...]
    next_cursor: str | None


# --- what the driver reads (E5 P2 spec §4.4) ---------------------------------------------


@dataclass(frozen=True, slots=True)
class DueRun:
    """A Run the driver's tick has work for.

    ``drive``: live, with starts, and nobody holds its lease (R4). ``past_deadline`` and
    ``unfollowed``: live, not yet stopped, and past its deadline (R11) or attached with nobody
    following it (R10). ``owed``: the topics a stop still owes (R9).
    """

    run_id: str
    drive: bool = False
    past_deadline: bool = False
    unfollowed: bool = False
    owed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PendingStart:
    """A `pending` Candidate the driver may start: its topic and trace once it was bound."""

    index: int
    start: CandidateStart
    topic: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class StartPlan:
    """What the driver needs to start a Run's next Candidates (E5 P2 spec R1)."""

    run_id: str
    owner: OwnerKey
    owner_email: str | None
    client_version: str
    stopped: bool
    in_flight: int
    # The first of the `pending` Candidates the driver may start now, by index; ``waiting``
    # counts every `pending` Candidate that has a start.
    pending: tuple[PendingStart, ...] = field(default=())
    waiting: int = 0
