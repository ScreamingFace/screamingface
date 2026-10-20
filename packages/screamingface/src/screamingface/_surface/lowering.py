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

from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Any, cast

from screamingface._surface.chain import Pipeline as Chain
from screamingface._surface.chain import Step, _Block, refuse_step
from screamingface._surface.fanout import Fanout
from screamingface._surface.judge import Judge, JudgePick
from screamingface._surface.refs import (
    engine_op,
    field_extract,
    is_rule_name,
    with_normalizer,
)
from screamingface._surface.steps import (
    ArgMax,
    ArgMin,
    Concat,
    Filter,
    First,
    Mean,
    Median,
    Merge,
    Rank,
    Vote,
)
from screamingface._surface.synthesize import Synthesize
from screamingface.blocks import Extract, Reduce
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.fields import Merge as MergeNode
from screamingface.fields import Pick as PickNode
from screamingface.fusion import Fusion
from screamingface.judge import Judge as JudgeNode
from screamingface.model import Model
from screamingface.pipeline import Pipeline
from screamingface.recipe import Recipe, _inferred_name, _inferred_self_name, _kept_name
from screamingface.reducer import _DEFAULT_NORMALIZE, BENCHMARK_EXTRACT, Reducer
from screamingface.reducer import Mean as MeanNode
from screamingface.reducer import Median as MedianNode
from screamingface.reducer import Vote as VoteNode
from screamingface.selection import Concat as ConcatNode
from screamingface.selection import Filter as FilterNode
from screamingface.selection import Rank as RankNode

_FA2 = "sf.Fanout signals= needs a reducer: sf.Synthesize reads no signal"
# The judge a step is checked with when it is built: the block's own sf.Judge comes at block close.
_PROBE_JUDGE = JudgeNode("probe/judge", returns="scores", rubric="probe")

type _Active = tuple[int, ...]


def lower(value: Recipe) -> Recipe:
    """The internal value of ``value``: a chain lowers stage by stage (LO-4); every other value
    is returned as it is, unless it holds a chain (LO-0).

    A step, a ``Fanout`` or a chain that ends inside a block is refused (CH-8, CH-11).
    """

    return _lower(value, ())


def block_node(block: _Block) -> Recipe:
    """The lowered value of one closed block (lowering §2.2), built at block close (CH-9)."""

    fanout = block.fanout
    judge = None if block.judge is None else cast("Judge", block.judge)._node
    if not block.narrow:
        return _fusion_of(fanout, _terminal(fanout, block.terminal, judge))
    # INVARIANT (CH-12, until unit 5): one narrow step, and a Synthesize after it.
    (narrow,) = block.narrow
    writer = _writer(cast("Synthesize", block.terminal))
    return Pipeline([_fusion_of(fanout, step_node(narrow, judge)), writer])


def step_node(step: Step, judge: JudgeNode | None) -> Reducer:
    """Today's reducer for a reduce or narrow step. ``judge`` is the block's scores judge of
    today; only a step that reads ``score:judge`` gets it."""

    return _NODES[type(step)](step, judge if step._reads_judge() else None)


def check_step(step: Step) -> None:
    """Build today's reducer once, so a bad option raises when the step is built.

    WHY the probe judge: a step that reads ``score:judge`` needs the block's ``sf.Judge``, which
    comes at block close (CH-10); with the probe, today's constructor checks every other option
    now.
    """

    step_node(step, _PROBE_JUDGE)


def with_prompt(model: Model, prompt: str) -> Model:
    """``model`` with ``prompt``, every other option kept (O6, SY-1: it has no prompt yet)."""

    return Model(
        model.model,
        name=model._sample_id,
        prompt=prompt,
        params=model.params,
        optional=model.optional,
    )


def _fusion_of(fanout: Fanout, synthesizer: Recipe | Reducer) -> Fusion:
    return Fusion(
        _members(fanout),
        name=fanout.name,
        signals=fanout.signals,
        synthesizer=synthesizer,
        quorum=fanout.quorum,
    )


def _members(fanout: Fanout) -> tuple[Recipe, ...]:
    prompt = fanout.prompt
    if prompt is None:
        return tuple(lower(member) for member in fanout.members)
    # Fanout proved each member is a Model with no prompt (FA-1).
    return tuple(with_prompt(cast("Model", member), prompt) for member in fanout.members)


def _terminal(fanout: Fanout, terminal: Step, judge: JudgeNode | None) -> Recipe | Reducer:
    if isinstance(terminal, Synthesize):
        # FA-2 (erratum E4): with no narrow step, nothing reads the signals.
        if fanout.signals is not None:
            raise ValueError(_FA2)
        return _writer(terminal)
    return step_node(terminal, judge)


def _writer(step: Synthesize) -> Recipe:
    if step.prompt is None:
        return lower(step.model)
    # Synthesize proved the model is a Model with no prompt (SY-1).
    return with_prompt(cast("Model", step.model), step.prompt)


