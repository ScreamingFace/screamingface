"""screamingface.budget.v1: the method-owner Budget records, SDK side (OME-1289, erd s11).

FEATURE/STORY: the four records an E4c call layer writes and a compare reads (``Budget`` declared on
a request, one ``BudgetCharge`` per sent call, one ``BudgetRefusal`` per call not sent, and the
``BudgetState`` that holds them). They mirror ``screamingface_engine.budget``: the same fields,
field order and rules. There is no charge rule here: the E4c call layer is the producer, and
``budget_cases.json`` (an Engine contract fixture) binds the two mirrors.
INVARIANT: a ``BudgetState`` equals the fold of its own charges (``remaining = max(cap - spent,
0)``; ``None`` is unpriced, never zero), so a decoded ledger cannot disagree with itself.
AIDEV-NOTE: E4a declares no Budget on any request and writes no charge or ``budget`` trace entry.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Literal, get_args

from screamingface._report_primitives import _optional_number, _required_number

type BudgetUnit = Literal["usd", "tokens"]
type ChargeSource = Literal["live", "cache_reference", "unpriced"]
type BudgetStage = Literal["model", "synthesis", "judge", "writer"]

BUDGET_SCHEMA = "screamingface.budget.v1"

_UNITS = frozenset(get_args(BudgetUnit.__value__))
_SOURCES = frozenset(get_args(ChargeSource.__value__))
_STAGES = frozenset(get_args(BudgetStage.__value__))
_MEMBER_ID = re.compile(r"member_[1-9][0-9]*")
# The Engine's combine DECIMAL_CONTEXT; budget_cases.json binds the two.
_DECIMAL = Context(prec=1000, rounding=ROUND_HALF_EVEN)


def _choice(value: object, allowed: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{label} must be one of {', '.join(sorted(allowed))}")
    return value


def _ids(operation_id: object, member_id: object, label: str) -> None:
    if not isinstance(operation_id, str) or not operation_id:
        raise ValueError(f"{label} operation_id must be a non-empty string")
    if member_id is not None and (
        not isinstance(member_id, str) or _MEMBER_ID.fullmatch(member_id) is None
    ):
        raise ValueError(f"{label} member_id must look like 'member_1' or be None")


def _non_negative(value: object, label: str) -> float:
    number = _required_number(value, label)
    if number < 0:
        raise ValueError(f"{label} must not be negative")
    return number


def _check_cap(unit: object, cap: object, label: str) -> float:
    _choice(unit, _UNITS, f"{label} unit")
    number = _required_number(cap, f"{label} cap")
    if not number > 0:
        raise ValueError(f"{label} cap must be finite and greater than zero")
    if unit == "tokens" and not number.is_integer():
        raise ValueError(f"a tokens {label} cap must be a whole number")
    return number


def _fields(value: object, keys: tuple[str, ...], label: str) -> dict[str, object]:
    """The exact keys of a record mapping; a missing or extra key is named."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} is read from a mapping")
    if missing := [key for key in keys if key not in value]:
        raise ValueError(f"{label} is missing {missing[0]!r}")
    if extra := sorted(set(value) - set(keys)):
        raise ValueError(f"{label} has an unsupported field {extra[0]!r} (extra)")
    return {key: value[key] for key in keys}


def _records[T](value: object, build: type[T], label: str) -> tuple[T, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise TypeError(f"{label} must be a list")
    return tuple(item if isinstance(item, build) else build.from_dict(item) for item in value)  # type: ignore[attr-defined]


_BUDGET_KEYS = ("unit", "cap")


@dataclass(frozen=True, slots=True)
class Budget:
    """A Budget declared on a request: a unit and a cap (finite, > 0; whole for tokens)."""

    unit: BudgetUnit
    cap: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "cap", _check_cap(self.unit, self.cap, "Budget"))

    def to_dict(self) -> dict[str, object]:
        return {"unit": self.unit, "cap": self.cap}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Budget:
        """Rebuild a Budget from its exact to_dict shape."""
        return cls(**_fields(value, _BUDGET_KEYS, "Budget"))  # type: ignore[arg-type]


_CHARGE_KEYS = ("operation_id", "member_id", "stage", "amount", "source", "remaining_after")


