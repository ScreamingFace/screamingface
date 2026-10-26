"""``Gate``: run ``then`` when a condition holds and ``otherwise`` when it does not (E4b, E4c).

FEATURE: ``Gate(*, when, then, otherwise=None, abstain_if=None)`` is the one branch construct
(E4c, OME-1291, ans:Q6, ans:Q9). It has two forms, and ``when=`` says which:

- a **panel gate** reads a number on the answers of a ``sf.Fanout`` block (``sf.agreement()``,
  ``sf.signal(x).chosen()`` or ``.mean()``); it closes the block, like a reducer step;
- an **input gate** reads a label of the Case input (``sf.label(sel) == "x"``,
  ``sf.labels(sel).has("x")``); it is a recipe: the candidate, a Pipeline stage or a branch.

``then=`` and ``otherwise=`` each take a reducer step (panel gates), a recipe (a model route, a
``sf.Model``, a chain, another input ``sf.Gate``) or a word: ``"abstain"`` or ``"fail_closed"``.
A branch that is not taken makes zero model calls, and the report says why. An N-way choice is
nested Gates. ``otherwise`` left out means ``"abstain"`` (and "skip" for a Fanout member Gate).

A panel gate whose branches are only the block's reducer and ``"abstain"`` (or an E4b
``sf.JudgePick`` / ``sf.Synthesize`` fallback) compiles to the one combine call of E4b; every other
gate compiles to the gated branch shape (``_evaluation/branch.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal, cast

from screamingface._surface.budget import BudgetCondition, Estimate
from screamingface._surface.chain import Step, _Category
from screamingface._surface.judge import JudgePick
from screamingface._surface.refs import (
    AnsweredCondition,
    GateBand,
    GateCondition,
    is_rule_name,
)
from screamingface._surface.selectors import LabelCondition
from screamingface._surface.steps import (
    ArgMax,
    ArgMin,
    First,
    Mean,
    Median,
    Merge,
    Vote,
    _check_by_lowering,
)
from screamingface._surface.synthesize import Synthesize
from screamingface.branch import GATE_IN_LOOP
from screamingface.model import Model
from screamingface.recipe import _BU11, Recipe

# The E4b fallback of a vote gate (kept for the one-call compile and its lowering).
type Fallback = Literal["abstain"] | JudgePick | Synthesize
type Branch = Step | Recipe | str | Estimate
type Condition = GateCondition | AnsweredCondition | LabelCondition | BudgetCondition

_ABSTAIN: Literal["abstain"] = "abstain"
_WORDS: tuple[str, ...] = ("abstain", "fail_closed")
# The reducer steps a panel gate's branch may be (gate GT-6, ans:Q6).
_REDUCE_STEPS: tuple[type, ...] = (Vote, Median, Mean, ArgMax, ArgMin, First, Merge, JudgePick)
# The steps that choose one member, so a chosen:<name> gate can read the chosen member's value.
_CHOOSING_STEPS: tuple[type, ...] = (Vote, ArgMax, ArgMin, First, JudgePick)
_WHEN_RULE = (
    "sf.Gate when= takes a condition such as sf.agreement() >= 0.7, sf.label(sel) == 'x' "
    "or sf.budget.remaining() >= 0.02"
)
_GUARD_RULE = (
    "sf.Gate when= takes a condition such as sf.label(sel) == 'x'; a guard cannot run Python code"
)
_PANEL_STEP = "a step in {name}= needs a panel: put the sf.Gate after a sf.Fanout, or give a recipe"


def _branch_rule(name: str) -> str:
    return f"sf.Gate {name}= takes a step, a recipe, 'abstain' or 'fail_closed'"


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Gate(Step, Recipe):
    """Run ``then`` when ``when`` holds; else ``otherwise``. The branch not taken makes no call.

    ``when``: a panel condition (``sf.agreement() >= x`` with ``>=`` or ``>`` and ``x`` in
    [0, 1], ``sf.signal("name").chosen() <op> x``, ``sf.signal("name").mean() <op> x``), which
    closes a ``sf.Fanout`` block; or an input condition (``sf.label(sel) == "x"``, ``!=``,
    ``sf.labels(sel).has("x")``, ``.empty()``), which makes the Gate a recipe. Routing decides
    before any answer exists, from the question; a cascade decides after an answer, from a number
    on it.

    ``then`` / ``otherwise``: a reducer step (``sf.Vote()``, ``sf.Median()``, ... ; panel gates
    only), a recipe, ``"abstain"`` (the Case declines with ``gate_not_met``) or ``"fail_closed"``
    (the Case fails with the code ``fail_closed`` and no model runs after the Gate). A recipe
    branch answers the Gate's input. ``otherwise`` left out is ``"abstain"``.

    ``abstain_if=ref.between(lo, hi)`` (panel gates) reads the same number as ``when``: inside
    the closed band the Case abstains with ``in_band`` and no branch runs.

    The fallback branch runs only on the Cases where the gate takes it: the branch that is not
    taken makes no model call, and the report shows it as not run.
    """

    _category: ClassVar[_Category] = "reduce"
    when: Condition
    then: Branch
    otherwise: Branch | None
    abstain_if: GateBand | None
    # E4c budget (BU-3): the author's sf.Estimate of each branch, unwrapped from then=/otherwise=.
    estimates: tuple[Estimate | None, Estimate | None]

    def __init__(
        self,
        *,
        when: Condition,
        then: Branch,
        otherwise: Branch | None = None,
        abstain_if: GateBand | None = None,
    ) -> None:
        panel = _condition(when)
        then_estimate, then = cast("tuple[Estimate | None, Branch]", _estimated(then))
        otherwise_estimate, otherwise = cast(
            "tuple[Estimate | None, Branch | None]", _estimated(otherwise)
        )
        object.__setattr__(self, "when", when)
        object.__setattr__(self, "then", _branch(then, "then", panel))
        object.__setattr__(
            self, "otherwise", None if otherwise is None else _branch(otherwise, "otherwise", panel)
        )
        object.__setattr__(self, "estimates", (then_estimate, otherwise_estimate))
        object.__setattr__(self, "abstain_if", _band(abstain_if, when))
        if panel:
            _check_panel(self)
            _check_by_lowering(self)

    # --- the two forms ----------------------------------------------------------------------------

    @property
    def _panel(self) -> bool:
        return isinstance(self.when, GateCondition | AnsweredCondition)

    def _is_recipe(self) -> bool:
        """An input gate is a recipe (the candidate, a stage, a branch); a panel gate is a step."""

        return not self._panel

    @property
    def name(self) -> str:
        return "gate"

    @property
    def optional(self) -> bool:
        return False

    @property
    def _recipe_marker(self) -> None:
        return None

    def _budget_condition(self) -> BudgetCondition | None:
        return self.when if isinstance(self.when, BudgetCondition) else None

    def _is_skip_member(self) -> bool:
        """Whether this Gate can be a Fanout member (a skip-Gate, ans:Q16, SM-8): an input gate
        with no ``otherwise=`` and a recipe in ``then=``. An unselected member makes no call."""

        return (
            self._is_recipe()
            and self.otherwise is None
            and isinstance(self.then, Recipe)
            and (not isinstance(self.then, Step) or self.then._is_recipe())
        )

    def _otherwise(self) -> Branch:
        """``otherwise`` with the sentinel resolved: ``"abstain"`` (a member Gate's skip is the
        Fanout's business, ``_surface/fanout.py``)."""

        return _ABSTAIN if self.otherwise is None else self.otherwise

    def _one_call(self) -> bool:
        """Whether this panel gate compiles to E4b's one combine call: its branches are the
        block's reducer and ``"abstain"``, or an E4b judge or writer fallback (E4b bytes, GT-17)."""

        # E4c (lazy-fallback delta 1): a judge or writer fallback runs only in the Gate's fallback
        # branch, so only the abstain word keeps the one combine call.
        return (
            isinstance(self.when, GateCondition)
            and isinstance(self.then, Step)
            and self._otherwise() == _ABSTAIN
        )

    def _steps(self) -> tuple[Step, ...]:
        return tuple(value for value in (self.then, self.otherwise) if isinstance(value, Step))

    def _reads_judge(self) -> bool:
        return any(step._reads_judge() for step in self._steps())

    def _sees_every_member(self) -> bool:
        # WHY: a judge or writer fallback makes its own call over the whole fanout context (O11).
        return isinstance(self.otherwise, JudgePick | Synthesize)

    def _recipes(self) -> tuple[Recipe, ...]:
        held: list[Recipe] = []
        for value in (self.then, self.otherwise):
            if isinstance(value, Synthesize):
                held.extend(value._recipes())
            elif isinstance(value, Recipe):
                held.append(value)
        return tuple(held)

    __hash__: ClassVar[Any] = None


def _condition(value: object) -> bool:
    """True for a panel condition, False for an input condition, else TypeError (GT-13, GU-8)."""

    if isinstance(value, GateCondition | AnsweredCondition):
        return True
    if isinstance(value, LabelCondition | BudgetCondition):
        return False
    if callable(value):
        raise TypeError(_GUARD_RULE)
    raise TypeError(_WHEN_RULE)


def _branch(value: object, name: str, panel: bool) -> Branch:
    """A checked branch value: a step (panel gates), a recipe, or a word (GT-11, GT-12, GU-8)."""

    if isinstance(value, str):
        return _word_or_route(value, name)
    if isinstance(value, Step) and not (isinstance(value, Gate) and value._is_recipe()):
        return _step_branch(value, name, panel)
    if isinstance(value, Recipe):
        return _recipe_branch(value)
    raise TypeError(_GUARD_RULE if callable(value) else _branch_rule(name))


def _estimated(value: object) -> tuple[Estimate | None, object]:
    """An ``sf.Estimate`` branch as (its estimate, the branch it wraps); any other as (None, it)."""

    if isinstance(value, Estimate):
        if (
            isinstance(value.branch, Step)
            and not isinstance(value.branch, (JudgePick, Synthesize))
            and not (isinstance(value.branch, Gate) and value.branch._is_recipe())
        ):
            # BU-24: a reducer step makes no model call, so it has nothing to estimate.
            raise ValueError("sf.Estimate wraps a branch that makes model calls")
        return value, value.branch
    return None, value


def _word_or_route(value: str, name: str) -> Branch:
    if value in _WORDS:
        return value
    if value == "skip":
        raise TypeError(_branch_rule(name))
    return Model(value)


def _step_branch(value: Step, name: str, panel: bool) -> Step:
    if not isinstance(value, (*_REDUCE_STEPS, Synthesize)):
        raise TypeError(_branch_rule(name))
    if not panel:
        raise ValueError(_PANEL_STEP.format(name=name))
    return value


def _recipe_branch(value: Recipe) -> Recipe:
    # WHY lazy: corrective imports the recipe machinery this module builds on.
    from screamingface._surface.budget import Budget
    from screamingface.corrective import CorrectiveLoop, SelfCorrective

    if isinstance(value, Budget):
        raise ValueError(_BU11)  # BU-11
    if isinstance(value, CorrectiveLoop | SelfCorrective):
        raise ValueError(GATE_IN_LOOP)  # GT-27 (ans:Q26)
    return value


def _check_panel(gate: Gate) -> None:
    """The panel gate rules: the decision reducer (GT-6, GT-16) and the E4b fallbacks."""

    when = gate.when
    steps = gate._steps()
    otherwise = gate.otherwise
    if isinstance(otherwise, JudgePick | Synthesize):
        _check_e4b_fallback(gate.then, otherwise)
        return
    if isinstance(gate.then, Synthesize):
        raise TypeError(_branch_rule("then"))
    decision = next((step for step in steps if not isinstance(step, Synthesize)), None)
    if not isinstance(when, GateCondition):
        return  # sf.answered() reads the reducer's result, whichever reducer it is
    if when.ref.observe == "agreement" and decision is not None and not isinstance(decision, Vote):
        raise ValueError(
            "sf.agreement() needs a sf.Vote in then= or otherwise=, or no reducer step at all"
        )
    if (
        when.ref.observe.startswith("chosen:")
        and decision is not None
        and not isinstance(decision, _CHOOSING_STEPS)
    ):
        raise ValueError(
            "sf.signal(x).chosen() needs a step that chooses one member in then= or otherwise="
        )


def _check_e4b_fallback(then: Branch, otherwise: JudgePick | Synthesize) -> None:
    """The E4b judge or writer fallback: the vote of ``then`` decides, the fallback answers."""

    if not isinstance(then, Vote):
        raise TypeError(
            "sf.Gate with a sf.JudgePick or sf.Synthesize fallback takes a sf.Vote in then="
        )
    if not is_rule_name(then.over):
        raise ValueError("a vote with a judge or writer fallback reads a rule name in over=")
    if isinstance(otherwise, Synthesize) and not isinstance(otherwise.model, Model):
        raise ValueError(  # GA-4: the writer fallback is one model call
            "sf.Gate otherwise=sf.Synthesize(...) makes one model call: give it a model route "
            "or a sf.Model"
        )


def _band(value: object, when: Condition) -> GateBand | None:
    if value is None:
        return None
    if not isinstance(value, GateBand):
        raise TypeError("sf.Gate abstain_if= takes ref.between(lo, hi)")
    if not isinstance(when, GateCondition) or value.ref != when.ref:
        # GA-5 (O5): the Engine band is on the gated number.
        raise ValueError("abstain_if must read the same number as when")
    return value


__all__ = ["Gate"]
