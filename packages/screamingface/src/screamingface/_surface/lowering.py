"""The lowering: a chain of the new surface → the internal values that today's compiler reads.

FEATURE (E4b surface, lowering §1–§2): ``lower()`` turns a chain into today's ``Fusion``,
``Pipeline`` and reducer values, so a recipe in the new form compiles to the url4 of today. It
runs at block close (``block_node``) and once at the first compile entry
(``S/_evaluation/candidate.py``).
INVARIANT (LO-1): pure and deterministic; it makes no call. Idempotent: a lowered value lowers to
itself.
INVARIANT (LO-0): until the swap, ``lower()`` is the identity on every value that is not a
``_surface`` value and holds none, so no existing recipe changes by one byte.
AIDEV-NOTE: the targets keep today's class names (``Fusion``, ``Vote``, ``Reduce``, ...) until the
swap (unit 7) renames them to their ``Node`` names (O7).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

from screamingface._surface.chain import Pipeline as Chain
from screamingface._surface.chain import Step, _Block, refuse_step
from screamingface._surface.fanout import Fanout
from screamingface._surface.refs import (
    engine_op,
    field_extract,
    is_rule_name,
    with_normalizer,
)
from screamingface._surface.steps import Mean, Median, Vote, reads_judge
from screamingface._surface.synthesize import Synthesize
from screamingface.blocks import Extract, Reduce
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.fusion import Fusion
from screamingface.model import Model
from screamingface.pipeline import Pipeline
from screamingface.recipe import Recipe
from screamingface.reducer import _DEFAULT_NORMALIZE, Reducer
from screamingface.reducer import Mean as MeanNode
from screamingface.reducer import Median as MedianNode
from screamingface.reducer import Vote as VoteNode

_FA2 = "sf.Fanout signals= needs a reducer: sf.Synthesize reads no signal"
_NO_JUDGE = "score:judge needs sf.Judge(...) after sf.Fanout"  # CH-10 (unit 3 adds sf.Judge)

type _Active = tuple[int, ...]


def lower(value: Recipe) -> Recipe:
    """The internal value of ``value``: a chain lowers stage by stage (LO-4); every other value
    is returned as it is, unless it holds a chain (LO-0).

    A step, a ``Fanout`` or a chain that ends inside a block is refused (CH-8, CH-11).
    """

    return _lower(value, ())


def block_node(block: _Block) -> Recipe:
    """The lowered value of one closed block (lowering §2.2), built at block close (CH-9)."""

    # INVARIANT: unit 2 has no score step and no narrow step; unit 3 adds them (lowering §2.2).
    assert block.judge is None and not block.narrow
    fanout = block.fanout
    return Fusion(
        _members(fanout),
        name=fanout.name,
        signals=fanout.signals,
        synthesizer=_terminal(fanout, block.terminal),
        quorum=fanout.quorum,
    )


def reducer_node(step: Vote | Median | Mean) -> Reducer:
    """Today's reducer for a reduce step: the named reducer for a rule name, else the block form.

    WHY the block form for ``"field:<path>"`` and ``sf.Extract``: the named reducers store an
    operator name only (``S/reducer.py``), so ``sf.Reduce`` is the one path that compiles an
    extractor with arguments today (O1).
    """

    if isinstance(step, Vote):
        return _vote_node(step)
    return _statistic_node(step)


def with_prompt(model: Model, prompt: str) -> Model:
    """``model`` with ``prompt``, every other option kept (O6, SY-1: it has no prompt yet)."""

    return Model(
        model.model,
        name=model._sample_id,
        prompt=prompt,
        params=model.params,
        optional=model.optional,
    )


# ---------------------------------------------------------------- blocks


def _members(fanout: Fanout) -> tuple[Recipe, ...]:
    prompt = fanout.prompt
    if prompt is None:
        return tuple(lower(member) for member in fanout.members)
    # Fanout proved each member is a Model with no prompt (FA-1).
    return tuple(with_prompt(cast("Model", member), prompt) for member in fanout.members)


def _terminal(fanout: Fanout, terminal: Step) -> Recipe | Reducer:
    if isinstance(terminal, Synthesize):
        if fanout.signals is not None:
            raise ValueError(_FA2)
        return _writer(terminal)
    step = cast("Vote | Median | Mean", terminal)
    if reads_judge(step.weights):
        raise ValueError(_NO_JUDGE)
    return reducer_node(step)


def _writer(step: Synthesize) -> Recipe:
    if step.prompt is None:
        return lower(step.model)
    # Synthesize proved the model is a Model with no prompt (SY-1).
    return with_prompt(cast("Model", step.model), step.prompt)


def _vote_node(step: Vote) -> Reducer:
    if is_rule_name(step.over):
        over = cast("str", step.over)
        return VoteNode(extract=engine_op(over), normalize=step.normalize, weights=step.weights)
    extract = _vote_extract(step)
    if step.weights is None:
        return Reduce("plurality", extract=extract)
    return Reduce("weighted", extract=extract, weights=step.weights)


def _vote_extract(step: Vote) -> Extract:
    """The extract of a field or ``sf.Extract`` vote: the step's normalizer goes in it, unless the
    caller passed none and the ``sf.Extract`` has its own (EX-2)."""

    if isinstance(step.over, str):
        return field_extract(step.over, step.normalize)
    if step.normalize is _DEFAULT_NORMALIZE:
        return step.over
    return with_normalizer(step.over, step.normalize)


def _statistic_node(step: Median | Mean) -> Reducer:
    if is_rule_name(step.over):
        named = MedianNode if isinstance(step, Median) else MeanNode
        over = cast("str", step.over)
        return named(extract=engine_op(over), select=step.select, weights=step.weights)
    # The numeric normalizer is the block's own: Reduce sets it on the extract.
    extract = field_extract(step.over, None) if isinstance(step.over, str) else step.over
    options: dict[str, Any] = {} if step.weights is None else {"weights": step.weights}
    op = "median" if isinstance(step, Median) else "mean"
    return Reduce(op, select=step.select, extract=extract, **options)


# ---------------------------------------------------------------- chains and today's containers


def _lower(value: Recipe, active: _Active) -> Recipe:
    # WHY the active ids: a cyclic value (only built by hand) must reach the compiler, which names
    # the cycle; the lowering leaves a value it is already inside as it is.
    refuse_step(value)
    if id(value) in active:
        return value
    for kind, lowering in _LOWERINGS:
        if isinstance(value, kind):
            return lowering(value, (*active, id(value)))
    return value


def _chain(chain: Chain, active: _Active) -> Recipe:
    stages = tuple(
        stage.node if isinstance(stage, _Block) else _lower(stage, active)
        for stage in chain._stages
    )
    if not chain._is_named and len(stages) == 1 and isinstance(chain._stages[0], _Block):
        # LO-5: an unnamed chain of one closed block is that block's node; its flag moves there.
        return _optional_node(stages[0]) if chain.optional else stages[0]
    # LO-6: a named chain keeps its grouping. Today's Pipeline flattens the unnamed ones (LO-4).
    return Pipeline(stages, name=chain.name if chain._is_named else None, optional=chain.optional)


def _optional_node(node: Recipe) -> Recipe:
    # INVARIANT: in unit 2 a block node is one Fusion; unit 3 adds Pipeline([Fusion, writer]).
    assert isinstance(node, Fusion)
    return _rebuilt_fusion(node, node.members, node.synthesizer, optional=True)


def _fusion(fusion: Fusion, active: _Active) -> Recipe:
    members = _lowered(fusion.members, active)
    synthesizer = fusion.synthesizer
    if not isinstance(synthesizer, Reducer):
        synthesizer = _lower(synthesizer, active)
    if members is fusion.members and synthesizer is fusion.synthesizer:
        return fusion
    return _rebuilt_fusion(fusion, members, synthesizer, optional=fusion.optional)


def _rebuilt_fusion(
    fusion: Fusion,
    members: Sequence[Recipe],
    synthesizer: Recipe | Reducer,
    *,
    optional: bool,
) -> Fusion:
    return Fusion(
        members,
        name=fusion.name,
        signals=fusion.signals,
        synthesizer=synthesizer,
        quorum=fusion.quorum,
        optional=optional,
    )


def _pipeline(pipeline: Pipeline, active: _Active) -> Recipe:
    stages = _lowered(pipeline.stages, active)
    if stages is pipeline.stages:
        return pipeline
    name = pipeline.name if pipeline._is_named else None
    return Pipeline(stages, name=name, optional=pipeline.optional)


def _loop(loop: CorrectiveLoop, active: _Active) -> Recipe:
    members = _lowered(loop.members, active)
    judge = _lower(loop.judge, active)
    if members is loop.members and judge is loop.judge:
        return loop
    return CorrectiveLoop(members, judge=judge, max_rounds=loop.max_rounds, name=loop.name)


def _solo(solo: SelfCorrective, active: _Active) -> Recipe:
    member = _lower(solo.member, active)
    if member is solo.member:
        return solo
    return SelfCorrective(member, max_rounds=solo.max_rounds, name=solo.name)


def _lowered(values: tuple[Recipe, ...], active: _Active) -> tuple[Recipe, ...]:
    """``values`` lowered; the same tuple when no value changed, so LO-0 keeps the object."""

    lowered = tuple(_lower(value, active) for value in values)
    unchanged = all(new is old for new, old in zip(lowered, values, strict=True))
    return values if unchanged else lowered


# The recipe kinds that can hold a chain, and how each one lowers. A Model holds none.
_LOWERINGS: tuple[tuple[type, Callable[[Any, _Active], Recipe]], ...] = (
    (Chain, _chain),
    (Fusion, _fusion),
    (Pipeline, _pipeline),
    (CorrectiveLoop, _loop),
    (SelfCorrective, _solo),
)


__all__ = ["block_node", "lower", "reducer_node"]
