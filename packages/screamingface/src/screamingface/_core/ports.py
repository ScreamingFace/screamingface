"""Client-owned ports for SF Engine integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

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
