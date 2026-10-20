"""The Fusion recipe rewrite: sf.Fusion is the recipe Fan-out -> Reduce.compute(context) -> Model.

FEATURE (FR delta, ans:Q6/Q16): the block form ``sf.Pipeline([sf.Fusion(members,
synthesizer=sf.Reduce("context")), S, ...])`` is the Fusion ``sf.Fusion(members, synthesizer=S)``.
The rewrite is pure and runs before compile, so the url4 of the block form is byte for byte the
url4 of the Fusion form. A recipe with no ``context`` block is returned as the same object, so an
existing Fusion cannot change by one byte.
INVARIANT: a rebuilt value goes through the public constructor of its class, with the name rule:
a name equal to the one inferred from the original children is inferred again from the rewritten
children, and any other name is kept (a Pipeline uses ``_is_named``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from types import MappingProxyType

from screamingface.blocks import CONTEXT_MISUSE, ReduceNode
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.fusion import FusionNode
from screamingface.pipeline import Pipeline
from screamingface.recipe import (
    Recipe,
    _inferred_name,
    _inferred_self_name,
    _kept_name,
    _recipe_kind,
)
from screamingface.reducer import Reducer


def rewrite_fusion_recipe(recipe: Recipe) -> Recipe:
    """sf.Fusion is the named recipe Fan-out -> Reduce.compute(context) -> Model (FR delta, Q16).

    Pipeline([Fusion(m, Reduce("context")), S, *rest]) -> Pipeline([Fusion(m, S), *rest]), or
    Fusion(m, S) when rest is empty and the Pipeline is unnamed. Pure, idempotent, runs before
    compile."""

    return _rewrite(recipe, ())


def _rewrite(recipe: Recipe, active: tuple[int, ...]) -> Recipe:
    # WHY the active ids: a cyclic value (only built by hand) must reach the compiler, which names
    # the cycle; the rewrite leaves a value it is already inside as it is.
    if id(recipe) in active:
        return recipe
    return _REWRITES[_recipe_kind(recipe)](recipe, (*active, id(recipe)))


def _is_context_fusion(recipe: Recipe) -> bool:
    synthesizer = recipe.synthesizer if isinstance(recipe, FusionNode) else None
    return isinstance(synthesizer, ReduceNode) and synthesizer.op == "context"


def _same(old: Sequence[object], new: Sequence[object]) -> bool:
    return len(old) == len(new) and all(a is b for a, b in zip(old, new, strict=True))


def _unchanged(recipe: Recipe, active: tuple[int, ...]) -> Recipe:
    return recipe


def _fusion(fusion: FusionNode, active: tuple[int, ...]) -> Recipe:
    """A Fusion met outside a Pipeline pair: a context Fusion here is misuse."""

    if _is_context_fusion(fusion):
        raise ValueError(CONTEXT_MISUSE)
    members = tuple(_rewrite(member, active) for member in fusion.members)
    synthesizer = fusion.synthesizer
    if not isinstance(synthesizer, Reducer):
        synthesizer = _rewrite(synthesizer, active)
    if _same(fusion.members, members) and synthesizer is fusion.synthesizer:
        return fusion
    return FusionNode(
        members,
        name=_fusion_name(fusion),
        signals=fusion.signals,
        synthesizer=synthesizer,
        quorum=fusion.quorum,
        optional=fusion.optional,
    )


def _fusion_name(fusion: FusionNode) -> str | None:
    return _kept_name(fusion.name, _inferred_name(fusion.members))


def _lowered_pair(stages: Sequence[Recipe], index: int, active: tuple[int, ...]) -> FusionNode:
    """The Fusion that the context Fusion at ``index`` and the stage after it make together."""

    context = stages[index]
    assert isinstance(context, FusionNode)
    follower = stages[index + 1] if index + 1 < len(stages) else None
    if follower is None or _is_context_fusion(follower):
        raise ValueError(CONTEXT_MISUSE)
    members = tuple(_rewrite(member, active) for member in context.members)
    # WHY the quorum rides along: the block form must compile to the named form's bytes. The
    # context Fusion is a Pipeline stage, never optional; the Pipeline's own flag is kept below.
    return FusionNode(
        members,
        name=_fusion_name(context),
        synthesizer=_rewrite(follower, active),
        quorum=context.quorum,
    )


def _pipeline(pipeline: Pipeline, active: tuple[int, ...]) -> Recipe:
    """Scan the stages left to right; a context Fusion and the stage after it become one Fusion."""

    stages: list[Recipe] = []
    lowered = False
    index = 0
    while index < len(pipeline.stages):
        stage = pipeline.stages[index]
        if _is_context_fusion(stage):
            stages.append(_lowered_pair(pipeline.stages, index, active))
            lowered = True
            index += 2
        else:
            stages.append(_rewrite(stage, active))
            index += 1
    if not lowered and _same(pipeline.stages, stages):
        return pipeline
    if lowered and len(stages) == 1 and not pipeline._is_named:
        return _optional_fusion(stages[0], pipeline.optional)
    return Pipeline(
        stages, name=pipeline.name if pipeline._is_named else None, optional=pipeline.optional
    )


def _optional_fusion(stage: Recipe, optional: bool) -> Recipe:
    """The lowered Fusion that replaces a one-pair Pipeline keeps that Pipeline's optional flag."""

    if not optional:
        return stage
    assert isinstance(stage, FusionNode)  # a lowered pair is always a Fusion
    return FusionNode(
        stage.members,
        name=_fusion_name(stage),
        signals=stage.signals,
        synthesizer=stage.synthesizer,
        quorum=stage.quorum,
        optional=True,
    )


def _loop(loop: CorrectiveLoop, active: tuple[int, ...]) -> Recipe:
    members = tuple(_rewrite(member, active) for member in loop.members)
    judge = _rewrite(loop.judge, active)
    if _same(loop.members, members) and judge is loop.judge:
        return loop
    return CorrectiveLoop(
        members,
        name=_kept_name(loop.name, _inferred_name(loop.members)),
        judge=judge,
        max_rounds=loop.max_rounds,
    )


def _self_corrective(solo: SelfCorrective, active: tuple[int, ...]) -> Recipe:
    member = _rewrite(solo.member, active)
    if member is solo.member:
        return solo
    return SelfCorrective(
        member,
        name=_kept_name(solo.name, _inferred_self_name(solo.member)),
        max_rounds=solo.max_rounds,
    )


_REWRITES: MappingProxyType[str, Callable[..., Recipe]] = MappingProxyType(
    {
        "model": _unchanged,
        "fusion": _fusion,
        "pipeline": _pipeline,
        "corrective_loop": _loop,
        "self_corrective": _self_corrective,
    }
)

__all__ = ["rewrite_fusion_recipe"]
