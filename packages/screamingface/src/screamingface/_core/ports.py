"""Client-owned ports for SF Engine integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from screamingface._evaluation.model import Candidate, _Evaluation
    from screamingface.events import Event
    from screamingface.report import Usage

#: The states a Candidate has ended in on the Engine (E5 P2 spec §4.3); every other is live.
CANDIDATE_ENDED: frozenset[str] = frozenset({"succeeded", "failed", "timed_out", "stopped", "lost"})

type SyncEventObserver = Callable[[Event], None]
type AsyncEventObserver = Callable[[Event], None | Awaitable[None]]


@dataclass(frozen=True, slots=True)
class StartRequest:
    """One Candidate's start (P2 spec D8): its url4 and the flags the start route took as
    headers. The Engine's driver sends it for the Candidate, so the Client never starts one."""

    name: str
    url4: str
    answer_seed: int | None = None
    capture: bool = False
    use_cache: bool = True
    replay_frozen_copy: str | None = None

    def __post_init__(self) -> None:
        # INVARIANT (OME-1307): the Engine refuses both together, so no start carries both.
        if self.capture and self.replay_frozen_copy is not None:
            raise ValueError("capture and replay_frozen_copy are mutually exclusive")

    def body(self) -> dict[str, object]:
        return {
            "name": self.name,
            "url4": self.url4,
            "answer_seed": self.answer_seed,
            "capture": self.capture,
            "use_cache": self.use_cache,
            "replay_frozen_copy": self.replay_frozen_copy,
        }


@dataclass(frozen=True, slots=True)
class _ResultArtifact:
    """Claim ticket for a result the Engine spilled instead of sending inline (OME-892).

    The transport redeems it (`GET /artifacts/{id}`) and verifies `size_bytes` + `sha256`
    before any decoding sees the bytes.
    """

    id: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _RunResult:
    """Where a driver-started Candidate's result is kept (E5 P2 spec D9a): the Run's result
    route for the Candidate at ``index``, checked against ``size_bytes`` and ``sha256``."""

    run_id: str
    index: int
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _RunOutcome:
    """Transport-neutral root result retained for strict Report decoding.

    The contract supplies an inline body or artifact ticket. Public Clients select
    persistence and provide a result_path before decoding; artifact tickets remain
    available for recovery. save_results=False retains the legacy in-memory path.
    """

    run_id: str
    started_at: datetime
    completed_at: datetime
    result_body: str | None
    media_type: str | None
    root_usage: Usage | None
    # FEATURE (OME-1252): what this run's cache hits avoided, summed per provenance across its
    # spans. Two fields, never a third holding their sum — url4 keeps them apart so a consumer
    # cannot "add the labels away", and `reported` money is evidence about THIS row while
    # `archive_matched` is measured from a different call of the same model and kind.
    #
    # None means nothing priceable was observed, which is not the same as zero. The run-level
    # status derivation reads exactly that difference to tell `partial` from `unavailable`.
    cache_saved_cost_usd: Decimal | None = None
    cache_saved_cost_archive_usd: Decimal | None = None
    artifact: _ResultArtifact | None = None
    # WHY (OME-967): the id the CLIENT minted for this run, not one read back off a frame.
    # A user quoting it must be quoting the value that actually travelled on the wire —
    # including for a run whose frames never arrived.
    trace_id: str | None = None
    client_version: str | None = None
    result_path: Path | None = None
    # FEATURE (OME-1441, spec 2026-09-30-cached-run-not-complete): how many of this run's gateway
    # round trips the response cache served. A hit spends nothing upstream, so any hit means the
    # spend is not the run's cost, and the submission must not publish it as `complete`.
    cache_hits: int = 0
    # FEATURE (OME-1463, D7 on OME-1251): the run summary's count of hits that carried no price at
    # all. None when no summary arrived: the Engine may drop log events under backpressure, so
    # absence is "unknown", never "none were unpriced". The submission needs 0 to claim `complete`.
    cache_unpriced_hits: int | None = None
    # FEATURE (OME-1307): the run summary's frozen copy. None means the summary did not say (an
    # older Engine, or a run that was not a capture run), which is not `partial`: the submission
    # omits what it does not know.
    frozen_copy_id: str | None = None
    capture_status: Literal["complete", "partial"] | None = None
    # The copy the Engine says it replayed from. Only a replay run's summary carries it, and only
    # an Engine that honoured `X-Replay-Frozen-Copy` writes it.
    capture_replay: str | None = None
    # The partial reasons the run counted (design §5.2), sorted. Empty when complete or unknown.
    capture_partial_reasons: tuple[str, ...] = ()
    # FEATURE (OME-1837): a Candidate the Engine started keeps its result in the Run's
    # run-results store; the Client reads it from the result route (E5 P2 spec D9a).
    run_result: _RunResult | None = None


