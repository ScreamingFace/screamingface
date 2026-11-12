"""``sf.Cascade``: run the cheap tier first; call the next tier only where a line says so.

FEATURE: E4c (OME-1291, cascade PRD, ans:Q6, ans:Q7; 2026-11-12 proposal review).
``sf.Cascade(t1, sf.escalate_if(c), t2)`` is a shortcut function. The tiers are its arguments,
read top to bottom, and each escalation is its own line between the two tiers it connects. It
returns ordinary nested ``sf.Gate`` values, the way ``sf.Fusion`` returns the
``sf.Fanout(...) >> S`` chain, so ``==``, ``repr`` and ``Url4.to_python()`` show the Gate form and
it compiles to the same bytes (CA-1, CA-21).
STORY: as a researcher whose result is a saving, the expensive model runs only on the Cases that
need it, and the recipe says each reason to escalate.

INVARIANT: a Cascade escalates only through an ``sf.escalate_if`` line. A tier that fails fails
the Case, a tier whose number is missing fails it with ``signal_missing``, and a tier that
abstains makes the Case abstain; only ``sf.escalate_if(sf.unanswered())`` escalates on those.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

from screamingface._environment import SDK_PACKAGE_ROOT
from screamingface._surface.chain import Pipeline, Step, _Block
from screamingface._surface.fanout import Fanout
from screamingface._surface.gate import Gate, word_shaped
from screamingface._surface.outcomes import Outcome
from screamingface._surface.refs import (
    AnsweredCondition,
    GateCondition,
    _condition,
    answered,
    signal_condition,
)
from screamingface._surface.steps import Vote
from screamingface.combine_evidence import GateCmp
from screamingface.model import Model
from screamingface.recipe import Recipe, _inferred_name, _kept_name
from screamingface.warnings import CascadeSeedWarning

type Tier = str | Recipe


@dataclass(frozen=True, slots=True)
class Unanswered:
    """``sf.unanswered()``: the tier failed or abstained (the keep form is ``sf.answered()``)."""

    def __repr__(self) -> str:
        return "unanswered()"


def unanswered() -> Unanswered:
    """The condition that a tier gave no answer: it failed or abstained. Use it in
    ``sf.escalate_if(sf.unanswered())`` to call the next tier when a tier gives no answer."""

    return Unanswered()


type Escalation = GateCondition | Unanswered


@dataclass(frozen=True, slots=True)
class EscalateIf:
    """``sf.escalate_if(condition)``: the line between two ``sf.Cascade`` tiers."""

    condition: Escalation

    def __repr__(self) -> str:
        return f"escalate_if({self.condition!r})"


def escalate_if(condition: object) -> EscalateIf:
    """The line between two ``sf.Cascade`` tiers: call the next tier when ``condition`` holds.

    ``condition`` is a comparison on a number of the tier's answers, in the escalate form:
    ``sf.agreement() < 0.8``, ``sf.signal("lp") < 0.7`` (the chosen member's value), or
    ``sf.signal("cons").mean() < 0.8``. ``sf.unanswered()`` calls the next tier when the tier
    failed or abstained.
    """

    condition = signal_condition(condition)
    if not isinstance(condition, GateCondition | Unanswered):
        raise TypeError(_LINE_TYPE)
    return EscalateIf(condition)


# The keep form of an escalate form (CA-4): the condition that keeps a tier's answer.
_KEEP: dict[GateCmp, GateCmp] = {"<": ">=", "<=": ">", ">": "<=", ">=": "<"}
_LINE_TYPE = (
    "sf.escalate_if takes a condition such as sf.agreement() < 0.8, sf.signal('lp') < 0.7 or "
    "sf.unanswered()"
)
_FORM = (
    "sf.Cascade takes its tiers as arguments, with a line between each two: "
    "sf.Cascade(t1, sf.escalate_if(...), t2)"
)
_TIER_SHAPE = (
    "a cascade tier before a sf.escalate_if line must end in a reducer step such as "
    "sf.Vote(): write sf.Fanout([m], signals=...) >> sf.Vote()"
)


def Cascade(*parts: Tier | EscalateIf | Outcome) -> Recipe:  # noqa: N802 - like sf.Fusion
    """Run the first tier; call the next tier only when the ``sf.escalate_if`` line before it holds.

    ``sf.Cascade(t1, sf.escalate_if(c1), t2, sf.escalate_if(c2), t3)``: each tier answers the
    original question, never the previous answer. A tier followed by a line is a block that ends
    in a reducer step (``sf.Fanout([...]) >> sf.Vote()``); the last tier is any recipe, and its
    answer is final. Two tiers with no line between them are refused: the second could never run.

    Nothing escalates unless a line says so. A tier that fails fails the Case (a panel tier fails
    as its ``sf.Fanout`` quorum says), a tier whose number is missing fails it with
    ``signal_missing``, and a tier that abstains makes the Case abstain.
    ``sf.escalate_if(sf.unanswered())`` escalates when the tier failed or abstained (first
    success); its tier may be a model route or a ``sf.Model``, and its members become optional.

    The last part may be ``sf.abstain()`` (the Case abstains with ``gate_not_met``: a scored
    decline, the human last tier) or ``sf.fail()`` (the Case fails with ``fail_closed``) after a
    line: the last tier is then gated too.

    A cascade decides per full answer; no API escalates inside one decode. Adaptive sampling is a
    cascade over sample panels: tier 2 does not reuse tier 1's samples, so give it fresh
    ``seeds=``. ``sf.Cascade`` is a function, so ``isinstance(x, sf.Cascade)`` is not supported.
    """

    tiers, lines, outcome = _parts(parts)
    blocks = [_tier(tiers[index], lines[index].condition) for index in range(len(lines))]
    _warn_repeated_seeds([_members(tier) for tier in tiers])
    rest: Tier | Outcome = outcome if outcome is not None else tiers[-1]
    for index in range(len(lines) - 1, -1, -1):
        fanout, judge, step = blocks[index]
        rest = _gated(fanout, judge, step, lines[index].condition, index + 1, rest)
    assert isinstance(rest, Recipe)
    return rest


def _parts(
    parts: Sequence[object],
) -> tuple[list[Tier], list[EscalateIf], Outcome | None]:
    """The tiers, the lines and the closing outcome, in the one order a Cascade takes (CA-12)."""

    if len(parts) == 1 and isinstance(parts[0], list | tuple):
        raise TypeError(_FORM)  # the list form before 2026-11-12
    tiers: list[Tier] = []
    lines: list[EscalateIf] = []
    outcome: Outcome | None = None
    for part in parts:
        if outcome is not None:
            raise ValueError("sf.abstain() or sf.fail() is the last part of a sf.Cascade")
        outcome = _add(part, tiers, lines)
    if not lines or (outcome is None and len(lines) == len(tiers)):
        raise ValueError(
            "sf.Cascade needs a tier, a sf.escalate_if(...) line, and a tier, sf.abstain() or "
            "sf.fail() after it"
        )
    return tiers, lines, outcome


def _add(part: object, tiers: list[Tier], lines: list[EscalateIf]) -> Outcome | None:
    """Add one part to ``tiers`` or ``lines`` in order; return it when it is the closing outcome."""

    tier_due = len(lines) == len(tiers)
    if isinstance(part, EscalateIf):
        if tier_due:
            raise ValueError("sf.escalate_if(...) goes between two sf.Cascade tiers")
        lines.append(part)
        return None
    if not tier_due:
        raise ValueError(
            f"sf.Cascade part {len(tiers) + len(lines) + 1} can never run: write "
            f"sf.escalate_if(...) after tier {len(tiers)}"
        )
    if isinstance(part, Outcome):
        if not tiers:
            raise ValueError("a sf.Cascade starts with a tier")
        return part
    tiers.append(_checked_tier(part))
    return None


def _checked_tier(part: object) -> Tier:
    """A tier value: a route or a recipe; an outcome word or an open Fanout is refused."""

    if isinstance(part, str) and word_shaped(part):
        raise TypeError(  # one spelling for an outcome in the new API (2026-11-12)
            f"sf.Cascade takes sf.abstain() or sf.fail() as its last part, not the word {part!r}"
        )
    if isinstance(part, Fanout):
        raise TypeError(_TIER_SHAPE)  # CA-13: an open Fanout has no reducer step
    if not isinstance(part, str | Recipe):
        raise TypeError(_FORM)
    return part


def _tier(value: Tier, condition: Escalation) -> tuple[Fanout, Step | None, Step]:
    """A gated tier as its Fanout, its judge and its reducer step.

    A condition line keeps the tier as the author wrote it: its quorum decides when it fails. An
    ``sf.unanswered()`` line makes its members optional with quorum 0, so a failure escalates.
    """

    if isinstance(value, str | Model):
        if not isinstance(condition, Unanswered):
            raise TypeError(_TIER_SHAPE)
        value = Fanout([value]) >> Vote()  # CA-10: a first-success tier answers verbatim
    block = _single_block(value)
    fanout = block.fanout
    if isinstance(condition, Unanswered):
        fanout = _optional_fanout(fanout)
    return fanout, block.judge, block.terminal


def _optional_fanout(fanout: Fanout) -> Fanout:
    """The tier's Fanout with optional members and quorum 0 (CA-6, ans:Q24)."""

    if fanout.quorum != "all":
        raise ValueError(  # CA-17: the quorum would be dropped without a word
            "a sf.escalate_if(sf.unanswered()) tier decides on the members that answered; it "
            "takes quorum='all'"
        )
    return Fanout(
        [_optional(member) for member in fanout.members],
        signals=fanout.signals,
        quorum=0,
        name=_kept_name(fanout.name, _inferred_name(fanout.members)),
        prompt=fanout.prompt,
    )


def _single_block(value: object) -> _Block:
    """The one closed block of a tier chain that ends in a reducer step, else CA-13."""

    if not isinstance(value, Pipeline) or value._open or len(value._stages) != 1:
        raise TypeError(_TIER_SHAPE)
    block = value._stages[0]
    if not isinstance(block, _Block) or block.narrow or block.terminal._category != "reduce":
        raise TypeError(_TIER_SHAPE)
    if isinstance(block.terminal, Gate):
        raise TypeError(_TIER_SHAPE)
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
    raise TypeError("a cascade tier member is a model route, a sf.Model or a chain")


def _keep(condition: Escalation) -> GateCondition | AnsweredCondition:
    """The keep form of an escalate form (CA-4); ``sf.unanswered()`` keeps an answer (CA-10)."""

    if isinstance(condition, Unanswered):
        return answered()
    return _condition(condition.ref, _KEEP[condition.cmp], condition.threshold)


def _gated(
    fanout: Fanout,
    judge: Step | None,
    step: Step,
    condition: Escalation,
    number: int,
    rest: Tier | Outcome,
) -> Recipe:
    try:
        gate = Gate(when=_keep(condition), then=step, otherwise=rest)
    except ValueError as exc:
        # CA-15: the refusal names the escalate form the author wrote.
        raise ValueError(
            f"sf.Cascade tier {number}: sf.escalate_if({condition!r}): {exc}"
        ) from None
    try:
        chain = fanout >> judge >> gate if judge is not None else fanout >> gate
    except ValueError as exc:
        # CA-14: a block rule (an undeclared signal) names the tier the author wrote.
        raise ValueError(f"sf.Cascade tier {number}: {exc}") from None
    return chain


def _members(tier: object) -> tuple[Recipe, ...]:
    """The Fanout members of a tier that is one block; none for any other tier."""

    if isinstance(tier, Pipeline) and tier._stages and isinstance(tier._stages[0], _Block):
        return tier._stages[0].fanout.members
    return ()


def _warn_repeated_seeds(tiers: list[tuple[Recipe, ...]]) -> None:
    """CA-23: equal sample requests can be gateway cache hits with the same text."""

    seen: dict[tuple[str, object], int] = {}
    for number, members in enumerate(tiers, start=1):
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
                f"sf.Cascade tier {number} repeats seeds {', '.join(seeds)} of tier {earlier}; "
                "give seeds= for fresh samples",
                CascadeSeedWarning,
                skip_file_prefixes=(SDK_PACKAGE_ROOT,),
            )


__all__ = ["Cascade", "EscalateIf", "Unanswered", "escalate_if", "unanswered"]
