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

from screamingface._surface.chain import Pipeline as Chain
from screamingface._surface.chain import Step
from screamingface._surface.fanout import Fanout
from screamingface._surface.gate import Fallback, Gate
from screamingface._surface.judge import Judge, JudgePick
from screamingface._surface.refs import (
    FieldEquals,
    GateRef,
    _condition,
    agreement,
    field,
    signal,
    with_normalizer,
)
from screamingface._surface.render import dispatch, model_options, render
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
from screamingface.blocks import _REVERSE_RULES, Extract, ReduceNode
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.fields import MergeNode, PickNode
from screamingface.fusion import FusionNode
from screamingface.judge import JudgeNode
from screamingface.model import Model
from screamingface.pipeline import Pipeline
from screamingface.recipe import Recipe, _inferred_name, _inferred_self_name, _kept_name
from screamingface.reducer import (
    BENCHMARK_EXTRACT,
    MeanNode,
    MedianNode,
    Reducer,
    VoteNode,
    _cannot_rebuild,
    _narrow_steps,
)
from screamingface.selection import ConcatNode, FilterNode, RankNode

_CANNOT_REBUILD = "URL4 Candidate has a recipe this SDK version cannot rebuild"
_FIELD_PREFIX = "field:"


class _Unexpressible(Exception):
    """A value of today that has no new-surface form; ``_converted`` names it "cannot rebuild".

    WHY a dedicated exception: only these refusals become "cannot rebuild", so a programming error
    in a converter surfaces as itself.
    """


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
        _recompiles,
        _replay_check_surface,
    )

    decoded = _decode_candidate(url4)
    # editable: a model call whose prompt is its role's default comes back with no prompt
    today = _recipe_from_topology(decoded.topology, decoded.calls, editable=True)
    value = surface_value(today)
    check_surface = _replay_check_surface(decoded.topology)
    if not _recompiles(decoded.candidate, value, decoded.calls, check_surface=check_surface):
        raise ValueError(_CANNOT_REBUILD)
    return Rebuilt(value, f"candidate = {render(value, 'sf.')}")


def surface_value(value: Recipe) -> Recipe:
    """Today's ``value`` in the new surface: a Fusion becomes a block, a Pipeline a chain."""

    convert = dispatch(_RECIPES, value)
    if convert is None:  # pragma: no cover - the url4 topology has no other kind
        raise ValueError(_CANNOT_REBUILD)
    return convert(value)


def _model(model: Model) -> Model:
    return model


def _fusion(fusion: FusionNode) -> Chain:
    return Chain(_block(fusion), optional=fusion.optional)


def _loop(loop: CorrectiveLoop) -> CorrectiveLoop:
    return CorrectiveLoop(
        [surface_value(member) for member in loop.members],
        judge=surface_value(loop.judge),
        max_rounds=loop.max_rounds,
        name=_kept_name(loop.name, _inferred_name(loop.members)),
    )


def _solo(solo: SelfCorrective) -> SelfCorrective:
    return SelfCorrective(
        surface_value(solo.member),
        max_rounds=solo.max_rounds,
        name=_kept_name(solo.name, _inferred_self_name(solo.member)),
    )


def _chain(pipeline: Pipeline) -> Chain:
    """Today's stages as one chain: a selection Fusion and the stage after it are one block,
    ``Fanout >> <narrow> >> Synthesize(next stage)`` (rebuild-display §1)."""

    items: list[Recipe | Step] = []
    stages = list(pipeline.stages)
    while stages:
        stage = stages.pop(0)
        if not isinstance(stage, FusionNode):
            items.append(surface_value(stage))
        elif _is_selection(stage) and stages:
            items.extend(_block(stage, writer=stages.pop(0)))
        else:
            items.extend(_block(stage))
    name = pipeline.name if pipeline._is_named else None
    return Chain(items, name=name, optional=pipeline.optional)


# The recipe kinds of today and their new-surface form.
_RECIPES: tuple[tuple[type, Callable[[Any], Recipe]], ...] = (
    (Model, _model),
    (FusionNode, _fusion),
    (Pipeline, _chain),
    (CorrectiveLoop, _loop),
    (SelfCorrective, _solo),
)


def _is_selection(fusion: FusionNode) -> bool:
    synthesizer = fusion.synthesizer
    return isinstance(synthesizer, Reducer) and synthesizer._combine_plan().kind == "selection"


