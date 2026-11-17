"""Your Runs on the Engine: list, reopen, wait on and cancel them (E5 P1 spec §4.4, P2 §4.6).

Every ``sf.evaluate`` is a Run, and ``report.run_id`` names it; ``sf.evaluate(..., detach=True)``
returns the Run at once and the Engine runs it without you. A Run is listed from any notebook or
machine signed in as you, for 30 days, and its Report can be built on any of them.
``sf.reports`` is separate: it opens the results saved on this machine.

e.g. ``sf.runs.get(run_id).wait()``.
"""

from __future__ import annotations

import asyncio
import builtins
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from screamingface import reports
from screamingface._core.ports import _RunReattaching
from screamingface._default_client import default_client
from screamingface._engine import runs as _wire
from screamingface._engine.runs import CandidateState, RunState, StopReason
from screamingface._evaluation.outcome import with_run_id
from screamingface.errors import ExecutionError
from screamingface.report import Report

if TYPE_CHECKING:
    from screamingface.client import Client

_CANDIDATE_DONE: frozenset[str] = frozenset({"succeeded", "failed", "timed_out", "stopped", "lost"})


@dataclass(frozen=True, slots=True)
class CandidateRun:
    """One Candidate of a Run. ``cost_usd`` is None while unknown (a lost Candidate's stays so)."""

    name: str
    state: CandidateState
    cost_usd: Decimal | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class RunProgress:
    """How far a Run has got: Candidates ``done`` of ``total``, and the spend known so far."""

    done: int
    total: int
    cost_usd: Decimal | None


@dataclass(frozen=True, slots=True)
class Run:
    """A snapshot of one Run. Its methods read the Engine again; the snapshot never changes.

    ``state`` is ``"running"`` until every Candidate has finished, then one of ``"complete"``,
    ``"partial"``, ``"errored"``, ``"canceled"`` or ``"interrupted"``.
    """

    id: str
    state: RunState
    created_at: datetime
    finished_at: datetime | None
    benchmark: str
    candidates: tuple[CandidateRun, ...]
    #: E5 P2: a detached Run runs without a follower until ``deadline_at``; ``stopped_by`` says
    #: why a Run that was stopped ended (``"canceled"``, ``"orphaned"`` or ``"deadline"``).
    detached: bool = False
    deadline_at: datetime | None = None
    stopped_by: StopReason | None = None
    # Set by `_run`, never by a caller: the Client the methods read and follow the Run with.
    _client: Client = field(init=False, repr=False, compare=False)
    # A one-Candidate Run's attempt: a raw-URL4 or replay evaluation saves its result under it.
    _attempt_id: str | None = field(init=False, repr=False, compare=False)

    @property
    def cost_usd(self) -> Decimal | None:
        """The sum of the Candidates' known costs; None when none is known yet."""
        known = [c.cost_usd for c in self.candidates if c.cost_usd is not None]
        return sum(known, Decimal(0)) if known else None

    def refresh(self) -> Run:
        """The Run as the Engine has it now."""
        record = _wire.get_sync(self._client._http_request, self.id, summary=True)
        return _run(record, self._client)

    def progress(self) -> RunProgress:
        """Read the Engine again and say how far the Run has got."""
        now = self.refresh()
        done = sum(1 for c in now.candidates if c.state in _CANDIDATE_DONE)
        return RunProgress(done=done, total=len(now.candidates), cost_usd=now.cost_usd)

    def wait(self) -> Report:
        """Follow the Run until it ends, and return its Report; a finished Run's at once.

        It works from any machine: the Report is this machine's saved one, else built from the
        Engine (``report()``). Raises ``login_expired`` when the sign-in expires while following;
        the Run goes on, and ``wait()`` picks it up again once you sign in.
        """
        if self.state == "running" and self.refresh().state == "running":
            transport = self._client._transport
            if isinstance(transport, _RunReattaching):
                transport.wait_run(self.id, detached=self.detached)
        return self.report()

    def report(self) -> Report:
        """The Run's Report, from the results saved on this machine (spec D9).

        Raises ``ExecutionError``: ``run_not_finished`` while the Run is running;
        ``results_not_local`` when this machine does not hold its results; and, as
        ``sf.reports.get`` does, ``candidates_failed`` with the partial Report when a Candidate
        did not succeed.
        """
        # WHY re-read: a snapshot taken while the Run ran must not refuse a Run that has finished.
        if self.state == "running" and self.refresh().state == "running":
            raise ExecutionError(
                f"Run {self.id} is still running",
                code="run_not_finished",
                permanent=False,
                hint="Call `run.wait()` first.",
            )
        try:
            saved = _saved(self.id) or _saved(self._attempt_id)
        except ExecutionError as exc:
            if exc.partial_report is not None:
                exc.partial_report = with_run_id(exc.partial_report, self.id)
            raise
        if saved is not None:
            return with_run_id(saved, self.id)
        from screamingface._evaluation.reattach import engine_report

        # E5 P2 spec D9b, D14: built from the Engine's context, records and results, as an
        # attached evaluation builds it, and saved here when this Client saves results.
        return engine_report(self._client, self.id)

    def cancel(self) -> None:
        """Stop every Candidate of the Run still running, and refuse its later starts (D12).

        A finished Run is left as it is.
        """
        _wire.cancel_sync(self._client._http_request, self.id)


def list(
    *, state: RunState | None = None, since: datetime | None = None, limit: int = 50
) -> builtins.list[Run]:
    """Your Runs, newest first: at most ``limit``, created at or after ``since``, in ``state``.

    Raises ``ExecutionError("runs_unavailable")`` when the Engine does not serve Runs.
    """
    if since is not None and since.tzinfo is None:
        raise ValueError("since must be a timezone-aware datetime")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    client = default_client()
    records = _wire.list_sync(client._http_request, state=state, since=since, limit=limit)
    return [_run(record, client) for record in records]


def get(run_id: str) -> Run:
    """One of your Runs by its id, e.g. ``report.run_id``.

    Raises ``KeyError`` for an unknown id, or another caller's, and
    ``ExecutionError("runs_unavailable")`` when the Engine does not serve Runs.
    """
    client = default_client()
    return _run(_wire.get_sync(client._http_request, run_id, summary=True), client)


async def list_async(
    *, state: RunState | None = None, since: datetime | None = None, limit: int = 50
) -> builtins.list[Run]:
    """``list``, without blocking the event loop."""
    return await asyncio.to_thread(list, state=state, since=since, limit=limit)


async def get_async(run_id: str) -> Run:
    """``get``, without blocking the event loop."""
    return await asyncio.to_thread(get, run_id)


def _saved(report_id: str | None) -> Report | None:
    """The saved Report under ``report_id`` (a Run id, or an attempt id), or None."""
    if report_id is None:
        return None
    try:
        return reports.get(report_id)
    except KeyError:
        return None


def _run(record: _wire.RunRecord, client: Client) -> Run:
    run = Run(
        id=record.id,
        state=record.state,
        created_at=record.created_at,
        finished_at=record.finished_at,
        benchmark=record.benchmark,
        candidates=tuple(
            CandidateRun(name=c.name, state=c.state, cost_usd=c.cost_usd, error_code=c.error_code)
            for c in record.candidates
        ),
        detached=record.detached,
        deadline_at=record.deadline_at,
        stopped_by=record.stopped_by,
    )
    object.__setattr__(run, "_client", client)
    only = record.candidates[0].attempt_id if len(record.candidates) == 1 else None
    object.__setattr__(run, "_attempt_id", only)
    return run


__all__ = ["CandidateRun", "Run", "RunProgress", "get", "get_async", "list", "list_async"]
