"""screamingface.budget.v1: the method-owner Budget records and the charge rule (OME-1289, erd s11).

FEATURE/STORY (a Gate reads remaining; the call layer writes charges/refusals). INVARIANT: pure, no
I/O; amounts sum in DECIMAL_CONTEXT (Decimal(repr(x))); remaining = max(cap - spent, 0); None is
unpriced, never zero. AIDEV-NOTE: E4a declares no Budget on any request and writes no charge
(BU-D4).
"""

from __future__ import annotations

import contextvars
import math
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal, localcontext
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from screamingface_engine.combine.ports import DECIMAL_CONTEXT
from screamingface_engine.operation_accounting import SignalAccounting

BUDGET_SCHEMA = "screamingface.budget.v1"
BudgetUnit = Literal["usd", "tokens"]
ChargeSource = Literal["live", "cache_reference", "unpriced"]
# E4c (OME-1291, budget BU-21): a LabelModel selector call is charged as its own stage; a
# consistency `sample` call is charged as `model` (E4b part 7 D7).
BudgetStage = Literal["model", "synthesis", "judge", "writer", "selector"]

# The spec's member id form (combine/spec.py); a Budget record names no other id.
_MEMBER = re.compile(r"member_[1-9][0-9]*")


def exact_decimal(number: float) -> Decimal:
    """The exact decimal a float prints as, so 0.1 stays 0.1 and sums do not drift."""
    return Decimal(repr(number))


def _check_member(member_id: str | None) -> str | None:
    if member_id is not None and not _MEMBER.fullmatch(member_id):
        raise ValueError("member_id must be member_N or None")
    return member_id


def _check_cap(unit: str, cap: float) -> None:
    if not cap > 0:
        raise ValueError("budget cap must be finite and greater than zero")
    if unit == "tokens" and not cap.is_integer():
        raise ValueError("a tokens budget cap must be a whole number")


class _BudgetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class Budget(_BudgetModel):
    """A Budget declared on a request: a unit and a cap."""

    unit: BudgetUnit
    cap: float

    @model_validator(mode="after")
    def _cap_rule(self) -> Self:
        _check_cap(self.unit, self.cap)
        return self


class BudgetCharge(_BudgetModel):
    """One sent call's charge; ``amount`` is None only for an unpriced call."""

    operation_id: str = Field(min_length=1)
    member_id: str | None
    stage: BudgetStage
    amount: float | None = Field(ge=0)
    source: ChargeSource
    remaining_after: float = Field(ge=0)

    @model_validator(mode="after")
    def _record_rules(self) -> Self:
        _check_member(self.member_id)
        if (self.amount is None) != (self.source == "unpriced"):
            raise ValueError("amount is None exactly when source is 'unpriced'")
        return self


class BudgetRefusal(_BudgetModel):
    """One call that was not sent because it would exceed the cap (the call layer writes it)."""

    operation_id: str = Field(min_length=1)
    member_id: str | None
    stage: BudgetStage
    estimated: float = Field(ge=0)
    reason: Literal["would_exceed_cap"]

    @model_validator(mode="after")
    def _record_rules(self) -> Self:
        _check_member(self.member_id)
        return self


def _ledger(cap: float, amounts: Sequence[float | None]) -> tuple[float, float, int, list[float]]:
    """Fold the charge amounts: (spent, remaining, unpriced count, remaining after each charge).

    The one rule behind ``BudgetState.apply`` and the state validator. An unpriced charge
    (``None``) adds nothing to spent and one to the count.
    """
    with localcontext(DECIMAL_CONTEXT):
        spent = Decimal(0)
        unpriced = 0
        remaining_after: list[float] = []
        for amount in amounts:
            if amount is None:
                unpriced += 1
            else:
                spent += exact_decimal(amount)
            remaining_after.append(float(max(exact_decimal(cap) - spent, Decimal(0))))
        remaining = float(max(exact_decimal(cap) - spent, Decimal(0)))
    return float(spent), remaining, unpriced, remaining_after


def fold(cap: float, amounts: Sequence[Decimal | None]) -> tuple[float, float, int]:
    """(spent, remaining, unpriced count) of ``amounts`` against ``cap``: the ledger rule above,
    for the ancestors of one E4c Gate decision (OME-1291, erd §5)."""

    spent, remaining, unpriced, _ = _ledger(
        cap, [None if amount is None else float(amount) for amount in amounts]
    )
    return spent, remaining, unpriced