@dataclass(frozen=True, slots=True)
class BudgetCharge:
    """One sent call's charge; ``amount`` is None exactly when ``source`` is ``unpriced``."""

    operation_id: str
    member_id: str | None
    stage: BudgetStage
    amount: float | None
    source: ChargeSource
    remaining_after: float

    def __post_init__(self) -> None:
        _ids(self.operation_id, self.member_id, "BudgetCharge")
        _choice(self.stage, _STAGES, "BudgetCharge stage")
        _choice(self.source, _SOURCES, "BudgetCharge source")
        amount = _optional_number(self.amount, "BudgetCharge amount")
        if amount is not None and amount < 0:
            raise ValueError("BudgetCharge amount must not be negative")
        if (amount is None) != (self.source == "unpriced"):
            raise ValueError("BudgetCharge amount is None exactly when source is 'unpriced'")
        object.__setattr__(self, "amount", amount)
        remaining = _non_negative(self.remaining_after, "BudgetCharge remaining_after")
        object.__setattr__(self, "remaining_after", remaining)

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "member_id": self.member_id,
            "stage": self.stage,
            "amount": self.amount,
            "source": self.source,
            "remaining_after": self.remaining_after,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> BudgetCharge:
        """Rebuild a BudgetCharge from its exact to_dict shape."""
        return cls(**_fields(value, _CHARGE_KEYS, "BudgetCharge"))  # type: ignore[arg-type]


_REFUSAL_KEYS = ("operation_id", "member_id", "stage", "estimated", "reason")


@dataclass(frozen=True, slots=True)
class BudgetRefusal:
    """One call that was not sent because it would exceed the cap (written by E4c)."""

    operation_id: str
    member_id: str | None
    stage: BudgetStage
    estimated: float
    reason: Literal["would_exceed_cap"]

    def __post_init__(self) -> None:
        _ids(self.operation_id, self.member_id, "BudgetRefusal")
        _choice(self.stage, _STAGES, "BudgetRefusal stage")
        object.__setattr__(
            self, "estimated", _non_negative(self.estimated, "BudgetRefusal estimated")
        )
        _choice(self.reason, frozenset({"would_exceed_cap"}), "BudgetRefusal reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "member_id": self.member_id,
            "stage": self.stage,
            "estimated": self.estimated,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> BudgetRefusal:
        """Rebuild a BudgetRefusal from its exact to_dict shape."""
        return cls(**_fields(value, _REFUSAL_KEYS, "BudgetRefusal"))  # type: ignore[arg-type]


def _ledger(cap: float, amounts: Sequence[float | None]) -> tuple[float, float, int, list[float]]:
    """Fold the charge amounts: (spent, remaining, unpriced count, remaining after each charge).

    The same rule as the Engine's ``_ledger``: ``Decimal(repr(x))`` sums in ``_DECIMAL``.
    """
    with localcontext(_DECIMAL):
        spent = Decimal(0)
        unpriced = 0
        remaining_after: list[float] = []
        for amount in amounts:
            if amount is None:
                unpriced += 1
            else:
                spent += Decimal(repr(amount))
            remaining_after.append(float(max(Decimal(repr(cap)) - spent, Decimal(0))))
        remaining = float(max(Decimal(repr(cap)) - spent, Decimal(0)))
    return float(spent), remaining, unpriced, remaining_after


_STATE_KEYS = ("unit", "cap", "spent", "remaining", "unpriced_charges", "charges", "refused")


@dataclass(frozen=True, slots=True)
class BudgetState:
    """What a compare reads: the counters plus every charge and refusal."""

    unit: BudgetUnit
    cap: float
    spent: float
    remaining: float
    unpriced_charges: int
    charges: tuple[BudgetCharge, ...]
    refused: tuple[BudgetRefusal, ...]

    def __post_init__(self) -> None:
        cap = _check_cap(self.unit, self.cap, "BudgetState")
        spent = _non_negative(self.spent, "BudgetState spent")
        remaining = _non_negative(self.remaining, "BudgetState remaining")
        count = self.unpriced_charges
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("BudgetState unpriced_charges must be a non-negative integer")
        charges = _records(self.charges, BudgetCharge, "BudgetState charges")
        refused = _records(self.refused, BudgetRefusal, "BudgetState refused")
        folded = _ledger(cap, [charge.amount for charge in charges])
        if (spent, remaining, count) != folded[:3]:
            raise ValueError(
                "BudgetState spent, remaining and unpriced_charges must equal the fold of charges"
            )
        if [charge.remaining_after for charge in charges] != folded[3]:
            raise ValueError("BudgetState each remaining_after must equal the running remaining")
        for name, item in (
            ("cap", cap),
            ("spent", spent),
            ("remaining", remaining),
            ("charges", charges),
            ("refused", refused),
        ):
            object.__setattr__(self, name, item)

    def to_dict(self) -> dict[str, object]:
        return {
            "unit": self.unit,
            "cap": self.cap,
            "spent": self.spent,
            "remaining": self.remaining,
            "unpriced_charges": self.unpriced_charges,
            "charges": [charge.to_dict() for charge in self.charges],
            "refused": [refusal.to_dict() for refusal in self.refused],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> BudgetState:
        """Rebuild a BudgetState from its exact to_dict shape."""
        return cls(**_fields(value, _STATE_KEYS, "BudgetState"))  # type: ignore[arg-type]


__all__ = ["BUDGET_SCHEMA", "Budget", "BudgetCharge", "BudgetRefusal", "BudgetState"]
