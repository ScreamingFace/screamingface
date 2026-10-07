"""Client-owned ports for SF Engine integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from screamingface._evaluation.model import Candidate
    from screamingface.events import Event
    from screamingface.report import Usage

type SyncEventObserver = Callable[[Event], None]
type AsyncEventObserver = Callable[[Event], None | Awaitable[None]]


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
class _RunOutcome:
    """Transport-neutral root result retained for strict Report decoding.

    INVARIANT: exactly one of `result_body` / `artifact` is set when the contract layer
    builds this; the transport materializes an artifact outcome into a full `result_body`
    (artifact=None) before anything downstream decodes it — Report construction never
    sees an unredeemed ticket.
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
    # FEATURE (OME-1441, spec 2026-09-30-cached-run-not-complete): how many of this run's gateway
    # round trips the response cache served. A hit spends nothing upstream, so any hit means the
    # spend is not the run's cost, and the submission must not publish it as `complete`.
    cache_hits: int = 0
    # FEATURE (OME-1463, D7 on OME-1251): the run summary's count of hits that carried no price at
    # all. None when no summary arrived: the Engine may drop log events under backpressure, so
    # absence is "unknown", never "none were unpriced". The submission needs 0 to claim `complete`.
    cache_unpriced_hits: int | None = None
    # FEATURE (OME-1307, K3): the run summary's cache version. None means the summary did not say
    # (an older Engine, or a run that never touched the cache), which is not `partial`: the
    # submission omits what it does not know.
    cache_revision: str | None = None
    reproducible: Literal["complete", "partial"] | None = None
    # The label the Engine says it replayed from. Only a replay run's summary carries it, and only
    # an Engine that honoured `X-Cache-Replay` writes it.
    cache_replay: str | None = None


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
