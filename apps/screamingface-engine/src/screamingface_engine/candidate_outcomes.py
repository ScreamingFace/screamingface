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
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Literal, Protocol, cast, get_args

# INVARIANT: exactly the statuses a terminal frame can carry (url4 `TerminatedData.status`).
# `lost` is not one: only the registry's reconcile writes it, once no outcome can still arrive.
OutcomeStatus = Literal["succeeded", "failed", "stopped", "timed_out"]
OUTCOME_STATUSES: frozenset[str] = frozenset(get_args(OutcomeStatus))

# The registry's column widths (`runs/models/candidate.py`). WHY here: an outcome is checked
# against them before it is published, so a value Postgres would refuse never reaches the writer.
ERROR_CODE_LENGTH = 128
# WHY 12 places: costs are fractions of a cent per call; 24 digits leave 12 for whole dollars.
COST_DIGITS = 24
COST_PLACES = 12
_MAX_COST = Decimal(10) ** (COST_DIGITS - COST_PLACES)
_COST_QUANTUM = Decimal(1).scaleb(-COST_PLACES)


def stored_cost(cost: Decimal) -> Decimal:
    """``cost`` as the registry stores it: rounded up to `COST_PLACES`, so a cost below the
    column's precision stays visible, never 0."""
    return cost.quantize(_COST_QUANTUM, rounding=ROUND_CEILING)


def check_topic(topic: object) -> str:
    """``topic`` if an outcome may name it: a non-empty string with no NUL. Both adapters and
    the codec apply this one rule, so neither accepts an outcome the other would drop."""
    if not isinstance(topic, str) or not topic:
        raise ValueError("an outcome names its topic")
    if "\x00" in topic:
        raise ValueError("an outcome's topic has no NUL")
    return topic


UNSTORABLE_ERROR_CODE = "error_code_unstorable"
"""Stands in for a terminal frame's error code that is too long for the registry or holds a NUL.
url4 does not bound a code, so a producer names the case instead of losing the outcome."""


def storable_error_code(code: str | None) -> str | None:
    """``code`` if the registry can store it as it is, else `UNSTORABLE_ERROR_CODE`."""
    if code is None or (len(code) <= ERROR_CODE_LENGTH and "\x00" not in code):
        return code
    return UNSTORABLE_ERROR_CODE


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
    # WHEN the producer saw the end, so a Candidate's `finished_at` is not the time a delayed
    # outcome was written (after a database outage, hours later). WHY not compared: two outcomes
    # with one verdict are the same outcome, whenever each was seen.
    finished_at: datetime = field(default_factory=lambda: datetime.now(UTC), compare=False)

    def __post_init__(self) -> None:
        if self.status not in OUTCOME_STATUSES:
            raise ValueError(f"an outcome status is one of {sorted(OUTCOME_STATUSES)}")
        cost = self.cost_usd
        # WHY the stored value: rounding up can carry a cost just below the bound onto it, which
        # the column cannot hold.
        if cost is not None and (
            not cost.is_finite() or cost < 0 or stored_cost(cost) >= _MAX_COST
        ):
            raise ValueError(f"a cost must be a finite amount from 0 up to {_MAX_COST} USD")
        if storable_error_code(self.error_code) != self.error_code:
            raise ValueError(f"an error code is at most {ERROR_CODE_LENGTH} characters, no NUL")
        if self.finished_at.utcoffset() is None:
            raise ValueError("an outcome's finished_at must be timezone-aware")


def encode_outcome(topic: str, outcome: CandidateOutcome) -> bytes:
    """The outcome's wire form. WHY the cost as a string: a JSON number is a float to most
    readers, and a float cannot hold an exact cost."""
    cost = None if outcome.cost_usd is None else str(outcome.cost_usd)
    body = {
        "topic": check_topic(topic),
        "status": outcome.status,
        "error_code": outcome.error_code,
        "cost_usd": cost,
        "finished_at": outcome.finished_at.isoformat(),
    }
    return json.dumps(body, separators=(",", ":")).encode()


def decode_outcome(payload: bytes) -> tuple[str, CandidateOutcome]:
    """The topic and outcome in ``payload``; `ValueError` for anything else."""
    try:
        body = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        # WHY RecursionError too: deeply nested JSON exhausts the parser, and an error the writer
        # does not drop would stop every outcome behind it.
        raise ValueError("an outcome must be a JSON object") from exc
    if not isinstance(body, dict):
        raise ValueError("an outcome must be a JSON object")
    topic, status, error_code = body.get("topic"), body.get("status"), body.get("error_code")
    topic = check_topic(topic)
    # WHY the type first: a list or object is unhashable, and `in` would raise TypeError, which
    # the writer does not drop, so one such message would stop every outcome behind it.
    if not isinstance(status, str) or status not in OUTCOME_STATUSES:
        raise ValueError(f"an outcome status is one of {sorted(OUTCOME_STATUSES)}")
    if error_code is not None and not isinstance(error_code, str):
        raise ValueError("an error code is a string")
    outcome = CandidateOutcome(
        cast(OutcomeStatus, status),
        error_code,
        _decimal(body.get("cost_usd")),
        _finished_at(body.get("finished_at")),
    )
    return topic, outcome


def _finished_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("an outcome's finished_at is an ISO 8601 string")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("an outcome's finished_at is an ISO 8601 string") from exc


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
