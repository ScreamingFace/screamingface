"""``Gate``: keep the vote's answer only when a condition holds (E4b surface, surface §7, D5).

FEATURE: ``Gate(*, when, then, otherwise="abstain", abstain_if=None)`` closes a block. ``when``
compares a gate reference with a finite number; it is the condition that keeps the vote's answer.
``then`` is a ``Vote``. ``otherwise`` gives the answer when the condition fails. A gate lowers to
today's ``sf.Vote(gate=sf.Gate(observe, cmp, threshold, ...))`` (lowering §2.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from screamingface._surface.chain import Step, _Category
from screamingface._surface.judge import JudgePick
from screamingface._surface.refs import GateBand, GateCondition, is_rule_name
from screamingface._surface.steps import Vote, _check_by_lowering
from screamingface._surface.synthesize import Synthesize
from screamingface.model import Model
from screamingface.recipe import Recipe

type Fallback = Literal["abstain"] | JudgePick | Synthesize

_ABSTAIN: Literal["abstain"] = "abstain"
_OTHERWISE_RULE = "sf.Gate otherwise= takes 'abstain', sf.JudgePick(...) or sf.Synthesize(...)"


@dataclass(frozen=True, slots=True, init=False)
class Gate(Step):
    """Keep the vote's answer when ``when`` holds; else ``otherwise`` gives the answer.

    ``when``: ``sf.agreement() >= x`` (``>=`` or ``>``, ``x`` in [0, 1]),
    ``sf.signal("name").chosen() <op> x`` (the declared signal of the member the vote chose) or
    ``sf.signal("name").mean() <op> x`` (its mean over the members), with ``>=``, ``>``, ``<=``
    or ``<`` and a finite number. ``name`` is a name the block's ``sf.Fanout`` declares.

    ``then``: a ``sf.Vote`` whose ``over=`` is a rule name (until E4c). ``otherwise``:
    ``"abstain"`` (the Case abstains with ``gate_not_met``), a ``sf.JudgePick`` that names a
    member, or a ``sf.Synthesize`` with one model that writes the answer.

    ``abstain_if=ref.between(lo, hi)`` reads the same number as ``when``: inside the closed band
    the Case abstains with ``in_band``, for every ``otherwise``.

    In E4b the ``otherwise`` call runs on every Case, also when the gate keeps the vote's answer;
    E4c will skip it when the gate passes.
    """

    _category: ClassVar[_Category] = "reduce"
    when: GateCondition
    then: Vote
    otherwise: Fallback
    abstain_if: GateBand | None

    def __init__(
        self,
        *,
        when: GateCondition,
        then: Vote,
        otherwise: Fallback = _ABSTAIN,
        abstain_if: GateBand | None = None,
    ) -> None:
        if not isinstance(when, GateCondition):
            raise TypeError(
                "sf.Gate when= takes a condition such as sf.agreement() >= 0.7 or "
                "sf.signal('x').mean() <= 3.0"
            )
        object.__setattr__(self, "when", when)
        object.__setattr__(self, "then", _vote(then))
        object.__setattr__(self, "otherwise", _fallback(otherwise))
        object.__setattr__(self, "abstain_if", _band(abstain_if, when))
        _check_by_lowering(self)

    def _reads_judge(self) -> bool:
        return self.then._reads_judge()

    def _sees_every_member(self) -> bool:
        # WHY: a judge or writer fallback makes its own call over the whole Fusion context (O11).
        return not isinstance(self.otherwise, str)

    def _recipes(self) -> tuple[Recipe, ...]:
        return self.otherwise._recipes() if isinstance(self.otherwise, Synthesize) else ()

    __hash__: ClassVar[Any] = None


def _vote(value: object) -> Vote:
    if not isinstance(value, Vote):
        raise TypeError("sf.Gate then= takes sf.Vote until E4c")  # GA-3 (D5)
    if not is_rule_name(value.over):
        # GA-6 (O14): today's gated Vote holds an operator name only.
        raise ValueError("a gated vote reads a rule name in over= until E4c")
    return value


def _fallback(value: object) -> Fallback:
    if isinstance(value, str):
        if value != _ABSTAIN:
            raise ValueError(_OTHERWISE_RULE)
        return _ABSTAIN
    if isinstance(value, JudgePick):
        return value
    if not isinstance(value, Synthesize):
        raise TypeError(_OTHERWISE_RULE)
    if not isinstance(value.model, Model):
        raise ValueError(  # GA-4: the part 5 writer fallback is one model call
            "sf.Gate otherwise=sf.Synthesize(...) makes one model call: give it a model route "
            "or a sf.Model"
        )
    return value


def _band(value: object, when: GateCondition) -> GateBand | None:
    if value is None:
        return None
    if not isinstance(value, GateBand):
        raise TypeError("sf.Gate abstain_if= takes ref.between(lo, hi)")
    if value.ref != when.ref:
        # GA-5 (O5): the Engine band is on the gated number.
        raise ValueError("abstain_if must read the same number as when")
    return value


__all__ = ["Gate"]
