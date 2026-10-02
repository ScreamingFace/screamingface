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

from screamingface.blocks import CONTEXT_MISUSE, Reduce
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.fusion import Fusion
from screamingface.pipeline import Pipeline
from screamingface.recipe import Recipe, _recipe_kind
from screamingface.reducer import Reducer


def rewrite_fusion_recipe(recipe: Recipe) -> Recipe:
    """sf.Fusion is the named recipe Fan-out -> Reduce.compute(context) -> Model (FR delta, Q16).

    Pipeline([Fusion(m, Reduce("context")), S, *rest]) -> Pipeline([Fusion(m, S), *rest]), or
    Fusion(m, S) when rest is empty and the Pipeline is unnamed. Pure, idempotent, runs before
    compile."""

    return _REWRITES[_recipe_kind(recipe)](recipe)


def _is_context_fusion(recipe: Recipe) -> bool:
    synthesizer = recipe.synthesizer if isinstance(recipe, Fusion) else None
    return isinstance(synthesizer, Reduce) and synthesizer.op == "context"


def _same(old: Sequence[object], new: Sequence[object]) -> bool:
    return len(old) == len(new) and all(a is b for a, b in zip(old, new, strict=True))


def _unchanged(recipe: Recipe) -> Recipe:
    return recipe


def _fusion(fusion: Fusion) -> Recipe:
    """A Fusion met outside a Pipeline pair: a context Fusion here is misuse."""

    if _is_context_fusion(fusion):
        raise ValueError(CONTEXT_MISUSE)
    members = tuple(rewrite_fusion_recipe(member) for member in fusion.members)
    synthesizer = fusion.synthesizer
    if not isinstance(synthesizer, Reducer):
        synthesizer = rewrite_fusion_recipe(synthesizer)
    if _same(fusion.members, members) and synthesizer is fusion.synthesizer:
        return fusion
    return Fusion(members, name=_fusion_name(fusion), synthesizer=synthesizer)


def _fusion_name(fusion: Fusion) -> str | None:
    inferred = "+".join(member.name for member in fusion.members)
    return None if fusion.name == inferred else fusion.name


def _lowered_pair(stages: Sequence[Recipe], index: int) -> Fusion:
    """The Fusion that the context Fusion at ``index`` and the stage after it make together."""

    context = stages[index]
    assert isinstance(context, Fusion)
    follower = stages[index + 1] if index + 1 < len(stages) else None
    if follower is None or _is_context_fusion(follower):
        raise ValueError(CONTEXT_MISUSE)
    members = tuple(rewrite_fusion_recipe(member) for member in context.members)
    return Fusion(members, name=_fusion_name(context), synthesizer=rewrite_fusion_recipe(follower))


def _pipeline(pipeline: Pipeline) -> Recipe:
    """Scan the stages left to right; a context Fusion and the stage after it become one Fusion."""

    stages: list[Recipe] = []
    lowered = False
    index = 0
    while index < len(pipeline.stages):
        stage = pipeline.stages[index]
        if _is_context_fusion(stage):
            stages.append(_lowered_pair(pipeline.stages, index))
            lowered = True
            index += 2
        else:
            stages.append(rewrite_fusion_recipe(stage))
            index += 1
    if not lowered and _same(pipeline.stages, stages):
        return pipeline
    if lowered and len(stages) == 1 and not pipeline._is_named:
        return stages[0]
    return Pipeline(stages, name=pipeline.name if pipeline._is_named else None)


def _loop(loop: CorrectiveLoop) -> Recipe:
    members = tuple(rewrite_fusion_recipe(member) for member in loop.members)
    judge = rewrite_fusion_recipe(loop.judge)
    if _same(loop.members, members) and judge is loop.judge:
        return loop
    inferred = "+".join(member.name for member in loop.members)
    return CorrectiveLoop(
        members,
        name=None if loop.name == inferred else loop.name,
        judge=judge,
        max_rounds=loop.max_rounds,
    )


def _self_corrective(solo: SelfCorrective) -> Recipe:
    member = rewrite_fusion_recipe(solo.member)
    if member is solo.member:
        return solo
    return SelfCorrective(
        member,
        name=None if solo.name == solo.member.name else solo.name,
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
