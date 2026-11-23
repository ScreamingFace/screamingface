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
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, NoReturn, Protocol

from screamingface import reports
from screamingface._core.ports import (
    CANDIDATE_ENDED,
    _AsyncRunReattaching,
    _AsyncRunWaiting,
    _EndedRun,
    _RunReattaching,
)
from screamingface._default_client import default_client
from screamingface._engine import runs as _wire
from screamingface._engine.runs import CandidateState, RunState, StopReason
from screamingface._evaluation.outcome import with_run_id
from screamingface.errors import ExecutionError
from screamingface.report import Report

if TYPE_CHECKING:
    from screamingface.client import AsyncClient, Client

#: How often `wait()` reads a Run whose Client's transport cannot wait for a Run by its id (a
#: custom `run_transport`).
_WAIT_POLL_S = 5.0


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
    ``"partial"``, ``"errored"``, ``"canceled"`` or ``"interrupted"``. A Run that came from an
    `AsyncClient` is read through it: await the ``_async`` methods.
    """

    id: str
    state: RunState
    created_at: datetime
    finished_at: datetime | None
    benchmark: str
    candidates: tuple[CandidateRun, ...]
    #: E5 P2: a Run stops at ``deadline_at``: a detached Run's is fixed, and an attached Run's
    #: moves forward while it is followed. ``stopped_by`` says why a Run that was stopped ended
    #: (``"canceled"``, ``"orphaned"`` or ``"deadline"``).
    detached: bool = False
    deadline_at: datetime | None = None
    stopped_by: StopReason | None = None
    # Set by `_bound`, never by a caller: what the methods read and follow the Run through.
    _runs: _RunPort = field(init=False, repr=False, compare=False)
    # A one-Candidate Run's attempt: a raw-URL4 or replay evaluation saves its result under it.
    _attempt_id: str | None = field(init=False, repr=False, compare=False)

    @property
    def cost_usd(self) -> Decimal | None:
        """The sum of the Candidates' known costs; None when none is known yet."""
        known = [c.cost_usd for c in self.candidates if c.cost_usd is not None]
        return sum(known, Decimal(0)) if known else None

    @property
    def _client(self) -> Client:
        """The synchronous Client a Run from `sf.runs` or a `Client` is read through."""
        return self._runs.client("this Run's Client")

    def refresh(self) -> Run:
        """The Run as the Engine has it now."""
        self._runs.client("refresh")
        return _bound(self._runs.summary(self.id), self._runs)

    def progress(self) -> RunProgress:
        """Read the Engine again and say how far the Run has got."""
        self._runs.client("progress")
        return _progress(self.refresh())

    def wait(self) -> Report:
        """Follow the Run until it ends, and return its Report; a finished Run's at once.

        It works from any machine: the Report is built from the Engine (``report()``). Raises
        ``login_expired`` when the sign-in expires while following; the Run goes on, and
        ``wait()`` picks it up again once you sign in.
        """
        self._runs.client("wait")
        if self.state == "running":
            self._runs.wait(self)
        return self.report()

    def report(self) -> Report:
        """The Run's Report, built from the Engine's context and records with the results this
        machine already holds, fetching the rest (spec D14), exactly as the evaluation that
        started it built it. A Run from before P2, or one the Engine no longer keeps, is read
        from the results saved on this machine.

        Raises ``ExecutionError``: ``run_not_finished`` while the Run is running;
        ``results_not_local`` for such a Run when this machine does not hold its results; and,
        as ``sf.reports.get`` does, ``candidates_failed`` with the partial Report when a
        Candidate did not succeed.
        """
        self._runs.client("report")
        return self._runs.report(self)

    def cancel(self) -> None:
        """Stop every Candidate of the Run still running, and refuse its later starts (D12).

        A finished Run is left as it is.
        """
        self._runs.client("cancel")
        self._runs.cancel(self.id)

    async def refresh_async(self) -> Run:
        """``refresh()``, without blocking the event loop."""
        return _bound(await self._runs.summary_async(self.id), self._runs)

    async def progress_async(self) -> RunProgress:
        """``progress()``, without blocking the event loop."""
        return _progress(await self.refresh_async())

    async def wait_async(self) -> Report:
        """``wait()`` on the event loop. Cancelling it ends the follow, so it no longer holds
        an attached Run, and no thread goes on following."""
        if self.state == "running":
            await self._runs.wait_async(self)
        return await self.report_async()

    async def report_async(self) -> Report:
        """``report()``, without blocking the event loop."""
        return await self._runs.report_async(self)

    async def cancel_async(self) -> None:
        """``cancel()``, without blocking the event loop."""
        await self._runs.cancel_async(self.id)


