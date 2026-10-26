"""``sf.Cascade``: run the cheap stage first; call the next stage only when the signal is weak.

FEATURE: E4c (OME-1291, cascade PRD, ans:Q6, ans:Q7, ans:Q17). ``sf.Cascade(stages,
escalate_if=..., otherwise=None)`` is a shortcut function. It returns ordinary nested ``sf.Gate``
values, the way ``sf.Fusion`` returns the ``sf.Fanout(...) >> S`` chain, so ``==``, ``repr`` and
``Url4.to_python()`` show the Gate form and it compiles to the same bytes (CA-1, CA-21).
STORY: as a researcher whose result is a saving, the expensive model runs only on the Cases that
need it, and a stage that fails or abstains escalates instead of failing the Case.

INVARIANT: every gated stage is a block that ends in a reducer step; its members are optional and
its panel has quorum 0, so a failed member never fails the stage (CA-6, ans:Q24).
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import Literal

from screamingface._environment import SDK_PACKAGE_ROOT
from screamingface._surface.chain import Pipeline, Step, _Block
from screamingface._surface.fanout import Fanout
from screamingface._surface.gate import Gate
from screamingface._surface.refs import AnsweredCondition, GateCondition, _condition, answered
from screamingface._surface.steps import Vote
from screamingface.model import Model
from screamingface.recipe import Recipe, _inferred_name, _kept_name
from screamingface.warnings import CascadeSeedWarning

type Stage = str | Recipe
type Escalation = GateCondition | Sequence[GateCondition] | None

# The keep form of an escalate form (CA-4): the condition that keeps a stage's answer.
_KEEP = {"<": ">=", "<=": ">", ">": "<=", ">=": "<"}
_STAGE_SHAPE = (
    "a cascade stage before the last must end in a reducer step such as sf.Vote(): write "
    "sf.Fanout([m], signals=...) >> sf.Vote()"
)


def Cascade(  # noqa: N802 - the public name of a shortcut, like sf.Fusion
    stages: Sequence[Stage],
    *,
    escalate_if: Escalation = None,
    otherwise: Literal["abstain", "fail_closed"] | None = None,
) -> Recipe:
    """Run ``stages[0]``; call the next stage only when ``escalate_if`` holds, or the stage failed.

    ``escalate_if`` is a comparison on a number of the stage's answers, in the escalate form the
    author thinks in: ``sf.agreement() < 0.8``, ``sf.signal("conf").chosen() < 0.7``. One
    condition applies to every gated stage; a list gives one per gated stage. ``None`` escalates
    only when a stage fails or abstains (first success). A stage that fails or abstains always
    escalates. Each later stage answers the original question, never the previous answer.

    A gated stage is a block that ends in a reducer step (``sf.Fanout([...]) >> sf.Vote()``); with
    ``escalate_if=None`` a route string or ``sf.Model`` is wrapped as ``sf.Fanout([m]) >>
    sf.Vote()``. Its members become optional and its panel takes ``quorum=0``.

    ``otherwise=None``: the last stage answers unconditionally and its failure fails the Case.
    ``"abstain"`` gates the last stage too: when it escalates, the Case abstains (a scored
    decline, the human last tier); ``"fail_closed"`` fails the Case with ``fail_closed``.

    A cascade decides per full answer; no API escalates inside one decode. Adaptive sampling is a
    cascade over sample panels: stage 2 does not reuse stage 1's samples, so give it fresh
    ``seeds=``. ``sf.Cascade`` is a function, so ``isinstance(x, sf.Cascade)`` is not supported.
    """

    if isinstance(stages, str) or not isinstance(stages, Sequence) or len(stages) < 2:
        raise ValueError("sf.Cascade needs at least two stages")
    if otherwise not in (None, "abstain", "fail_closed"):
        raise ValueError("sf.Cascade otherwise= takes None, 'abstain' or 'fail_closed'")
    gated = len(stages) if otherwise is not None else len(stages) - 1
    conditions = _conditions(escalate_if, gated)
    blocks = [_stage(stages[index], conditions[index]) for index in range(gated)]
    _warn_repeated_seeds([_members(stage) for stage in stages])
    rest: Stage | Literal["abstain", "fail_closed"] = (
        otherwise if otherwise is not None else stages[-1]
    )
    for index in range(gated - 1, -1, -1):
        fanout, judge, step = blocks[index]
        rest = _gated(fanout, judge, step, conditions[index], index + 1, rest)
    assert isinstance(rest, Recipe)
    return rest


def _conditions(escalate_if: Escalation, gated: int) -> list[GateCondition | None]:
    """One escalate condition (or None) per gated stage (CA-5, CA-16)."""

    if escalate_if is None or isinstance(escalate_if, GateCondition):
        return [escalate_if] * gated
    if isinstance(escalate_if, str) or not isinstance(escalate_if, Sequence):
        raise TypeError(
            "sf.Cascade escalate_if= takes a condition such as sf.agreement() < 0.8, or a list"
        )
    conditions: list[GateCondition | None] = list(escalate_if)
    if len(conditions) != gated or not all(isinstance(item, GateCondition) for item in conditions):
        raise ValueError(
            f"sf.Cascade escalate_if= takes one condition or one per gated stage ({gated})"
        )
    return conditions


def _stage(value: Stage, condition: GateCondition | None) -> tuple[Fanout, Step | None, Step]:
    """A gated stage as its Fanout (members optional, quorum 0), its judge and its reducer step."""

    if isinstance(value, str | Model):
        if condition is not None:
            raise TypeError(_STAGE_SHAPE)
        value = Fanout([value]) >> Vote()  # CA-10: a first-success stage answers verbatim
    block = _single_block(value)
    fanout = block.fanout
    if fanout.quorum != "all":
        raise ValueError(  # CA-17 (ans:Q24)
            "a cascade stage decides on the members that answered; it takes quorum='all'"
        )
    members = [_optional(member) for member in fanout.members]
    stage_fanout = Fanout(
        members,
        signals=fanout.signals,
        quorum=0,
        name=_kept_name(fanout.name, _inferred_name(fanout.members)),
        prompt=fanout.prompt,
    )
    return stage_fanout, block.judge, block.terminal


def _single_block(value: object) -> _Block:
    """The one closed block of a stage chain that ends in a reducer step, else CA-13."""

    if not isinstance(value, Pipeline) or value._open or len(value._stages) != 1:
        raise TypeError(_STAGE_SHAPE)
    block = value._stages[0]
    if not isinstance(block, _Block) or block.narrow or block.terminal._category != "reduce":
        raise TypeError(_STAGE_SHAPE)
    if isinstance(block.terminal, Gate):
        raise TypeError(_STAGE_SHAPE)
    return block


def _optional(member: Recipe) -> Recipe:
    """A member marked optional (CA-6); a member already optional stays as it is (CA-24)."""

    if member.optional:
        return member
    if isinstance(member, Model):
        return Model(
            member.model,
            name=member._sample_id,
            prompt=member.prompt,
            params=member.params,
            optional=True,
        )
    if isinstance(member, Pipeline):
        return Pipeline(
            list(member.steps), name=member.name if member._is_named else None, optional=True
        )
    raise TypeError("a cascade stage member is a model route, a sf.Model or a chain")


def _keep(condition: GateCondition | None) -> GateCondition | AnsweredCondition:
    """The keep form of an escalate form (CA-4); None keeps a stage that answered (CA-10)."""

    if condition is None:
        return answered()
    return _condition(condition.ref, _KEEP[condition.cmp], condition.threshold)  # type: ignore[arg-type]


def _gated(
    fanout: Fanout,
    judge: Step | None,
    step: Step,
    condition: GateCondition | None,
    number: int,
    rest: Stage | Literal["abstain", "fail_closed"],
) -> Recipe:
    try:
        gate = Gate(when=_keep(condition), then=step, otherwise=rest)
    except ValueError as exc:
        # CA-15: the refusal names the escalate form the author wrote.
        raise ValueError(f"sf.Cascade stage {number}: escalate_if={condition!r}: {exc}") from None
    try:
        chain = fanout >> judge >> gate if judge is not None else fanout >> gate
    except ValueError as exc:
        # CA-14: a block rule (an undeclared signal) names the stage the author wrote.
        raise ValueError(f"sf.Cascade stage {number}: {exc}") from None
    return chain


def _members(stage: Stage) -> tuple[Recipe, ...]:
    """The Fanout members of a stage that is one block; none for any other stage."""

    if isinstance(stage, Pipeline) and stage._stages and isinstance(stage._stages[0], _Block):
        return stage._stages[0].fanout.members
    return ()


def _warn_repeated_seeds(stages: list[tuple[Recipe, ...]]) -> None:
    """CA-23: equal sample requests can be gateway cache hits with the same text."""

    seen: dict[tuple[str, object], int] = {}
    for number, members in enumerate(stages, start=1):
        repeated: dict[int, list[str]] = {}
        for member in members:
            if isinstance(member, Model) and "seed" in member.params:
                key = (member.model, member.params["seed"])
                if key in seen:
                    repeated.setdefault(seen[key], []).append(str(member.params["seed"]))
                else:
                    seen[key] = number
        for earlier, seeds in repeated.items():
            warnings.warn(
                f"sf.Cascade stage {number} repeats seeds {', '.join(seeds)} of stage {earlier}; "
                "give seeds= for fresh samples",
                CascadeSeedWarning,
                skip_file_prefixes=(SDK_PACKAGE_ROOT,),
            )


__all__ = ["Cascade"]
