"""The `RunRegistry` port (E5 P1 spec §4.2, E5 P2 spec §4.4): what the App asks of the Run
store.

FEATURE: first-class Runs (OME-1785) and a detached Run (OME-1837). One implementation,
`runs.store.TortoiseRunStore`, on SQLite locally and Postgres hosted (spec D2). The App is its
only user: every database write goes through the App (spec D3), and the layering gate keeps it
out of the runners.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import (
    DueRun,
    OwnerKey,
    RunPage,
    RunQuery,
    RunRecord,
    RunSpec,
    StartPlan,
    StopReason,
)


class RunNotFound(LookupError):
    """No Run of this id belongs to this owner. A foreign id reads the same as an unknown one."""


class UnknownCandidate(LookupError):
    """The Run has no Candidate at this index."""


class RunCanceled(RuntimeError):
    """The Run was stopped (canceled, orphaned or past its deadline), so no Candidate of it may
    start (spec D12, E5 P2 spec R9)."""


class CandidateAlreadyStarted(RuntimeError):
    """The Candidate is bound to another topic, or the topic to another Candidate (spec R2)."""


class ClientKeyConflict(RuntimeError):
    """The owner already has a Run with this `client_key` but a different benchmark, Case count,
    Candidates, starts, `detach` or deadline: a repeat of `POST /runs` must describe the same
    evaluation (409)."""


class InvalidCursor(LookupError):
    """The `list` cursor names no Run of this owner, for example one retention has deleted (422)."""


class RunRegistry(Protocol):
    async def create(self, owner: OwnerKey, spec: RunSpec) -> RunRecord:
        """Register a Run, or return the owner's existing Run with the same `client_key`.

        Raises `ClientKeyConflict` when that Run describes a different evaluation.
        """
        ...

    async def register(self, owner: OwnerKey, spec: RunSpec) -> tuple[RunRecord, bool]:
        """`create`, and whether this call created the Run (`POST /runs` 201) or found it
        (200)."""
        ...

    async def get(self, owner: OwnerKey, run_id: str) -> RunRecord | None:
        """The Run with each Candidate's start and record."""
        ...

    async def summary(self, owner: OwnerKey, run_id: str) -> RunRecord | None:
        """`get` without each Candidate's start and record (E5 P2 spec §4.4)."""
        ...

    async def records(
        self, owner: OwnerKey, run_id: str, indexes: Sequence[int]
    ) -> dict[int, dict[str, Any] | None] | None:
        """The record of each named Candidate the Run has, by index (`None` until it ends), or
        `None` when the owner has no such Run. The event stream and the result route read one
        Candidate's record without loading the whole Run (E5 P2 spec §4.2)."""
        ...

    async def list(self, owner: OwnerKey, query: RunQuery) -> RunPage:
        """The owner's Runs, newest first by `created_at`, the id breaking ties.

        Raises `InvalidCursor` when the cursor names no Run of this owner.
        """
        ...

    async def bind(
        self,
        owner: OwnerKey,
        run_id: str,
        candidate: int,
        topic: str,
        *,
        trace_id: str | None = None,
    ) -> None:
        """Bind ``topic``, and the Candidate's trace, to the Run's Candidate at index
        ``candidate`` (spec R2). The Candidate stays `pending`; binding the same triple again
        changes nothing.

        Raises `RunNotFound`, `UnknownCandidate`, `RunCanceled` or `CandidateAlreadyStarted`.
        """
        ...

    async def mark_scheduled(self, topic: str) -> bool:
        """The bound Candidate's start was sent: `pending` becomes `scheduled`, and its clock
        starts (E5 P2 spec R8).

        Returns whether the start stands: False once any stop has flagged the Run, so the caller
        stops what it just sent (spec D12, E5 P2 spec R9).
        """
        ...

    async def settle(self, topic: str, outcome: CandidateOutcome) -> None:
        """Record the Candidate's outcome. INVARIANT (spec R4): the first terminal outcome wins;
        a terminal Candidate never moves, and an unbound topic is a no-op."""
        ...

    async def cancel(self, owner: OwnerKey, run_id: str) -> RunRecord | None:
        """`stop` the owner's Run as `canceled`, and return it; `None` when the owner has no
        such Run."""
        ...

    async def stop(
        self,
        run_id: str,
        reason: StopReason,
        *,
        unless_followed_since: datetime | None = None,
    ) -> bool:
        """Stop the Run while any Candidate is live (E5 P2 spec R9): keep the first reason, settle
        every unbound `pending` Candidate `stopped`, move every bound one to `scheduled`, and owe
        a stop to every live Candidate that has a topic. Returns whether this call stopped it.

        With ``unless_followed_since``, an orphan stop does nothing when the Run was followed
        after that time (R10).
        """
        ...

    async def owed_stops(self, owner: OwnerKey, run_id: str) -> list[str]:
        """The topics a cancel of the owner's Run still owes a stop (spec D12), whatever their
        state now: a stop that failed stays owed until `stop_done`."""
        ...

    async def stop_done(self, topic: str) -> None:
        """Record that the topic's owed stop succeeded."""
        ...

    async def reconcile(self) -> int:
        """Settle as `lost` the sent Candidates whose outcome can no longer arrive (spec R6).
        Returns how many it settled. It never writes any other state, and never touches a
        `pending` Candidate (E5 P2 spec R8)."""
        ...

    async def expiring(self, older_than: datetime) -> list[str]:
        """The ids of the Runs created before ``older_than``, oldest first, one batch at most
        (E5 P2 spec R13)."""
        ...

    async def expire(self, run_ids: Sequence[str]) -> int:
        """Delete these Runs and their Candidates (spec R7). Returns how many Runs."""
        ...

    # --- the Engine's driver (E5 P2 spec §4.4) -------------------------------------------

    async def lease_run(self, run_id: str, held_until: datetime | None, until: datetime) -> bool:
        """Take or renew the Run's lease until ``until`` (R4). Wins when nobody holds it, it
        has expired, or it is still the ``held_until`` this driver last wrote."""
        ...

    async def release_run(self, run_id: str, held_until: datetime) -> None:
        """Give the lease up, if it is still ``held_until``."""
        ...

    async def due_runs(self, now: datetime) -> list[DueRun]:
        """The Runs the driver's tick has work for: to drive, past their deadline, attached
        with nobody following, or with stops still owed."""
        ...

    async def pending_starts(self, run_id: str) -> StartPlan | None:
        """What the driver needs to start the Run's next Candidates (R1)."""
        ...

    async def overdue(self, run_id: str, before: datetime) -> list[str]:
        """The topics of the Run's in-flight Candidates sent before ``before`` (R7)."""
        ...

    async def followed(self, run_id: str, at: datetime) -> None:
        """Stamp that the Run had a follower at ``at``; the stamp never moves back (R10)."""
        ...

    async def settle_startless(self) -> int:
        """Settle the `pending` Candidates no start will ever reach: those of a Run a Client
        from before P2 registered (R11). Returns how many it moved."""
        ...


__all__ = [
    "CandidateAlreadyStarted",
    "ClientKeyConflict",
    "InvalidCursor",
    "RunCanceled",
    "RunNotFound",
    "RunRegistry",
    "UnknownCandidate",
]