class _RunPort(Protocol):
    """What a Run's methods read and follow it through: a `Client` (`_SyncRuns`) or an
    `AsyncClient` (`_AsyncRuns`), each in both forms."""

    def client(self, method: str) -> Client:
        """The synchronous Client; raises `TypeError` naming the ``_async`` form of ``method``
        when there is none."""
        ...

    def summary(self, run_id: str) -> _wire.RunRecord: ...

    def wait(self, run: Run) -> None: ...

    def report(self, run: Run) -> Report: ...

    def cancel(self, run_id: str) -> None: ...

    async def summary_async(self, run_id: str) -> _wire.RunRecord: ...

    async def wait_async(self, run: Run) -> None: ...

    async def report_async(self, run: Run) -> Report: ...

    async def cancel_async(self, run_id: str) -> None: ...


class _SyncRuns:
    """A Run's methods through a synchronous `Client`; the async forms run them in a thread,
    except the wait, which follows on the event loop where the transport can."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def client(self, method: str) -> Client:
        return self._client

    def summary(self, run_id: str) -> _wire.RunRecord:
        return _wire.get_sync(self._client._http_request, run_id, summary=True)

    def wait(self, run: Run) -> None:
        if self.summary(run.id).state != "running":
            return
        transport = self._client._transport
        if isinstance(transport, _RunReattaching):
            transport.wait_run(run.id, detached=run.detached)
            return
        # WHY: a custom `run_transport` cannot wait for a Run by its id; the Run's summary still
        # says when it ends.
        while self.summary(run.id).state == "running":
            time.sleep(_WAIT_POLL_S)

    def report(self, run: Run) -> Report:
        from screamingface._engine.run_client import ended_run
        from screamingface._evaluation.reattach import engine_report

        # WHY the Engine first for a Run seen running (#1878 review): this machine may hold
        # every result before the Engine ends the Run, which is `run_not_finished` until then.
        seen_running = run.state == "running"
        record = self._read(run.id) if seen_running else None
        whole = _whole_here(run.id)
        if whole is not None:
            return whole
        if not seen_running:
            record = self._read(run.id)
        request = self._client._http_request
        attempt_id = _attempt(run, record)
        ended: _EndedRun | None = None
        lost: ExecutionError | None = None
        if record is not None:
            try:
                ended = ended_run(request, record)
            except KeyError:
                pass  # retention deleted it after its full read
            except ExecutionError as exc:
                lost = _lost(exc)
        # A Client whose transport cannot rebuild (a custom `run_transport`) reads this machine.
        if ended is not None and isinstance(self._client._transport, _RunReattaching):
            try:
                # E5 P2 spec D14: the one build every Report of a Run comes from, saved here
                # when this Client saves results.
                return engine_report(self._client._transport, run.id, ended)
            except ExecutionError as exc:
                lost = _unreadable(exc)
        return _saved_here(run.id, attempt_id, lost)

    def _read(self, run_id: str) -> _wire.RunRecord | None:
        """The Run's full read, which must have ended; None once retention has deleted it."""
        try:
            record = _wire.get_sync(self._client._http_request, run_id)
        except KeyError:
            return None
        _require_ended(record)
        return record

    def cancel(self, run_id: str) -> None:
        _wire.cancel_sync(self._client._http_request, run_id)

    async def summary_async(self, run_id: str) -> _wire.RunRecord:
        return await asyncio.to_thread(self.summary, run_id)

    async def wait_async(self, run: Run) -> None:
        if (await self.summary_async(run.id)).state != "running":
            return
        transport = self._client._transport
        if isinstance(transport, _AsyncRunWaiting):
            await transport.wait_run_async(run.id, detached=run.detached)
        elif isinstance(transport, _RunReattaching):
            # A transport that follows only on a thread (a test fake).
            await asyncio.to_thread(transport.wait_run, run.id, detached=run.detached)
        else:
            while (await self.summary_async(run.id)).state == "running":
                await asyncio.sleep(_WAIT_POLL_S)

    async def report_async(self, run: Run) -> Report:
        return await asyncio.to_thread(run.report)

    async def cancel_async(self, run_id: str) -> None:
        await asyncio.to_thread(self.cancel, run_id)