# FEATURE: OME-1066 adds the two capacity states — a start the Engine did not admit yet
# (`waiting_for_capacity`, with its attempt) and the start it finally admitted (`admitted`).
type _ConnectionState = Literal["reconnecting", "reconnected", "waiting_for_capacity", "admitted"]


@dataclass(frozen=True, slots=True)
class _ConnectionNotice:
    """One reconnect step of a Run's event stream, for the built-in progress output only.

    FEATURE: OME-1016 — the "reconnecting (attempt n)" progress line (spec 2026-09-28 R4).
    INVARIANT: it carries no URL, token, close code or exception text — only the step and
    its attempt number — so no renderer can leak transport internals.
    AIDEV-NOTE: deliberately NOT a public `Event`, and only the transport builds one, so
    the `Literal` is the whole contract — no runtime validation. Whether the user's
    `on_event` should also see it is an owner decision (spec 2026-09-28 Q1).
    """

    state: _ConnectionState
    # Set for `reconnecting` and `waiting_for_capacity` (the attempt now under way).
    attempt: int | None = None


@runtime_checkable
class _ConnectionListener(Protocol):
    """An `on_event` observer that also renders connection notices.

    WHY a capability check and not a second `run()` argument: the transport port stays
    unchanged for every implementation, and only the runner's bound observer opts in.
    """

    def connection(self, notice: _ConnectionNotice) -> None: ...


class SyncRunTransport(Protocol):
    """Execute one inspected Candidate through an SF Engine."""

    def run(
        self,
        candidate: Candidate,
        on_event: SyncEventObserver | None,
    ) -> _RunOutcome: ...

    def cancel_active(self) -> None: ...

    def close(self) -> None: ...


class AsyncRunTransport(Protocol):
    """Asynchronous counterpart of :class:`SyncRunTransport`."""

    async def run(
        self,
        candidate: Candidate,
        on_event: AsyncEventObserver | None,
    ) -> _RunOutcome: ...

    async def cancel_active(self) -> None: ...

    async def close(self) -> None: ...


__all__: list[str] = []


@runtime_checkable
class _RunRegistration(Protocol):
    """A transport that records each evaluation as a Run on the Engine (E5 P1 spec R1, D8).

    A transport without it (a test fake) runs every evaluation without a Run.
    """

    def open_run(
        self, benchmark: str, case_count: int, candidates: tuple[Candidate, ...]
    ) -> str | None: ...

    def abort_evaluation(self, candidates: tuple[Candidate, ...]) -> None: ...


@runtime_checkable
class _AsyncRunRegistration(Protocol):
    """The async twin of `_RunRegistration`. AIDEV-NOTE: `isinstance` sees only the name, so
    each caller checks the twin matching the transport it holds."""

    async def open_run(
        self, benchmark: str, case_count: int, candidates: tuple[Candidate, ...]
    ) -> str | None: ...

    async def abort_evaluation(self, candidates: tuple[Candidate, ...]) -> None: ...


@runtime_checkable
class _ResultPersistence(Protocol):
    def prepare_results(
        self, evaluation: _Evaluation, candidates: tuple[Candidate, ...]
    ) -> Path | None: ...


class _RunSink(Protocol):
    """What a followed Run reports to the runner, per Candidate by its index (E5 P2 spec §4.2).
    ``settled`` carries the outcome with its result fetched and kept, or why it has none."""

    def state(self, index: int, state: str) -> None: ...

    def event(self, index: int, event: Event) -> None: ...

    def settled(self, index: int, state: str, outcome: _RunOutcome | Exception) -> None: ...

    def connection(self, notice: _ConnectionNotice) -> None: ...

    def quiet(self) -> None:
        """A heartbeat: time has passed with no frame."""
        ...


class _AsyncRunSink(Protocol):
    async def state(self, index: int, state: str) -> None: ...

    async def event(self, index: int, event: Event) -> None: ...

    async def settled(self, index: int, state: str, outcome: _RunOutcome | Exception) -> None: ...

    def connection(self, notice: _ConnectionNotice) -> None: ...

    def quiet(self) -> None: ...