def _block(fusion: FusionNode, writer: Recipe | None = None) -> list[Recipe | Step]:
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
        return [fanout, _synthesize(synthesizer)]
    steps: list[Recipe | Step] = [fanout, *_reducer_steps(synthesizer)]
    if writer is not None:
        steps.append(_synthesize(writer))
    return steps


def _synthesize(writer: Recipe) -> Synthesize:
    """The writer step: a Model whose one option is its prompt shows the prompt on the step."""

    rebuilt = surface_value(writer)
    if isinstance(rebuilt, Model) and model_options(rebuilt) == {"prompt"}:
        return Synthesize(rebuilt.model, prompt=rebuilt.prompt)
    return Synthesize(rebuilt)


# ---------------------------------------------------------------- a reducer as steps


def _reducer_steps(reducer: Reducer) -> list[Step]:
    """The judge (when a step reads one), the narrow steps in order, then the main step."""

    judges: list[JudgeNode] = []
    narrow = [_converted(step, judges) for step in _narrow_steps(reducer)]
    main = _converted(reducer, judges)
    try:
        judge = _judge_step(judges)
    except _Unexpressible as exc:
        raise _cannot_rebuild(reducer.name) from exc
    return [*judge, *narrow, main]


def _judge_step(judges: list[JudgeNode]) -> list[Step]:
    """One ``Judge`` for every step that reads ``score:judge``; two different judges: refuse."""

    steps: list[Step] = [
        _built(Judge, judge.model, rubric=judge.rubric, params=dict(judge.params) or None)
        for judge in judges
    ]
    if any(step != steps[0] for step in steps[1:]):
        raise _Unexpressible("two different judges in one block")
    return steps[:1]


def _converted(reducer: Reducer, judges: list[JudgeNode]) -> Step:
    """One reducer of today as its step; a value with no new-surface form is "cannot rebuild"."""

    convert = dispatch(_CONVERSIONS, reducer)
    if convert is None:
        raise _cannot_rebuild(reducer.name)
    try:
        return convert(reducer, judges)
    except _Unexpressible as exc:
        raise _cannot_rebuild(reducer.name) from exc


def _built[T](build: Callable[..., T], *args: object, **kwargs: object) -> T:
    """A new-surface value built from url4 data: its own refusal means no new-surface form."""

    try:
        return build(*args, **kwargs)
    except (TypeError, ValueError) as exc:
        raise _Unexpressible(str(exc)) from exc


def _rule(op: str) -> str:
    """An Engine extract op as its rule name, with its pin (erratum E2: ``json_object@1`` is
    ``json@1``); ``benchmark`` has no op; an op of no rule (a hand edit) has no form."""

    if op == BENCHMARK_EXTRACT:
        return op
    name, at, version = op.partition("@")
    rule = _REVERSE_RULES.get(name)
    if rule is None:
        raise _Unexpressible(f"no extract rule for {op!r}")
    return f"{rule}{at}{version}"


def _over(extract: Extract) -> str | Extract:
    """A field extract with only its path as ``"field:<path>"`` (the S4 spelling), else itself
    with no normalizer (the step holds the normalizer)."""

    if extract.rule == "field" and set(extract.args) == {"path"}:
        return f"{_FIELD_PREFIX}{extract.args['path']}"
    return with_normalizer(extract, None)


def _filter_over(extract: Extract) -> str | Extract:
    """The ``over=`` a Filter's extract was written with: a rule name with no argument, a field,
    or the ``sf.Extract`` itself when it holds a normalizer or other arguments."""

    if extract.normalize is not None:
        return extract
    if not extract.args:
        return str(extract.rule)
    return _over(extract)


def _unpinned(select: str) -> str:
    """A statistic's select op with no pin: ``select=`` takes ``"nearest"`` or ``"value"``."""

    return select.partition("@")[0]


def _vote(vote: VoteNode, judges: list[JudgeNode]) -> Vote:
    if vote.judge is not None:
        judges.append(vote.judge)
    if vote.extract == BENCHMARK_EXTRACT:
        return _built(Vote, over=BENCHMARK_EXTRACT, weights=vote.weights)
    return _built(Vote, over=_rule(vote.extract), normalize=vote.normalize, weights=vote.weights)


def _gated(vote: VoteNode, judges: list[JudgeNode]) -> Vote | Gate:
    gate = vote.gate
    if gate is None:
        return _vote(vote, judges)
    ref = _built(_gate_ref, gate.observe)
    band = gate.abstain_band
    return _built(
        Gate,
        when=_built(_condition, ref, gate.cmp, gate.threshold),
        then=_vote(vote, judges),
        otherwise=_fallback(gate.otherwise),
        abstain_if=None if band is None else _built(ref.between, *band),
    )


