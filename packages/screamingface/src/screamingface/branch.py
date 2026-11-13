"""The internal sf.Gate node: one branch construct for routers, cascades and guards (E4c).

FEATURE: OME-1291 — a model in the recipe might not be called. Every public ``sf.Gate`` (and every
``sf.Cascade`` stage) lowers to one ``BranchNode``; the compiler renders it as a gated url4
iterate per branch, so the branch that is not selected makes zero model calls
(``_evaluation/branch.py``, branch-core §2.2).
STORY: as the compiler, I read one value that says what the Gate compares, what each branch is
(a recipe, the decision call's own reducer, or a word), and the panel block of a panel gate.

INVARIANT: internal only. The public surface (``_surface/gate.py``) builds and checks it; this
module holds data and the few rules every builder shares.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from screamingface._surface.selectors import Selector
from screamingface.fusion import FusionNode
from screamingface.recipe import Recipe
from screamingface.reducer import Reducer

if TYPE_CHECKING:
    from screamingface.gate import GateNode
    from screamingface.reducer import _ReducerPlan

type Word = Literal["abstain", "fail_closed"]
# A branch: a recipe, a reducer step (panel gates), a word, or None = skip (a skip-Gate member's
# otherwise, ans:Q16).
type Body = Recipe | Reducer | Word | None

WORDS: tuple[Word, Word] = ("abstain", "fail_closed")
MAX_GATE_DEPTH = 8
# GT-27 (ans:Q26): the message for a sf.Gate inside a sf.CorrectiveLoop, shared by each check.
GATE_IN_LOOP = (
    "a sf.Gate cannot sit inside a sf.CorrectiveLoop, and a sf.CorrectiveLoop cannot "
    "be a sf.Gate branch"
)
# The panel forms of a condition (erd §1): they read the decision call of a Fanout block.
_PANEL_OBSERVE = ("agreement", "answered", "chosen:", "mean:")


@dataclass(frozen=True, slots=True)
class BranchCondition:
    """The one comparison a Gate makes, as data (GATE_SPEC ``when``).

    ``observe`` is ``label``/``labels`` (with ``selector``), ``budget.remaining:<unit>``, or a
    panel form: ``agreement``, ``chosen:<name>``, ``mean:<name>``, ``answered``.
    """

    observe: str
    cmp: str
    value: float | str | bool | None
    selector: Selector | None = None

    __hash__: ClassVar[Any] = None

    @property
    def panel(self) -> bool:
        return self.observe.startswith(_PANEL_OBSERVE)


class BranchNode(Recipe):
    """Run ``then`` when ``condition`` holds and ``otherwise`` when it does not.

    ``panel`` is the Fanout block of a panel gate: its synthesizer is the decision reducer, whose
    one combine call the condition reads. A ``then``/``otherwise`` that IS that reducer is the
    step slot: the decision call itself answers, with no gated body.
    """

    __slots__ = ("condition", "estimates", "name", "optional", "otherwise", "panel", "then")

    condition: BranchCondition
    then: Body
    otherwise: Body
    panel: FusionNode | None

    def __init__(
        self,
        *,
        condition: BranchCondition,
        then: Body,
        otherwise: Body,
        panel: FusionNode | None = None,
        name: str = "gate",
        estimates: tuple[Mapping[str, float | int] | None, Mapping[str, float | int] | None] = (
            None,
            None,
        ),
    ) -> None:
        if condition.panel != (panel is not None):
            raise ValueError("a panel condition reads a sf.Fanout block, an input condition none")
        if then is None:
            raise ValueError("a gate takes a then= branch")
        object.__setattr__(self, "condition", condition)
        object.__setattr__(self, "then", then)
        object.__setattr__(self, "otherwise", otherwise)
        object.__setattr__(self, "panel", panel)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "optional", False)
        # E4c budget (BU-3): the author's estimate of each branch, {"usd": n, "tokens": n} or None.
        object.__setattr__(self, "estimates", estimates)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("a BranchNode is immutable")

    @property
    def _recipe_marker(self) -> None:
        return None

    def decision_reducer(self) -> Reducer | None:
        """The panel block's reducer: the decision call's own step, or None for an input gate."""

        if self.panel is None:
            return None
        synthesizer = self.panel.synthesizer
        return synthesizer if isinstance(synthesizer, Reducer) else None

    def body(self, branch: Literal["then", "otherwise"]) -> Body:
        return self.then if branch == "then" else self.otherwise

    __hash__: ClassVar[Any] = None

    def __repr__(self) -> str:
        return (
            f"BranchNode(condition={self.condition!r}, then={self.then!r}, "
            f"otherwise={self.otherwise!r})"
        )


class _DelegatingReducer(Reducer):
    """A reducer wrapper whose step name, context check and member check come from ``_inner``."""

    __slots__ = ()

    @property
    @abstractmethod
    def _inner(self) -> Reducer:
        """The reducer step this wrapper delegates to."""

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"a {type(self).__name__} is immutable")

    def _step_name(self) -> str:
        return self._inner._step_name()

    def _whole_context_call(self) -> str | None:
        return self._inner._whole_context_call()

    def _check_members(self, count: int) -> None:
        self._inner._check_members(count)

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Reducer:
        raise ValueError("URL4 Candidate has a gate spec this SDK version cannot rebuild")


class DecisionReducer(_DelegatingReducer):
    """A panel gate's decision reducer: a reducer step plus the gate its combine call records.

    WHY a wrapper: E4c puts a gate on any reducer that answers (P3); the gate's ``otherwise`` is
    always ``"abstain"`` here, because the Gate's branches, not the combine call, act on the
    fallback branch (branch-core D4). The combine spec gains the ``gate`` object; nothing else of
    the step changes.
    """

    __slots__ = ("gate", "step")

    step: Reducer
    gate: GateNode

    def __init__(self, step: Reducer, gate: GateNode) -> None:
        if gate.otherwise != "abstain":
            raise ValueError("a decision gate takes no fallback call: the gate branches act")
        object.__setattr__(self, "step", step)
        object.__setattr__(self, "gate", gate)
        object.__setattr__(self, "name", step.name)
        object.__setattr__(self, "_narrow", ())

    @property
    def _inner(self) -> Reducer:
        return self.step

    def _plan(self) -> _ReducerPlan:
        return replace(self.step._combine_plan(), gate=self.gate)

    __hash__: ClassVar[Any] = None

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, DecisionReducer)
            and self.step == other.step
            and self.gate == other.gate
        )

    def __repr__(self) -> str:
        return f"DecisionReducer({self.step!r}, {self.gate!r})"


class LazyDecision(_DelegatingReducer):
    """Call #1 of a lazy E4b fallback (lazy-fallback delta 1): the full gated vote's own spec,
    without the fallback call, sent with ``phase=decide``.

    ``full`` is the gated vote of E4b (its gate names the judge or writer fallback). The Gate's
    ``otherwise`` body compiles ``full`` as call #2, with the fallback call, so the fallback runs
    only when the gate takes it. The spec bytes of both calls are equal (FB-I1, E4b C8).
    """

    __slots__ = ("full", "gate")

    full: Reducer
    gate: GateNode

    def __init__(self, full: Reducer) -> None:
        gate = getattr(full, "gate", None)
        if gate is None or gate.otherwise == "abstain":
            raise ValueError("a lazy decision wraps a gated vote with a judge or writer fallback")
        object.__setattr__(self, "full", full)
        object.__setattr__(self, "gate", gate)
        object.__setattr__(self, "name", full.name)
        object.__setattr__(self, "_narrow", ())

    @property
    def _inner(self) -> Reducer:
        return self.full

    def _plan(self) -> _ReducerPlan:
        from screamingface.reducer import _FALLBACK_KEYS

        plan = self.full._combine_plan()
        fallback = set(_FALLBACK_KEYS.values())
        calls = tuple(call for call in plan.signal_calls if call.key not in fallback)
        return replace(plan, signal_calls=calls)

    __hash__: ClassVar[Any] = None

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LazyDecision) and self.full == other.full

    def __repr__(self) -> str:
        return f"LazyDecision({self.full!r})"


def _is_skip_member(member: Recipe) -> bool:
    """A skip-Gate Fanout member (E4c, ans:Q16): a Gate node with no otherwise."""

    return isinstance(member, BranchNode) and member.otherwise is None


__all__: list[str] = []
