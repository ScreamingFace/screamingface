"""sf.Gate: keep a vote's majority only when one recorded number passes a threshold (E4b part 5).

The gate is data, never Python code: one named number (``observe``), one comparison (``cmp``) and
one threshold, written into the combine spec as ``gate``. When ``observed cmp threshold`` holds,
the vote's majority is the answer. Otherwise the fallback (``otherwise``) gives the answer: an
abstain with the reason ``gate_not_met``, a label judge that names a member, or a model that
writes. In this version the fallback call runs on every Case; the gate chooses and records
(ans:Q1). E4c (OME-1291) removes the unused call with no wire change.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, cast

from screamingface._signals import is_signal_key, is_signal_name
from screamingface.judge import Judge
from screamingface.model import Model
from screamingface.reducer import _ModelSignal

type GateCmp = Literal[">=", ">", "<=", "<"]

_CMPS: tuple[str, ...] = (">=", ">", "<=", "<")
_KEEP_HIGH: tuple[str, ...] = (">=", ">")
_AGREEMENT = "agreement"
_NAMED_FORMS: tuple[str, ...] = ("chosen", "mean")
_ABSTAIN: Literal["abstain"] = "abstain"
_OBSERVE_RULE = (
    "Gate observe must be 'agreement', 'chosen:<name>' or 'mean:<name>', where <name> is a "
    "declared signal name"
)
_E4A_HINT = "; an E4a key such as cost_usd is not a gate input"
_OTHERWISE_RULE = "Gate otherwise must be 'abstain', an sf.Judge or an sf.Model"


@dataclass(frozen=True, slots=True, init=False)
class Gate:
    """Keep the majority when ``observe cmp threshold`` holds; else run ``otherwise``.

    ``observe``: "agreement", "chosen:<name>" or "mean:<name>" (a name the Fusion declares).
    ``otherwise``: "abstain" (the Case abstains with gate_not_met), an sf.Judge(returns="label")
    that names a member whose text is the answer, or an sf.Model that writes the answer.
    In this version the fallback call runs on every Case; the gate chooses and records.
    """

    observe: str
    cmp: GateCmp
    threshold: float
    otherwise: Literal["abstain"] | Judge | Model

    def __init__(
        self,
        observe: str,
        cmp: GateCmp,
        threshold: float,
        *,
        otherwise: Literal["abstain"] | Judge | Model = "abstain",
    ) -> None:
        checked_observe = _observe(observe)
        checked_cmp = _cmp(cmp)
        number = _threshold(threshold)
        _check_agreement(checked_observe, checked_cmp, number)
        object.__setattr__(self, "observe", checked_observe)
        object.__setattr__(self, "cmp", checked_cmp)
        object.__setattr__(self, "threshold", number)
        object.__setattr__(self, "otherwise", _otherwise(otherwise))

    def _spec(self) -> dict[str, object]:
        """{"cmp", "observe", "otherwise": "abstain" | "judge" | "writer", "threshold": float}."""
        return {
            "cmp": self.cmp,
            "observe": self.observe,
            "otherwise": _otherwise_word(self.otherwise),
            "threshold": self.threshold,
        }

    def _signal_call(self) -> _ModelSignal | None:
        """The fallback model call the vote's combine step reads; None for abstain.

        SEAM (plan §2): E4b part 5 unit 4 builds the judge and writer calls here.
        """
        if isinstance(self.otherwise, str):
            return None
        raise NotImplementedError(
            "a judge or model gate fallback compiles from E4b part 5 unit 4 on"
        )

    def _declared_name(self) -> str | None:
        """<name> of chosen:<name> / mean:<name>; None for agreement."""
        if self.observe == _AGREEMENT:
            return None
        return self.observe.split(":", 1)[1]

    def __repr__(self) -> str:
        return self._render("Gate", repr)

    def _python(self) -> str:
        return self._render("sf.Gate", _python_form)

    def _render(self, head: str, show: Callable[[Judge | Model], str]) -> str:
        # WHY no otherwise for abstain: the default keeps the repr short (GA-D8).
        otherwise = "" if isinstance(self.otherwise, str) else f", otherwise={show(self.otherwise)}"
        return f"{head}({self.observe!r}, {self.cmp!r}, {self.threshold!r}{otherwise})"

    # WHY unhashable (as sf.Vote): a gate may hold an sf.Model, which is unhashable.
    __hash__: ClassVar[Any] = None


def _observe(value: object) -> str:
    """``value`` when it is agreement, chosen:<name> or mean:<name> with a declared name."""
    if not isinstance(value, str):
        raise TypeError("Gate observe must be text")
    if value == _AGREEMENT:
        return value
    form, colon, name = value.partition(":")
    named = bool(colon) and form in _NAMED_FORMS
    if named and is_signal_name(name):
        return value
    # WHY the hint: chosen:cost_usd looks right but reads an E4a key, not a declared signal.
    hint = _E4A_HINT if named and is_signal_key(name) else ""
    raise ValueError(_OBSERVE_RULE + hint)


def _cmp(value: object) -> GateCmp:
    if value not in _CMPS:
        raise ValueError("Gate cmp must be '>=', '>', '<=' or '<'")
    return cast("GateCmp", value)


def _threshold(value: object) -> float:
    """A finite float; an int is stored as a float, a bool is refused."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("Gate threshold must be a number")
    try:
        number = float(value)
    except OverflowError:  # an int beyond the float range
        raise ValueError("Gate threshold must be finite") from None
    if not math.isfinite(number):
        raise ValueError("Gate threshold must be finite")
    return number


def _check_agreement(observe: str, cmp: GateCmp, threshold: float) -> None:
    """P4: an agreement gate keeps a high agreement, and an agreement is a share in [0, 1]."""
    if observe != _AGREEMENT:
        return
    if cmp not in _KEEP_HIGH:
        raise ValueError(
            "an agreement gate keeps the majority when the agreement is high; use '>=' or '>'"
        )
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("an agreement gate threshold must be between 0 and 1")


def _otherwise(value: object) -> Literal["abstain"] | Judge | Model:
    """The checked fallback. The messages never echo a rubric or a prompt."""
    if isinstance(value, str):
        if value != _ABSTAIN:
            raise ValueError(_OTHERWISE_RULE)
        return _ABSTAIN
    if isinstance(value, Judge):
        if value.returns != "label":
            raise ValueError(
                "a gate fallback judge needs sf.Judge(..., returns='label'): it names one member"
            )
        return value
    if isinstance(value, Model):
        # WHY _sample_id: it holds an explicit name= (Model.__repr__ reads it the same way).
        if value._sample_id is not None or value.optional:
            raise ValueError("a gate fallback sf.Model takes no name= and is never optional")
        return value
    raise TypeError(_OTHERWISE_RULE)


def _otherwise_word(value: Literal["abstain"] | Judge | Model) -> str:
    """The spec word (erd §1). The model, prompt and params live in the url4 fallback call."""
    if isinstance(value, Judge):
        return "judge"
    if isinstance(value, Model):
        return "writer"
    return "abstain"


def _python_form(value: Judge | Model) -> str:
    """``sf.Judge(...)`` or ``sf.Model(...)``: the text ``Url4.to_python`` writes."""
    return f"sf.{value!r}"


__all__ = ["Gate"]