class BudgetState(_BudgetModel):
    """What a compare reads: the counters plus every charge and refusal."""

    unit: BudgetUnit
    cap: float
    spent: float
    remaining: float
    unpriced_charges: int = Field(ge=0)
    charges: list[BudgetCharge]
    refused: list[BudgetRefusal]

    @model_validator(mode="after")
    def _ledger_rule(self) -> Self:
        _check_cap(self.unit, self.cap)
        spent, remaining, unpriced, afters = _ledger(self.cap, [c.amount for c in self.charges])
        if (self.spent, self.remaining, self.unpriced_charges) != (spent, remaining, unpriced):
            raise ValueError("spent, remaining and unpriced_charges must equal the fold of charges")
        if [c.remaining_after for c in self.charges] != afters:
            raise ValueError("each remaining_after must equal the running remaining")
        return self

    @classmethod
    def start(cls, budget: Budget) -> Self:
        """The empty state of a declared Budget."""
        return cls(
            unit=budget.unit,
            cap=budget.cap,
            spent=0.0,
            remaining=budget.cap,
            unpriced_charges=0,
            charges=[],
            refused=[],
        )

    def apply(
        self,
        *,
        operation_id: str,
        member_id: str | None,
        stage: BudgetStage,
        signals: SignalAccounting,
        cached: bool,
    ) -> Self:
        """A new state with one more charge for a call that was sent."""
        amount, source = charge(signals, self.unit, cached=cached)
        number = None if amount is None else float(amount)
        amounts = [*(c.amount for c in self.charges), number]
        spent, remaining, unpriced, afters = _ledger(self.cap, amounts)
        sent = BudgetCharge(
            operation_id=operation_id,
            member_id=member_id,
            stage=stage,
            amount=number,
            source=source,
            remaining_after=afters[-1],
        )
        return type(self)(
            unit=self.unit,
            cap=self.cap,
            spent=spent,
            remaining=remaining,
            unpriced_charges=unpriced,
            charges=[*self.charges, sent],
            refused=self.refused,
        )


def charge(
    signals: SignalAccounting, unit: BudgetUnit, *, cached: bool
) -> tuple[Decimal | None, ChargeSource]:
    """The amount one call costs in ``unit``, and where the number came from.

    ``cached`` is the cache hit status of the call (the world layer knows it; ``signals`` holds
    numbers only). A hit is charged its ORIGINAL cost, as ``cache_reference``. A missing number
    makes the call unpriced: ``(None, "unpriced")``.
    """
    amount = _amount(signals, unit)
    if amount is None:
        return None, "unpriced"
    return amount, "cache_reference" if cached else "live"


class CallCharge(_BudgetModel):
    """What one provider call charges a Budget, per unit: the ``charge`` rule's numbers.

    E4c (OME-1291, ans:Q32): written on each operation of a candidate with a Budget, so the
    report's overspend line adds what the Budget added. A cache hit charges its ORIGINAL cost
    (``cache.reference``), so a replay shows the live run's spend. ``None`` is unpriced: it adds
    nothing to the spend, as in ``fold``.
    """

    usd: float | None = Field(ge=0)
    tokens: float | None = Field(ge=0)


def call_charge(signals: SignalAccounting) -> CallCharge:
    """The charge of one provider call in every unit (the rule of ``charge``)."""

    usd, _ = charge(signals, "usd", cached=False)
    tokens, _ = charge(signals, "tokens", cached=False)
    return CallCharge(
        usd=None if usd is None else float(usd), tokens=None if tokens is None else float(tokens)
    )


def _amount(signals: SignalAccounting, unit: BudgetUnit) -> Decimal | None:
    # erd I-S2: a NaN or infinite number is unknown, so the call is unpriced (None), never an error.
    numbers = (signals.cost_usd,) if unit == "usd" else (signals.tokens_in, signals.tokens_out)
    if not all(number is not None and math.isfinite(number) for number in numbers):
        return None
    with localcontext(DECIMAL_CONTEXT):
        return sum((exact_decimal(number) for number in numbers if number is not None), Decimal(0))


# E4c (OME-1291, budget BU-13, BU-28): the Budgets of the candidate running in this task, bound
# once per Attempt before the expression runs, so every task of the Case inherits them (a value
# set inside a running task would stay invisible to its siblings). Empty: no Budget.
_case_budgets: contextvars.ContextVar[tuple[Budget, ...]] = contextvars.ContextVar(
    "screamingface_engine_case_budgets", default=()
)
# The units whose unpriced warning this Attempt already logged (budget §4: once per Case). A
# mutable set bound with the Budgets, so a sibling task's warning is seen by the others.
_case_unpriced_logged: contextvars.ContextVar[set[str] | None] = contextvars.ContextVar(
    "screamingface_engine_case_unpriced_logged", default=None
)


@contextmanager
def case_budgets(budgets: Sequence[Budget]) -> Iterator[None]:
    """Bind the candidate's Budgets for one Attempt of one Case; each Attempt starts full."""

    token = _case_budgets.set(tuple(budgets))
    logged = _case_unpriced_logged.set(set())
    try:
        yield
    finally:
        _case_unpriced_logged.reset(logged)
        _case_budgets.reset(token)


def first_unpriced_warning(unit: BudgetUnit) -> bool:
    """True the first time this Attempt reports an unpriced ``unit`` charge, else False."""

    logged = _case_unpriced_logged.get()
    if logged is None or unit in logged:
        return False
    logged.add(unit)
    return True


def current_case_budgets() -> tuple[Budget, ...]:
    """The Budgets bound for this Attempt (in declaration order), or () without a Budget."""

    return _case_budgets.get()


def budget_schemas() -> dict[str, dict[str, Any]]:
    """The JSON Schema of each record, keyed by record name (the freeze snapshot input)."""
    return {
        model.__name__: model.model_json_schema(by_alias=True, mode="validation")
        for model in (Budget, BudgetCharge, BudgetRefusal, BudgetState)
    }