class _AsyncRuns:
    """A Run's methods through an `AsyncClient`, on its own async transport and http client:
    no synchronous Client is made for it (E5 P2 spec D14)."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def client(self, method: str) -> NoReturn:
        raise TypeError(
            f"This Run came from an AsyncClient; await `run.{method}_async()` instead"
            if method in _ASYNC_FORMS
            else "This Run came from an AsyncClient, which has no synchronous Client"
        )

    def summary(self, run_id: str) -> NoReturn:
        self.client("refresh")

    def wait(self, run: Run) -> NoReturn:
        self.client("wait")

    def report(self, run: Run) -> NoReturn:
        self.client("report")

    def cancel(self, run_id: str) -> NoReturn:
        self.client("cancel")

    async def summary_async(self, run_id: str) -> _wire.RunRecord:
        return await _wire.get_async(self._client._http_request, run_id, summary=True)

    async def wait_async(self, run: Run) -> None:
        if (await self.summary_async(run.id)).state != "running":
            return
        transport = self._client._transport
        if isinstance(transport, _AsyncRunWaiting):
            await transport.wait_run_async(run.id, detached=run.detached)
            return
        while (await self.summary_async(run.id)).state == "running":
            await asyncio.sleep(_WAIT_POLL_S)

    async def report_async(self, run: Run) -> Report:
        from screamingface._engine.run_client import ended_run_async
        from screamingface._evaluation.reattach import engine_report_async

        seen_running = run.state == "running"  # see `_SyncRuns.report`
        record = await self._read(run.id) if seen_running else None
        whole = await asyncio.to_thread(_whole_here, run.id)
        if whole is not None:
            return whole
        if not seen_running:
            record = await self._read(run.id)
        request = self._client._http_request
        ended: _EndedRun | None = None
        lost: ExecutionError | None = None
        attempt_id = _attempt(run, record)
        if record is not None:
            try:
                ended = await ended_run_async(request, record)
            except KeyError:
                pass  # retention deleted it after its full read
            except ExecutionError as exc:
                lost = _lost(exc)
        if ended is not None and isinstance(self._client._transport, _AsyncRunReattaching):
            try:
                return await engine_report_async(self._client._transport, run.id, ended)
            except ExecutionError as exc:
                lost = _unreadable(exc)
        return await _saved_here_async(run.id, attempt_id, lost)

    async def _read(self, run_id: str) -> _wire.RunRecord | None:
        """The async twin of ``_SyncRuns._read``."""
        try:
            record = await _wire.get_async(self._client._http_request, run_id)
        except KeyError:
            return None
        _require_ended(record)
        return record

    async def cancel_async(self, run_id: str) -> None:
        await _wire.cancel_async(self._client._http_request, run_id)


#: The Run methods that have an ``_async`` form, which an `AsyncClient`'s Run must await.
_ASYNC_FORMS = frozenset({"refresh", "progress", "wait", "report", "cancel"})


def _progress(now: Run) -> RunProgress:
    done = sum(1 for c in now.candidates if c.state in CANDIDATE_ENDED)
    return RunProgress(done=done, total=len(now.candidates), cost_usd=now.cost_usd)


def _whole_here(run_id: str) -> Report | None:
    """The Report this machine already saved whole, else None. WHY read, not built again: the
    build that saved it is the one every Report of the Run comes from (spec D14), and a build
    marks the saved evaluation running while it works, which an interruption would leave behind
    on a healthy Report."""
    if not reports._downloaded(run_id):
        return None
    try:
        return with_run_id(reports.get(run_id), run_id)
    except (KeyError, ExecutionError):
        return None  # not whole after all: built from the Engine


def _attempt(run: Run, record: _wire.RunRecord | None) -> str | None:
    """WHY the full read's, when there is one: a snapshot taken before a one-Candidate Run's
    Candidate started does not name the attempt its saved result is kept under."""
    if record is None:
        return run._attempt_id
    return record.candidates[0].attempt_id if len(record.candidates) == 1 else None


def _require_ended(record: _wire.RunRecord) -> None:
    if record.state == "running":
        raise ExecutionError(
            f"Run {record.id} is still running",
            code="run_not_finished",
            permanent=False,
            hint="Call `run.wait()` first.",
        )


def _lost(exc: ExecutionError) -> ExecutionError:
    """``exc`` when it says the Engine lost the Run's context, or holds one that no longer
    matches: this machine may hold the whole Report. Anything else is raised."""
    if exc.code not in _CONTEXT_LOST:
        raise exc
    return exc


def _unreadable(exc: ExecutionError) -> ExecutionError:
    """``exc`` when the context reads back whole but this Client cannot rebuild an evaluation
    from it (a newer Client's); anything else is raised."""
    if exc.code != _CONTEXT_UNREADABLE:
        raise exc
    return exc


def _saved_here(run_id: str, attempt_id: str | None, lost: ExecutionError | None) -> Report:
    """The Report saved on this machine, for a Run whose Report the Engine cannot give: one
    from before P2, which kept neither context nor starts there, one retention deleted, or one
    whose context is ``lost``, which is raised when this machine holds nothing either."""
    with _partial_named(run_id):
        saved = _saved(run_id) or _saved(attempt_id)
    return _found_here(run_id, saved, lost)


async def _saved_here_async(
    run_id: str, attempt_id: str | None, lost: ExecutionError | None
) -> Report:
    """``_saved_here`` through `sf.reports.get_async`. WHY (#1878 review): an AsyncClient's
    Run never makes a synchronous Client to fetch what this machine is missing."""
    with _partial_named(run_id):
        saved = await _saved_async(run_id) or await _saved_async(attempt_id)
    return _found_here(run_id, saved, lost)


@contextmanager
def _partial_named(run_id: str) -> Iterator[None]:
    try:
        yield
    except ExecutionError as exc:
        if exc.partial_report is not None:
            exc.partial_report = with_run_id(exc.partial_report, run_id)
        raise


def _found_here(run_id: str, saved: Report | None, lost: ExecutionError | None) -> Report:
    if saved is None:
        from screamingface._evaluation.reattach import results_not_local

        raise lost or results_not_local(run_id)
    return with_run_id(saved, run_id)


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


#: A context the Engine no longer holds, or one that no longer matches the Run's checksum.
_CONTEXT_LOST = frozenset({"context_not_found", "context_mismatch"})
#: A context that reads back whole but that this Client cannot rebuild an evaluation from.
_CONTEXT_UNREADABLE = "run_context_invalid"


def _saved(report_id: str | None) -> Report | None:
    """The saved Report under ``report_id`` (a Run id, or an attempt id), or None."""
    if report_id is None:
        return None
    try:
        return reports.get(report_id)
    except KeyError:
        return None


async def _saved_async(report_id: str | None) -> Report | None:
    """The async twin of ``_saved``."""
    if report_id is None:
        return None
    try:
        return await reports.get_async(report_id)
    except KeyError:
        return None


def _run(record: _wire.RunRecord, client: Client) -> Run:
    """The Run ``record`` names, read through the synchronous ``client``."""
    return _bound(record, _SyncRuns(client))


def _bound(record: _wire.RunRecord, runs: _RunPort) -> Run:
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
    object.__setattr__(run, "_runs", runs)
    only = record.candidates[0].attempt_id if len(record.candidates) == 1 else None
    object.__setattr__(run, "_attempt_id", only)
    return run


__all__ = ["CandidateRun", "Run", "RunProgress", "get", "get_async", "list", "list_async"]