def _vote_node(step: Vote, judge: JudgeNode | None) -> Reducer:
    """A rule name lowers to today's named Vote, a field or an extract to the block form.

    WHY the block form for ``"field:<path>"`` and ``sf.Extract``: the named reducers store an
    operator name only (``S/reducer.py``), so ``sf.Reduce`` is the one path that compiles an
    extractor with arguments today (O1).
    """

    if is_rule_name(step.over):
        over = cast("str", step.over)
        # WHY the default marker for "benchmark": today's Vote takes the benchmark's normalizer only
        # when no normalize= was passed (GP-E2); the step holds None for it.
        normalize = _DEFAULT_NORMALIZE if over == BENCHMARK_EXTRACT else step.normalize
        return VoteNode(
            extract=engine_op(over), normalize=normalize, weights=step.weights, judge=judge
        )
    extract = _vote_extract(step)
    if step.weights is None:
        return Reduce("plurality", extract=extract)
    options: dict[str, Any] = {} if judge is None else {"judge": judge}
    return Reduce("weighted", extract=extract, weights=step.weights, **options)


def _vote_extract(step: Vote) -> Extract:
    """The extract of a field or ``sf.Extract`` vote, with the vote's normalizer in it."""

    if isinstance(step.over, str):
        return field_extract(step.over, step.normalize)
    return with_normalizer(step.over, step.normalize)


def _statistic_node(step: Median | Mean, judge: JudgeNode | None) -> Reducer:
    if is_rule_name(step.over):
        named = MedianNode if isinstance(step, Median) else MeanNode
        over = cast("str", step.over)
        return named(extract=engine_op(over), select=step.select, weights=step.weights)
    # The numeric normalizer is the block's own: Reduce sets it on the extract.
    extract = field_extract(step.over, None) if isinstance(step.over, str) else step.over
    options: dict[str, Any] = {} if step.weights is None else {"weights": step.weights}
    op = "median" if isinstance(step, Median) else "mean"
    return Reduce(op, select=step.select, extract=extract, **options)


def _rank_node(step: Rank, judge: JudgeNode | None) -> Reducer:
    if judge is not None:
        # WHY the judge keeps order="max": Rank's own order= sets the direction of top_k (D2).
        return RankNode(step.k, by=judge, order=step.order)
    return RankNode(step.k, by_signal=step.by, order=step.order)


def _filter_node(step: Filter, judge: JudgeNode | None) -> Reducer:
    return FilterNode(where=step.where, extract=step.over, judge=judge)


def _concat_node(step: Concat, judge: JudgeNode | None) -> Reducer:
    return ConcatNode(step.separator, label=step.label)


def _pick_node(step: ArgMax, judge: JudgeNode | None) -> Reducer:
    """ArgMax/ArgMin by a signal is today's Pick by signal; by ``score:judge`` it is today's scores
    judge as the synthesizer, with ArgMin's ``order="min"`` (select ``best_holder{order:min}``)."""

    if judge is None:
        return PickNode(by_signal=step.by, order=step._order, output=step.output)
    if step._order == "max":
        return judge
    return JudgeNode(
        judge.model, returns="scores", rubric=judge.rubric, params=judge.params, order="min"
    )


def _first_node(step: First, judge: JudgeNode | None) -> Reducer:
    where = step.where
    return PickNode(
        where.path,
        equals=cast("str | int | float | bool", where.value),
        normalize=where.normalize,
        output=step.output,
    )


def _merge_node(step: Merge, judge: JudgeNode | None) -> Reducer:
    return MergeNode(step.fields)


def _judge_pick_node(step: JudgePick, judge: JudgeNode | None) -> Reducer:
    return step._node


# Each reduce and narrow step, and how it lowers to today's reducer (lowering §2.2).
_NODES: Mapping[type, Callable[[Any, JudgeNode | None], Reducer]] = MappingProxyType(
    {
        Vote: _vote_node,
        Median: _statistic_node,
        Mean: _statistic_node,
        Rank: _rank_node,
        Filter: _filter_node,
        Concat: _concat_node,
        ArgMax: _pick_node,
        ArgMin: _pick_node,
        First: _first_node,
        Merge: _merge_node,
        JudgePick: _judge_pick_node,
    }
)


# AIDEV-NOTE: the walk over today's containers mirrors S/_evaluation/fusion_recipe.py, with its
# name rule (_kept_name). Unit 7 deletes fusion_recipe.py, so this becomes the only walker.
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
    if isinstance(node, Pipeline):
        return Pipeline(
            node.stages, optional=True
        )  # a block's Pipeline([Fusion, writer]) is unnamed
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
        name=_kept_name(fusion.name, _inferred_name(fusion.members)),
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
    name = _kept_name(loop.name, _inferred_name(loop.members))
    return CorrectiveLoop(members, judge=judge, max_rounds=loop.max_rounds, name=name)


def _solo(solo: SelfCorrective, active: _Active) -> Recipe:
    member = _lower(solo.member, active)
    if member is solo.member:
        return solo
    name = _kept_name(solo.name, _inferred_self_name(solo.member))
    return SelfCorrective(member, max_rounds=solo.max_rounds, name=name)


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


__all__ = ["block_node", "check_step", "lower", "step_node"]
