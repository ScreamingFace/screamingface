"""``sf.WithBudget``, ``sf.Estimate`` and ``sf.budget.remaining()``: a per-Case spending cap (E4c).

FEATURE: OME-1291 budget PRD. ``sf.WithBudget(recipe, budget_usd=..., max_tokens=...)`` writes one
cap on the candidate (ans:Q19); it covers one Case (ans:Q13). Before each optional call (a Gate
branch, a cascade escalation, a lazy fallback) the Engine checks the spend of the calls that already
ran plus the branch's ``sf.Estimate``; a branch that would pass the cap is not sent. A call with no
known cost counts as $0, and the report warns (ans:Q14). Calls that always run are never refused.
STORY: as a researcher whose result is a saving, the cap is real money the provider never bills,
and the report shows spend against the cap and the refused branch.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, cast

from screamingface._surface.outcomes import Outcome
from screamingface.branch import WORDS
from screamingface.budget import _UNITS, BudgetUnit
from screamingface.recipe import _BU11, Recipe, _recipe

# The sf.WithBudget keyword of each unit. WHY "budget_usd", not "max_usd": the cap is checked before
# each optional call only, so the calls that always run can pass it (Q20); "max" read as a hard
# maximum (product review 2026-11-12). The url4 keeps the unit name ("usd=").
CAP_KEYWORDS: dict[BudgetUnit, str] = {"usd": "budget_usd", "tokens": "max_tokens"}


def _cap(
    value: object, unit: BudgetUnit, owner: str, keyword: str | None = None
) -> float | int | None:
    """A checked cap or estimate in ``unit``; ``keyword`` names the argument (default: the unit)."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{owner} {keyword or unit}= is a number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{owner} {keyword or unit}= must be finite and not negative")
    if unit == "tokens" and not float(value).is_integer():
        raise ValueError(f"{owner} {keyword or unit}= must be a whole number")
    return int(value) if unit == "tokens" else float(value)


def _units(usd: float | None, tokens: int | None) -> dict[str, float | int]:
    """The units set, usd then tokens; a unit left unset is left out."""

    return {unit: value for unit, value in (("usd", usd), ("tokens", tokens)) if value is not None}


def units_text(units: Mapping[str, float | int]) -> str:
    """The units as the author wrote them: ``usd=0.03, tokens=100``."""

    return ", ".join(f"{unit}={value!r}" for unit, value in units.items())


@dataclass(frozen=True, slots=True, init=False, repr=False)
class WithBudget(Recipe):
    """Wrap the whole candidate with a per-Case cap in USD (``budget_usd=``), tokens
    (``max_tokens=``) or both (a branch is refused when either unit refuses it). Use it once, at
    the root. The cap is checked before each optional call, so the calls that always run can pass
    it (the report shows the overspend, Q20)."""

    recipe: Recipe
    budget_usd: float | None
    max_tokens: int | None

    def __init__(
        self,
        recipe: str | Recipe,
        *,
        budget_usd: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        if isinstance(recipe, WithBudget):
            raise ValueError(_BU11)
        object.__setattr__(self, "recipe", _recipe(recipe, "sf.WithBudget recipe"))
        usd_cap = _cap(budget_usd, "usd", "sf.WithBudget", CAP_KEYWORDS["usd"])
        tokens_cap = _cap(max_tokens, "tokens", "sf.WithBudget", CAP_KEYWORDS["tokens"])
        if usd_cap is None and tokens_cap is None:
            raise ValueError("sf.WithBudget needs a cap: budget_usd=, max_tokens= or both")
        if usd_cap == 0 or tokens_cap == 0:
            raise ValueError("budget cap must be finite and greater than zero")
        object.__setattr__(self, "budget_usd", usd_cap)
        object.__setattr__(self, "max_tokens", tokens_cap)

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.recipe.name

    @property
    def optional(self) -> bool:  # type: ignore[override]
        return False

    @property
    def _recipe_marker(self) -> None:
        return None

    def _caps(self) -> dict[str, int | float]:
        """The caps this Budget sets, usd then tokens; a unit it does not cap is left out."""

        return _units(self.budget_usd, self.max_tokens)

    def units(self) -> tuple[BudgetUnit, ...]:
        return cast("tuple[BudgetUnit, ...]", tuple(self._caps()))

    __hash__: ClassVar[Any] = None

    def __repr__(self) -> str:
        return self._render("")

    def _render(self, prefix: str) -> str:
        from screamingface._surface.render import render

        caps = {
            CAP_KEYWORDS[cast("BudgetUnit", unit)]: value for unit, value in self._caps().items()
        }
        return f"{prefix}WithBudget({render(self.recipe, prefix)}, {units_text(caps)})"


@dataclass(frozen=True, slots=True, init=False)
class Estimate:
    """The author's estimate of what one Gate branch costs (ans:Q3): ``then=sf.Estimate(big,
    usd=0.03)``. With no estimate a branch is refused only when the cap is spent."""

    branch: object
    usd: float | None
    tokens: int | None

    def __init__(
        self, branch: object, *, usd: float | None = None, tokens: int | None = None
    ) -> None:
        if isinstance(branch, Outcome) or (isinstance(branch, str) and branch in WORDS):
            raise ValueError("sf.Estimate wraps a branch that makes model calls")
        object.__setattr__(self, "branch", branch)
        object.__setattr__(self, "usd", _cap(usd, "usd", "sf.Estimate"))
        object.__setattr__(self, "tokens", _cap(tokens, "tokens", "sf.Estimate"))
        if self.usd is None and self.tokens is None:
            raise ValueError("sf.Estimate needs usd=, tokens= or both")

    def _spec(self) -> dict[str, float | int]:
        return _units(self.usd, self.tokens)

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True)
class BudgetCondition:
    """``sf.budget.remaining() >= x``: a comparison on what the Case's Budget has left."""

    unit: BudgetUnit | None
    cmp: Literal[">=", ">", "<=", "<"]
    value: float

    def _render(self, prefix: str) -> str:
        unit = "" if self.unit is None else repr(self.unit)
        return f"{prefix}budget.remaining({unit}) {self.cmp} {self.value!r}"

    def __repr__(self) -> str:
        return self._render("")


@dataclass(frozen=True, slots=True)
class Remaining:
    unit: BudgetUnit | None

    def _compare(self, cmp: Literal[">=", ">", "<=", "<"], value: object) -> BudgetCondition:
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise TypeError("sf.budget.remaining() compares with a finite number")
        return BudgetCondition(self.unit, cmp, float(value) + 0.0)

    def __ge__(self, value: object) -> BudgetCondition:
        return self._compare(">=", value)

    def __gt__(self, value: object) -> BudgetCondition:
        return self._compare(">", value)

    def __le__(self, value: object) -> BudgetCondition:
        return self._compare("<=", value)

    def __lt__(self, value: object) -> BudgetCondition:
        return self._compare("<", value)


def remaining(unit: BudgetUnit | None = None) -> Remaining:
    """What the Budget has left after the calls that already ran (BU-6). Name the unit when the
    Budget declares both: ``sf.budget.remaining('usd')``."""

    if unit not in (None, *_UNITS):
        raise ValueError("sf.budget.remaining() takes 'usd' or 'tokens'")
    return Remaining(unit)


__all__ = ["BudgetCondition", "WithBudget", "Estimate", "Remaining", "remaining"]
