"""The url4 rebuild as a chain of the new surface (E4b surface unit 6, rebuild-display §1).

FEATURE: ``rebuild(url4)`` gives the chain value a url4 describes and the code that builds it,
with every step named through the module alias ``sf`` (``candidate = sf.Fanout(...) >> ...``).
WHY one decode path: the url4 decode and today's rebuild (``S/url4.py``) give today's values, and
``surface_value`` converts them with the inverse of the lowering table (lowering §2.2). So the url4
checks of today run once, and only the conversion is new.
INVARIANT (RB-1): the rebuilt value compiles to the url4 it came from, byte for byte, or the
rebuild is refused with the "cannot rebuild" message.
AIDEV-NOTE: until the swap (unit 7) only new tests call this; the swap makes ``Url4.to_python()``
use it, with the alias ``sf`` as the real ``screamingface``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from screamingface._evaluation.policy import DEFAULT_ANSWER_PROMPT, DEFAULT_SYNTHESIS_PROMPT
from screamingface._surface.chain import Pipeline as Chain
from screamingface._surface.chain import Step
from screamingface._surface.fanout import Fanout
from screamingface._surface.gate import Fallback, Gate
from screamingface._surface.judge import Judge, JudgePick
from screamingface._surface.refs import (
    GateRef,
    _condition,
    agreement,
    field,
    signal,
    with_normalizer,
)
from screamingface._surface.render import render
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
from screamingface.blocks import _REVERSE_RULES, Extract, Reduce
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.fields import Merge as MergeNode
from screamingface.fields import Pick as PickNode
from screamingface.fusion import Fusion
from screamingface.judge import Judge as JudgeNode
from screamingface.model import Model
from screamingface.pipeline import Pipeline
from screamingface.recipe import Recipe, _inferred_name, _inferred_self_name, _kept_name
from screamingface.reducer import BENCHMARK_EXTRACT, Reducer, _cannot_rebuild, _narrow_steps
from screamingface.reducer import Mean as MeanNode
from screamingface.reducer import Median as MedianNode
from screamingface.reducer import Vote as VoteNode
from screamingface.selection import Concat as ConcatNode
from screamingface.selection import Filter as FilterNode
from screamingface.selection import Rank as RankNode

_CANNOT_REBUILD = "URL4 Candidate has a recipe this SDK version cannot rebuild"
_FIELD_PREFIX = "field:"


@dataclass(frozen=True, slots=True)
class Rebuilt:
    """A rebuilt url4: the chain value and the code that builds it through the alias ``sf``."""

    value: Recipe
    python: str


def rebuild(url4: str) -> Rebuilt:
    """The chain a url4 describes, and its code; ValueError when the new surface cannot say it."""

    # WHY lazy: S/url4.py imports the compiler, which imports this package's lowering
    from screamingface.url4 import (
        _decode_candidate,
        _recipe_from_topology,
        _replay_check_surface,
        _require_recompiles,
    )

    decoded = _decode_candidate(url4)
    value = surface_value(_recipe_from_topology(decoded.topology, decoded.calls))
    try:
        _require_recompiles(
            decoded.candidate,
            value,
            decoded.calls,
            check_surface=_replay_check_surface(decoded.topology),
        )
    except ValueError as exc:
        raise ValueError(_CANNOT_REBUILD) from exc
    return Rebuilt(value, f"candidate = {render(value, 'sf.')}")


def surface_value(value: Recipe, *, synthesis: bool | None = False) -> Recipe:
    """Today's ``value`` in the new surface: a Fusion becomes a block, a Pipeline a chain.

    ``synthesis`` is the role the compiler gives the value (``S/_evaluation/candidate.py``): True
    in a Fusion synthesizer slot (and the first stage of a Pipeline there), False as a member or a
    later stage, None inside a corrective loop, whose roles this rebuild does not read. A Model
    whose prompt is the default of its role rebuilds with no prompt, as ``to_python`` writes it.
    """

    for kind, convert in _RECIPES:
        if isinstance(value, kind):
            return convert(value, synthesis)
    raise ValueError(_CANNOT_REBUILD)  # pragma: no cover - the url4 topology has no other kind


def _fusion(fusion: Fusion, _synthesis: bool | None) -> Chain:
    return Chain(_block(fusion), optional=fusion.optional)


def _loop(loop: CorrectiveLoop, _synthesis: bool | None) -> CorrectiveLoop:
    return CorrectiveLoop(
        [surface_value(member, synthesis=None) for member in loop.members],
        judge=surface_value(loop.judge, synthesis=None),
        max_rounds=loop.max_rounds,
        name=_kept_name(loop.name, _inferred_name(loop.members)),
    )


def _solo(solo: SelfCorrective, _synthesis: bool | None) -> SelfCorrective:
    return SelfCorrective(
        surface_value(solo.member, synthesis=None),
        max_rounds=solo.max_rounds,
        name=_kept_name(solo.name, _inferred_self_name(solo.member)),
    )


def _model(model: Model, synthesis: bool | None) -> Model:
    if synthesis is None:
        return model
    default = DEFAULT_SYNTHESIS_PROMPT if synthesis else DEFAULT_ANSWER_PROMPT
    if model.prompt != default:
        return model
    params = dict(model.params) or None
    return Model(model.model, name=model._sample_id, params=params, optional=model.optional)


def _chain(pipeline: Pipeline, synthesis: bool | None) -> Chain:
    """Today's stages as one chain: a selection Fusion and the stage after it are one block,
    ``Fanout >> <narrow> >> Synthesize(next stage)`` (rebuild-display §1)."""

    items: list[Recipe | Step] = []
    stages = list(enumerate(pipeline.stages))
    while stages:
        index, stage = stages.pop(0)
        role = None if synthesis is None else synthesis and index == 0
        if not isinstance(stage, Fusion) or stage.optional:
            items.append(surface_value(stage, synthesis=role))
        elif _is_selection(stage) and stages:
            index, writer = stages.pop(0)
            role = None if synthesis is None else synthesis and index == 0
            items.extend(_block(stage, writer=writer, writer_role=role))
        else:
            items.extend(_block(stage))
    name = pipeline.name if pipeline._is_named else None
    return Chain(items, name=name, optional=pipeline.optional)


# The recipe kinds of today and their new-surface form.
_RECIPES: tuple[tuple[type, Callable[[Any, bool | None], Recipe]], ...] = (
    (Model, _model),
    (Fusion, _fusion),
    (Pipeline, _chain),
    (CorrectiveLoop, _loop),
    (SelfCorrective, _solo),
)


def _is_selection(fusion: Fusion) -> bool:
    synthesizer = fusion.synthesizer
    return isinstance(synthesizer, Reducer) and synthesizer._combine_plan().kind == "selection"


def _block(
    fusion: Fusion, writer: Recipe | None = None, writer_role: bool | None = False
) -> list[Recipe | Step]:
    """One Fusion as the steps of one block: the Fanout, then the steps of its synthesizer; a
    ``writer`` (the Pipeline stage after a selection) closes it with ``Synthesize``."""

    fanout = Fanout(
        [surface_value(member) for member in fusion.members],
        signals=fusion.signals,
        quorum=fusion.quorum,
        name=_kept_name(fusion.name, _inferred_name(fusion.members)),
    )
    synthesizer = fusion.synthesizer
    if not isinstance(synthesizer, Reducer):
        return [fanout, _synthesize(synthesizer, synthesis=True)]
    steps: list[Recipe | Step] = [fanout, *_reducer_steps(synthesizer)]
    if writer is not None:
        steps.append(_synthesize(writer, synthesis=writer_role))
    return steps


def _synthesize(writer: Recipe, *, synthesis: bool | None) -> Synthesize:
    """The writer step: a Model with a prompt and no other option shows its prompt on the step."""

    writer = surface_value(writer, synthesis=synthesis)
    if (
        isinstance(writer, Model)
        and writer.prompt is not None
        and repr(writer) == f"Model({writer.model!r}, prompt={writer.prompt!r})"
    ):
        return Synthesize(writer.model, prompt=writer.prompt)
    return Synthesize(writer)


# ---------------------------------------------------------------- a reducer as steps


def _reducer_steps(reducer: Reducer) -> list[Step]:
    """The judge (when a step reads one), the narrow steps in order, then the main step."""

    judges: list[JudgeNode] = []
    narrow = [_converted(step, judges) for step in _narrow_steps(reducer)]
    main = _converted(reducer, judges)
    return [*_judge_step(judges, reducer.name), *narrow, main]


def _judge_step(judges: list[JudgeNode], name: str) -> list[Step]:
    """One ``Judge`` for every step that reads ``score:judge``; two different judges: refuse."""

    steps: list[Step] = [
        Judge(judge.model, rubric=judge.rubric, params=dict(judge.params) or None)
        for judge in judges
    ]
    if any(step != steps[0] for step in steps[1:]):
        raise _cannot_rebuild(name)
    return steps[:1]


def _converted(reducer: Reducer, judges: list[JudgeNode]) -> Step:
    """One reducer of today as its step; a value with no new-surface form is "cannot rebuild"."""

    convert = _CONVERSIONS.get(type(reducer))
    if convert is None:
        raise _cannot_rebuild(reducer.name)
    try:
        return convert(reducer, judges)
    except (TypeError, ValueError) as exc:
        raise _cannot_rebuild(reducer.name) from exc


def _rule(op: str) -> str:
    """An Engine extract op as its rule name, with its pin (erratum E2: ``json_object@1`` is
    ``json@1``); ``benchmark`` has no op."""

    if op == BENCHMARK_EXTRACT:
        return op
    name, at, version = op.partition("@")
    return f"{_REVERSE_RULES[name]}{at}{version}"


def _over(extract: Extract) -> str | Extract:
    """A field extract with only its path as ``"field:<path>"`` (the S4 spelling), else itself."""

    if extract.rule == "field" and set(extract.args) == {"path"}:
        return f"{_FIELD_PREFIX}{extract.args['path']}"
    return with_normalizer(extract, None)  # the step holds the normalizer


def _vote(vote: VoteNode, judges: list[JudgeNode]) -> Vote:
    if vote.judge is not None:
        judges.append(vote.judge)
    if vote.extract == BENCHMARK_EXTRACT:
        return Vote(over=BENCHMARK_EXTRACT, weights=vote.weights)
    return Vote(over=_rule(vote.extract), normalize=vote.normalize, weights=vote.weights)


def _gated(vote: VoteNode, judges: list[JudgeNode]) -> Vote | Gate:
    gate = vote.gate
    if gate is None:
        return _vote(vote, judges)
    ref = _gate_ref(gate.observe)
    band = gate.abstain_band
    return Gate(
        when=_condition(ref, gate.cmp, gate.threshold),
        then=_vote(vote, judges),
        otherwise=_fallback(gate.otherwise),
        abstain_if=None if band is None else ref.between(*band),
    )


def _gate_ref(observe: str) -> GateRef:
    if observe == "agreement":
        return agreement()
    method, _, name = observe.partition(":")
    return signal(name).chosen() if method == "chosen" else signal(name).mean()


def _fallback(otherwise: Literal["abstain"] | JudgeNode | Model) -> Fallback:
    if isinstance(otherwise, JudgeNode):
        return JudgePick(
            otherwise.model, rubric=otherwise.rubric, params=dict(otherwise.params) or None
        )
    if isinstance(otherwise, Model):
        # WHY no role: the url4 rebuild of a fallback writer already drops the default prompt
        return _synthesize(otherwise, synthesis=None)
    return otherwise


def _statistic(node: MedianNode | MeanNode, _judges: list[JudgeNode]) -> Median | Mean:
    step = Median if isinstance(node, MedianNode) else Mean
    return step(over=_rule(node.extract), select=node.select, weights=node.weights)


def _block_form(block: Reduce, judges: list[JudgeNode]) -> Step:
    """A ``ReduceNode`` (an extract with arguments) as its step with ``over=`` that extract."""

    options = block.options
    extract = cast("Extract", options["extract"])
    weights = cast("Any", options.get("weights"))
    if block.op in ("plurality", "weighted"):
        judge = options.get("judge")
        if isinstance(judge, JudgeNode):
            judges.append(judge)
        return Vote(over=_over(extract), normalize=extract.normalize, weights=weights)
    if block.op in ("median", "mean"):
        step = Median if block.op == "median" else Mean
        select = "nearest" if block.mode == "select" else "value"
        return step(over=_over(extract), select=select, weights=weights)
    raise _cannot_rebuild(block.name)


def _pick(pick: PickNode, _judges: list[JudgeNode]) -> Step:
    if pick.by_signal is not None:
        best = ArgMax if pick.order == "max" else ArgMin
        return best(pick.by_signal, output=pick.output)
    if pick.field is not None and pick.equals is not None:
        return First(
            where=field(pick.field, normalize=pick.normalize) == pick.equals, output=pick.output
        )
    # D3: a field pick by order reads a signal in the new surface (ArgMax("field:x"))
    raise _cannot_rebuild(pick.name)


def _judge_pick(judge: JudgeNode, judges: list[JudgeNode]) -> Step:
    if judge.returns == "label":
        return JudgePick(judge.model, rubric=judge.rubric, params=dict(judge.params) or None)
    judges.append(judge)
    return ArgMax("score:judge") if judge.order == "max" else ArgMin("score:judge")


def _rank(rank: RankNode, judges: list[JudgeNode]) -> Rank:
    if rank.by is not None:
        judges.append(rank.by)
        return Rank(rank.k, by="score:judge", order=rank.order)
    if rank.by_signal is None:
        raise _cannot_rebuild(rank.name)  # D3: today's Rank(by_field=)
    return Rank(rank.k, by=rank.by_signal, order=rank.order)


def _filter(node: FilterNode, judges: list[JudgeNode]) -> Filter:
    if node.judge is not None:
        judges.append(node.judge)
    return Filter(where=node.where, over=node.extract)


def _concat(node: ConcatNode, _judges: list[JudgeNode]) -> Concat:
    return Concat(node.separator, label=node.label)


def _merge(node: MergeNode, _judges: list[JudgeNode]) -> Merge:
    return Merge(node.fields)


# Each internal reducer of today and its step (the inverse of the lowering table, lowering §2.2).
_CONVERSIONS: dict[type, Callable[[Any, list[JudgeNode]], Step]] = {
    VoteNode: _gated,
    MedianNode: _statistic,
    MeanNode: _statistic,
    Reduce: _block_form,
    PickNode: _pick,
    JudgeNode: _judge_pick,
    RankNode: _rank,
    FilterNode: _filter,
    ConcatNode: _concat,
    MergeNode: _merge,
}


__all__ = ["Rebuilt", "rebuild", "surface_value"]