def _gate_ref(observe: str) -> GateRef:
    if observe == "agreement":
        return agreement()
    method, _, name = observe.partition(":")
    return signal(name).chosen() if method == "chosen" else signal(name).mean()


def _fallback(otherwise: Literal["abstain"] | JudgeNode | Model) -> Fallback:
    if isinstance(otherwise, JudgeNode):
        params = dict(otherwise.params) or None
        return _built(JudgePick, otherwise.model, rubric=otherwise.rubric, params=params)
    if isinstance(otherwise, Model):
        return _synthesize(otherwise)
    return otherwise


def _statistic(node: MedianNode | MeanNode, _judges: list[JudgeNode]) -> Median | Mean:
    step = Median if isinstance(node, MedianNode) else Mean
    select = _unpinned(node.select)
    return _built(step, over=_rule(node.extract), select=select, weights=node.weights)


def _block_form(block: ReduceNode, judges: list[JudgeNode]) -> Step:
    """A ``ReduceNode`` (an extract with arguments) as its step with ``over=`` that extract."""

    options = block.options
    extract = cast("Extract", options["extract"])
    weights = cast("Any", options.get("weights"))
    if block.op in ("plurality", "weighted"):
        judge = options.get("judge")
        if isinstance(judge, JudgeNode):
            judges.append(judge)
        return _built(Vote, over=_over(extract), normalize=extract.normalize, weights=weights)
    if block.op in ("median", "mean"):
        step = Median if block.op == "median" else Mean
        select = "nearest" if block.mode == "select" else "value"
        return _built(step, over=_over(extract), select=select, weights=weights)
    raise _Unexpressible(f"no step for sf.Reduce({block.op!r})")


def _pick(pick: PickNode, _judges: list[JudgeNode]) -> Step:
    if pick.by_signal is not None:
        best = ArgMax if pick.order == "max" else ArgMin
        return _built(best, pick.by_signal, output=pick.output)
    if pick.field is not None and pick.equals is not None:
        where = _built(_field_test, pick.field, pick.normalize, pick.equals)
        return _built(First, where=where, output=pick.output)
    # D3: a field pick by order reads a signal in the new surface (ArgMax("field:x"))
    raise _Unexpressible("a field pick by order")


def _field_test(path: str, normalize: Any, value: str) -> FieldEquals:
    return field(path, normalize=normalize) == value


def _judge_pick(judge: JudgeNode, judges: list[JudgeNode]) -> Step:
    if judge.returns == "label":
        params = dict(judge.params) or None
        return _built(JudgePick, judge.model, rubric=judge.rubric, params=params)
    judges.append(judge)
    return ArgMax("score:judge") if judge.order == "max" else ArgMin("score:judge")


def _rank(rank: RankNode, judges: list[JudgeNode]) -> Rank:
    if rank.by is not None:
        judges.append(rank.by)
        return _built(Rank, rank.k, by="score:judge", order=rank.order)
    if rank.by_signal is None:
        raise _Unexpressible("a rank by field")  # D3: today's Rank(by_field=)
    return _built(Rank, rank.k, by=rank.by_signal, order=rank.order)


def _filter(node: FilterNode, judges: list[JudgeNode]) -> Filter:
    if node.judge is not None:
        judges.append(node.judge)
    over = None if node.extract is None else _filter_over(node.extract)
    return _built(Filter, where=node.where, over=over)


def _concat(node: ConcatNode, _judges: list[JudgeNode]) -> Concat:
    return _built(Concat, node.separator, label=node.label)


def _merge(node: MergeNode, _judges: list[JudgeNode]) -> Merge:
    return _built(Merge, node.fields)


# Each internal reducer of today and its step (the inverse of the lowering table, lowering §2.2).
_CONVERSIONS: tuple[tuple[type, Callable[[Any, list[JudgeNode]], Step]], ...] = (
    (VoteNode, _gated),
    (MedianNode, _statistic),
    (MeanNode, _statistic),
    (ReduceNode, _block_form),
    (PickNode, _pick),
    (JudgeNode, _judge_pick),
    (RankNode, _rank),
    (FilterNode, _filter),
    (ConcatNode, _concat),
    (MergeNode, _merge),
)


__all__ = ["Rebuilt", "rebuild"]
