"""How a Candidate ended, on its way from whichever process saw the end to the App (E5 P1 spec R3).

FEATURE: first-class Runs (OME-1785). Every producer (the in-process runner, a worker's
supervisor, the App's own terminal writers) publishes a `CandidateOutcome` to the
`CandidateOutcomeStream`, and one App consumer writes it to the Run registry (spec D3, D4).

LAYERING: a shared leaf, standard library only. The runners import this and never the registry,
so nothing they execute holds a database connection (`.claude/scripts/check_layering.py`).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol, cast, get_args

# INVARIANT: exactly the statuses a terminal frame can carry (url4 `TerminatedData.status`).
# `lost` is not one: only the registry's reconcile writes it, once no outcome can still arrive.
OutcomeStatus = Literal["succeeded", "failed", "stopped", "timed_out"]
OUTCOME_STATUSES: frozenset[str] = frozenset(get_args(OutcomeStatus))

DEFAULT_OUTCOMES_MAX_AGE_S = 86_400.0
"""How long `url4-candidate-outcomes` keeps an unacked outcome. Reconcile's cutoff must
outlast it (spec R6)."""


@dataclass(frozen=True, slots=True)
class CandidateOutcome:
    """A Candidate's end: its status, the error code when it failed, and the exact cost when
    known. INVARIANT: cost is exact only, as on the wire (spec R3); an unknown cost is `None`,
    never an estimate."""

    status: OutcomeStatus
    error_code: str | None = None
    cost_usd: Decimal | None = None

    def __post_init__(self) -> None:
        if self.status not in OUTCOME_STATUSES:
            raise ValueError(f"an outcome status is one of {sorted(OUTCOME_STATUSES)}")
        cost = self.cost_usd
        if cost is not None and (not cost.is_finite() or cost < 0):
            raise ValueError("a cost must be a finite, non-negative amount")


def encode_outcome(topic: str, outcome: CandidateOutcome) -> bytes:
    """The outcome's wire form. WHY the cost as a string: a JSON number is a float to most
    readers, and a float cannot hold an exact cost."""
    cost = None if outcome.cost_usd is None else str(outcome.cost_usd)
    body = {
        "topic": topic,
        "status": outcome.status,
        "error_code": outcome.error_code,
        "cost_usd": cost,
    }
    return json.dumps(body, separators=(",", ":")).encode()


def decode_outcome(payload: bytes) -> tuple[str, CandidateOutcome]:
    """The topic and outcome in ``payload``; `ValueError` for anything else."""
    try:
        body = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("an outcome must be a JSON object") from exc
    if not isinstance(body, dict):
        raise ValueError("an outcome must be a JSON object")
    topic, status, error_code = body.get("topic"), body.get("status"), body.get("error_code")
    if not isinstance(topic, str) or not topic:
        raise ValueError("an outcome names its topic")
    # WHY the type first: a list or object is unhashable, and `in` would raise TypeError, which
    # the writer does not drop, so one such message would stop every outcome behind it.
    if not isinstance(status, str) or status not in OUTCOME_STATUSES:
        raise ValueError(f"an outcome status is one of {sorted(OUTCOME_STATUSES)}")
    if error_code is not None and not isinstance(error_code, str):
        raise ValueError("an error code is a string")
    outcome = CandidateOutcome(
        cast(OutcomeStatus, status), error_code, _decimal(body.get("cost_usd"))
    )
    return topic, outcome


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("a cost travels as a decimal string")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("a cost travels as a decimal string") from exc


@dataclass(frozen=True, slots=True)
class OutcomeDelivery:
    """One outcome handed to the writer. INVARIANT (spec R4): the writer calls `ack` only after
    its commit; an outcome never acked is delivered again."""

    topic: str
    outcome: CandidateOutcome
    _ack: Callable[[], Awaitable[None]] = field(repr=False, compare=False)

    async def ack(self) -> None:
        await self._ack()


class CandidateOutcomeStream(Protocol):
    """Where producers publish outcomes and the App's writer consumes them (spec §4.2).

    Backed by JetStream (`url4-candidate-outcomes`) or held in memory, like `EventStream`; which
    one is an adapter choice, never a mode branch.
    """

    @property
    def survives_restart(self) -> bool:
        """Whether an unacked outcome outlives this process. Reconcile (spec R6) reads it."""
        ...

    async def ensure_stream(self) -> None:
        """Create the stream if missing (spec R11). Safe to call from every process, any time."""
        ...

    async def publish(self, topic: str, outcome: CandidateOutcome) -> None: ...

    def consume(self) -> AsyncIterator[OutcomeDelivery]:
        """Deliveries in publish order, then redeliveries of those not acked in time."""
        ...


__all__ = [
    "DEFAULT_OUTCOMES_MAX_AGE_S",
    "OUTCOME_STATUSES",
    "CandidateOutcome",
    "CandidateOutcomeStream",
    "OutcomeDelivery",
    "OutcomeStatus",
    "decode_outcome",
    "encode_outcome",
]
