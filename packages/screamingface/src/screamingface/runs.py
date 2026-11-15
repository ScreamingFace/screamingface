"""Your Runs on the Engine: list, reopen, wait on and cancel them (E5 P1 spec §4.4).

Every ``sf.evaluate`` is recorded as a Run, and ``report.run_id`` names it. A Run is listed from
any notebook or machine signed in as you, for 30 days. ``sf.reports`` is separate: it opens the
results saved on this machine.

e.g. ``sf.runs.get(report.run_id).wait().report()``.
"""

from __future__ import annotations

import asyncio
import builtins
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from screamingface import reports
from screamingface._default_client import default_client
from screamingface._engine import runs as _wire
from screamingface._engine.runs import CandidateState, RunState
from screamingface._evaluation.outcome import with_run_id
from screamingface.errors import ExecutionError
from screamingface.report import Report

# Test seams: production code never replaces them.
_sleep = time.sleep
_monotonic = time.monotonic
_POLL_FIRST_S = 1.0
_POLL_MAX_S = 10.0
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
    # Set by `_run`, never by a caller: the Engine call the methods read the Run again with.
    _request: _wire.Request = field(init=False, repr=False, compare=False)
    # A one-Candidate Run's attempt: a raw-URL4 or replay evaluation saves its result under it.
    _attempt_id: str | None = field(init=False, repr=False, compare=False)

    @property
    def cost_usd(self) -> Decimal | None:
        """The sum of the Candidates' known costs; None when none is known yet."""
        known = [c.cost_usd for c in self.candidates if c.cost_usd is not None]
        return sum(known, Decimal(0)) if known else None

    def refresh(self) -> Run:
        """The Run as the Engine has it now."""
        return _run(_wire.get_sync(self._request, self.id), self._request)

    def progress(self) -> RunProgress:
        """Read the Engine again and say how far the Run has got."""
        now = self.refresh()
        done = sum(1 for c in now.candidates if c.state in _CANDIDATE_DONE)
        return RunProgress(done=done, total=len(now.candidates), cost_usd=now.cost_usd)

    def wait(self, *, timeout: float | None = None) -> Run:
        """Poll the Engine until the Run has finished, and return it; a finished Run at once.

        Raises ``TimeoutError`` when it is still running after ``timeout`` seconds.
        """
        deadline = None if timeout is None else _monotonic() + timeout
        delay = _POLL_FIRST_S
        current = self
        while current.state == "running":
            if deadline is not None:
                remaining = deadline - _monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Run {self.id} is still running after {timeout} s")
                delay = min(delay, remaining)
            _sleep(delay)
            delay = min(delay * 2, _POLL_MAX_S)
            current = self.refresh()
        return current

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
        if saved is None:
            raise ExecutionError(
                f"The results of Run {self.id} are not on this machine",
                code="results_not_local",
                permanent=True,
                hint="Open the report on the machine that ran the evaluation.",
            )
        return with_run_id(saved, self.id)

    def cancel(self) -> None:
        """Stop every Candidate of the Run still running, and refuse its later starts (D12).

        A finished Run is left as it is.
        """
        _wire.cancel_sync(self._request, self.id)


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
    request = _request()
    records = _wire.list_sync(request, state=state, since=since, limit=limit)
    return [_run(record, request) for record in records]


def get(run_id: str) -> Run:
    """One of your Runs by its id, e.g. ``report.run_id``.

    Raises ``KeyError`` for an unknown id, or another caller's, and
    ``ExecutionError("runs_unavailable")`` when the Engine does not serve Runs.
    """
    request = _request()
    return _run(_wire.get_sync(request, run_id), request)


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


def _request() -> _wire.Request:
    return default_client()._http_request


def _run(record: _wire.RunRecord, request: _wire.Request) -> Run:
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
    )
    object.__setattr__(run, "_request", request)
    only = record.candidates[0].attempt_id if len(record.candidates) == 1 else None
    object.__setattr__(run, "_attempt_id", only)
    return run


__all__ = ["CandidateRun", "Run", "RunProgress", "get", "get_async", "list", "list_async"]
