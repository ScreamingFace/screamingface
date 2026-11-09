"""The `RunRegistry` port (E5 P1 spec §4.2): what the App asks of the Run store.

FEATURE: first-class Runs (OME-1785). One implementation, `runs.store.TortoiseRunStore`, on SQLite
locally and Postgres hosted (spec D2). The App is its only user: every database write goes
through the App (spec D3), and the layering gate keeps it out of the runners.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import OwnerKey, RunPage, RunQuery, RunRecord, RunSpec


class RunNotFound(LookupError):
    """No Run of this id belongs to this owner. A foreign id reads the same as an unknown one."""


class UnknownCandidate(LookupError):
    """The Run has no Candidate at this index."""


class RunCanceled(RuntimeError):
    """The Run was canceled, so no Candidate of it may start (spec D12, 409 `run_canceled`)."""


class CandidateAlreadyStarted(RuntimeError):
    """The Candidate is bound to another topic, or the topic to another Candidate (spec R2,
    409 `candidate_already_started`)."""


class ClientKeyConflict(RuntimeError):
    """The owner already has a Run with this `client_key` but a different benchmark, Case count
    or Candidates: a repeat of `POST /runs` must describe the same evaluation (409)."""


class InvalidCursor(LookupError):
    """The `list` cursor names no Run of this owner, for example one retention has deleted (422)."""


class RunRegistry(Protocol):
    async def create(self, owner: OwnerKey, spec: RunSpec) -> RunRecord:
        """Register a Run, or return the owner's existing Run with the same `client_key`.

        Raises `ClientKeyConflict` when that Run describes a different evaluation.
        """
        ...

    async def get(self, owner: OwnerKey, run_id: str) -> RunRecord | None: ...

    async def list(self, owner: OwnerKey, query: RunQuery) -> RunPage:
        """The owner's Runs, newest first by `created_at`, the id breaking ties.

        Raises `InvalidCursor` when the cursor names no Run of this owner.
        """
        ...

    async def bind(self, owner: OwnerKey, run_id: str, candidate: int, topic: str) -> None:
        """Bind ``topic`` to the Run's Candidate at index ``candidate`` (spec R2). The Candidate
        stays `pending`; binding the same triple again changes nothing.

        Raises `RunNotFound`, `UnknownCandidate`, `RunCanceled` or `CandidateAlreadyStarted`.
        """
        ...

    async def mark_scheduled(self, topic: str) -> None:
        """The bound Candidate's start was scheduled: `pending` becomes `scheduled`."""
        ...

    async def settle(self, topic: str, outcome: CandidateOutcome) -> None:
        """Record the Candidate's outcome. INVARIANT (spec R4): the first terminal outcome wins;
        a terminal Candidate never moves, and an unbound topic is a no-op."""
        ...

    async def cancel(self, owner: OwnerKey, run_id: str) -> RunRecord | None:
        """Cancel the Run while any Candidate is not terminal (spec D12): set the sticky flag and
        stop every `pending` Candidate. A finished Run is returned unchanged."""
        ...

    async def reconcile(self) -> int:
        """Settle as `lost` the Candidates whose outcome can no longer arrive (spec R6). Returns
        how many it settled. It never writes any other state."""
        ...

    async def expire(self, older_than: datetime) -> int:
        """Delete the Runs created before ``older_than`` (spec R7). Returns how many."""
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