@runtime_checkable
class _RunFollowing(Protocol):
    """A transport the Engine drives (E5 P2 spec D1, D13): it registers the whole evaluation as a
    Run, with every Candidate's start, and follows it; the runner starts no Candidate.

    A transport without it (a test fake with `run()` alone) keeps the per-Candidate path until
    the Client port PR removes it.
    """

    def register_run(
        self,
        evaluation: _Evaluation | None,
        candidates: tuple[Candidate, ...],
        *,
        detach: bool = False,
        deadline_s: int | None = None,
    ) -> str: ...

    def follow_run(
        self, run_id: str, candidates: tuple[Candidate, ...], sink: _RunSink
    ) -> None: ...

    def cancel_run(self, run_id: str) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class _AsyncRunFollowing(Protocol):
    """The async twin of `_RunFollowing`. AIDEV-NOTE: `isinstance` sees only the names, so
    each caller checks the twin matching the transport it holds."""

    async def register_run(
        self,
        evaluation: _Evaluation | None,
        candidates: tuple[Candidate, ...],
        *,
        detach: bool = False,
        deadline_s: int | None = None,
    ) -> str: ...

    async def follow_run(
        self, run_id: str, candidates: tuple[Candidate, ...], sink: _AsyncRunSink
    ) -> None: ...

    async def cancel_run(self, run_id: str) -> None: ...

    async def close(self) -> None: ...


#: Where the follow keeps a settled Candidate's recorded outcome on the error of a result fetch
#: that failed (E5 P2 spec D14).
_RECORDED = "_screamingface_recorded"


def with_recorded(error: Exception, recorded: _RunOutcome) -> Exception:
    """``error``, a failed result fetch, naming the outcome the Engine recorded. WHY on the
    error itself: the sink still receives the fetch's own error (its type and code, which the
    transport tests pin), and the Report built when the Run ends fetches the result again
    instead of failing a Candidate that succeeded on the Engine."""
    setattr(error, _RECORDED, recorded)
    return error


def recorded_of(error: BaseException) -> _RunOutcome | None:
    """The recorded outcome a failed result fetch names, else None (a Candidate that failed)."""
    recorded = getattr(error, _RECORDED, None)
    return recorded if isinstance(recorded, _RunOutcome) else None


@dataclass(frozen=True, slots=True)
class _EndedRun:
    """A Run the Engine has ended, as the Client rebuilds its Report from it (E5 P2 spec D9b):
    the context the Client sent, each Candidate's start, and each one's outcome, which raises
    for a Candidate that did not succeed, as an attached evaluation's does."""

    context: str
    starts: tuple[StartRequest, ...]
    outcomes: tuple[_RunOutcome | Exception, ...]


@runtime_checkable
class _RunReattaching(Protocol):
    """A transport that can rebuild a Run's Report on any machine (E5 P2 spec D14): it keeps a
    settled Candidate's result as an attached evaluation does, and follows a Run to its end."""

    def adopt_run(self, run_id: str, candidates: tuple[Candidate, ...]) -> None: ...

    def save_result(self, candidate: Candidate, outcome: _RunOutcome) -> _RunOutcome: ...

    def wait_run(self, run_id: str, *, detached: bool) -> None: ...


@runtime_checkable
class _AsyncRunWaiting(Protocol):
    """A transport that follows a Run to its end on the event loop (`Run.wait_async`), so
    cancelling the wait ends the follow, and the hold it gives an attached Run."""

    async def wait_run_async(self, run_id: str, *, detached: bool) -> None: ...


@runtime_checkable
class _AsyncRunReattaching(Protocol):
    """The async twin of `_RunReattaching`: an `AsyncClient`'s transport, which rebuilds a Run's
    Report and follows a Run to its end on the event loop (E5 P2 spec D14)."""

    def adopt_run(self, run_id: str, candidates: tuple[Candidate, ...]) -> None: ...

    async def save_result(self, candidate: Candidate, outcome: _RunOutcome) -> _RunOutcome: ...

    async def wait_run_async(self, run_id: str, *, detached: bool) -> None: ...


#: What a Client holds until the Client port PR leaves one port: a transport the Engine drives,
#: or a `run()`-only one (every test fake).
type _SyncTransport = SyncRunTransport | _RunFollowing
type _AsyncTransport = AsyncRunTransport | _AsyncRunFollowing
