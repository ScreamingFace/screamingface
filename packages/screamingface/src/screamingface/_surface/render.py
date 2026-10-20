"""The one renderer of the new surface: ``repr`` and the rebuilt code (rebuild-display §1, §2).

FEATURE (E4b surface unit 6): ``render(value)`` is the ``repr`` of a chain or a step;
``render(value, "sf.")`` is code that names every step and value through the module alias ``sf``
(the url4 rebuild). A chain joins its steps with ``>>``; a named or optional chain, and a chain
whose first two stages are both recipes (``>>`` needs a step there), use the explicit
``Pipeline([...])`` form. A step shows only the arguments that differ from their defaults.
INVARIANT: the code of a value builds an equal value: the rebuild proves it by compiling both
(RB-1).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from screamingface._signals import Signal, _Comparison
from screamingface._surface.chain import Pipeline, Step
from screamingface._surface.fanout import Fanout
from screamingface._surface.gate import Gate
from screamingface._surface.judge import _JudgeStep
from screamingface._surface.refs import FieldEquals, GateBand, GateCondition
from screamingface._surface.steps import (
    Concat,
    Filter,
    First,
    Mean,
    Median,
    Merge,
    Rank,
    Vote,
    _ArgBest,
)
from screamingface._surface.synthesize import Synthesize
from screamingface.blocks import Extract, Matches
from screamingface.corrective import _DEFAULT_MAX_ROUNDS, CorrectiveLoop, SelfCorrective
from screamingface.model import Model
from screamingface.recipe import Recipe, _inferred_name, _inferred_self_name
from screamingface.reducer import BENCHMARK_EXTRACT
from screamingface.selection import _DEFAULT_SEPARATOR
from screamingface.signal_sources import SignalSource

_VOTE_NORMALIZE = "text"  # the normalizer of a Vote over a rule name or a field, by default


def render(value: object, prefix: str = "") -> str:
    """``value`` as one line of Python: its ``repr`` with ``prefix=""``, code with ``"sf."``."""

    if isinstance(value, Pipeline):
        return _chain(value, prefix)
    if isinstance(value, Step):
        return _step(value, prefix)
    return _recipe(value, prefix) if isinstance(value, Recipe) else _leaf(value, prefix)


def _chain(chain: Pipeline, prefix: str) -> str:
    steps = chain.steps
    explicit = (
        chain._is_named
        or chain.optional
        or len(steps) < 2
        or not any(isinstance(step, Step | Pipeline) for step in steps[:2])
    )
    if not explicit:
        return " >> ".join(_stage(step, prefix) for step in steps)
    arguments = ["[" + ", ".join(_stage(step, prefix) for step in steps) + "]"]
    if chain._is_named:
        arguments.append(f"name={chain.name!r}")
    if chain.optional:
        arguments.append("optional=True")
    return _call(prefix, "Pipeline", arguments)


def _stage(value: Recipe | Step, prefix: str) -> str:
    """A chain stage: a Model always shows as ``Model(...)``, since ``'a' >> 'b'`` is no chain."""

    if isinstance(value, Model):
        return prefix + repr(value)
    return render(value, prefix)


def _member(value: Recipe, prefix: str) -> str:
    """A member or a writer: a Model with no option shows as its route string."""

    if isinstance(value, Model) and repr(value) == f"Model({value.model!r})":
        return repr(value.model)
    return _stage(value, prefix)


def _recipe(value: Recipe, prefix: str) -> str:
    if isinstance(value, CorrectiveLoop):
        arguments = [
            _members(value.members, prefix),
            f"judge={_member(value.judge, prefix)}",
            *_rounds(value.max_rounds),
            *_name(value.name, _inferred_name(value.members)),
        ]
        return _call(prefix, "CorrectiveLoop", arguments)
    if isinstance(value, SelfCorrective):
        arguments = [
            _member(value.member, prefix),
            *_rounds(value.max_rounds),
            *_name(value.name, _inferred_self_name(value.member)),
        ]
        return _call(prefix, "SelfCorrective", arguments)
    # A Model, or a value of today's surface in a chain (only built by hand): its own repr.
    return prefix + repr(value)


def _step(step: Step, prefix: str) -> str:
    for kind, rendering in _STEPS:
        if isinstance(step, kind):
            return _call(prefix, type(step).__name__, rendering(step, prefix))
    raise TypeError(f"no rendering for sf.{type(step).__name__}")  # pragma: no cover


def _fanout(step: Fanout, prefix: str) -> list[str]:
    arguments = [_members(step.members, prefix)]
    if step.signals is not None:
        arguments.append(f"signals={_signals(step.signals, prefix)}")
    if step.quorum != "all":
        arguments.append(f"quorum={step.quorum!r}")
    arguments.extend(_name(step.name, _inferred_name(step.members)))
    if step.prompt is not None:
        arguments.append(f"prompt={step.prompt!r}")
    return arguments


def _judge(step: _JudgeStep, _prefix: str) -> list[str]:
    arguments = [repr(step.model), f"rubric={step.rubric!r}"]
    if step.params:
        arguments.append(f"params={dict(step.params)!r}")
    return arguments


def _vote(step: Vote, prefix: str) -> list[str]:
    arguments = _over(step.over, "last_line", prefix)
    if step.normalize != _vote_default_normalize(step):
        arguments.append(f"normalize={step.normalize!r}")
    return arguments + _weights(step.weights)


def _vote_default_normalize(step: Vote) -> str | None:
    """What ``normalize=`` is when it is left out: ``"text"`` for a rule name or a field; the
    extract's own (none, as the step holds it) for an ``sf.Extract``; none for ``"benchmark"``."""

    if isinstance(step.over, Extract) or step.over == BENCHMARK_EXTRACT:
        return None
    return _VOTE_NORMALIZE


def _statistic(step: Median | Mean, prefix: str) -> list[str]:
    arguments = _over(step.over, "last_number", prefix)
    if step.select != ("nearest" if isinstance(step, Median) else "value"):
        arguments.append(f"select={step.select!r}")
    return arguments + _weights(step.weights)


def _rank(step: Rank, _prefix: str) -> list[str]:
    order = [] if step.order == "max" else [f"order={step.order!r}"]
    return [repr(step.k), f"by={step.by.key!r}", *order]


def _filter(step: Filter, prefix: str) -> list[str]:
    over = [] if step.over is None else [f"over={_leaf(step.over, prefix)}"]
    return [f"where={_leaf(step.where, prefix)}", *over]


def _concat(step: Concat, _prefix: str) -> list[str]:
    separator = [] if step.separator == _DEFAULT_SEPARATOR else [repr(step.separator)]
    return [*separator, *([] if step.label else ["label=False"])]


def _arg_best(step: _ArgBest, _prefix: str) -> list[str]:
    return [repr(step.by.key), *_output(step.output)]


def _first(step: First, prefix: str) -> list[str]:
    return [f"where={_leaf(step.where, prefix)}", *_output(step.output)]


def _merge(step: Merge, prefix: str) -> list[str]:
    rules = ", ".join(f"{name!r}: {rule._render(prefix)}" for name, rule in step.fields.items())
    return ["{" + rules + "}"]


def _gate(step: Gate, prefix: str) -> list[str]:
    arguments = [f"when={_leaf(step.when, prefix)}", f"then={render(step.then, prefix)}"]
    if not isinstance(step.otherwise, str):
        arguments.append(f"otherwise={render(step.otherwise, prefix)}")
    if step.abstain_if is not None:
        arguments.append(f"abstain_if={_leaf(step.abstain_if, prefix)}")
    return arguments


def _synthesize(step: Synthesize, prefix: str) -> list[str]:
    prompt = [] if step.prompt is None else [f"prompt={step.prompt!r}"]
    return [_member(step.model, prefix), *prompt]


# Each step class and the arguments it shows. WHY Gate before Vote: neither is a subclass of the
# other, but the order keeps the table in the chain's reading order.
_STEPS: tuple[tuple[type, Callable[[Any, str], list[str]]], ...] = (
    (Fanout, _fanout),
    (_JudgeStep, _judge),
    (Rank, _rank),
    (Filter, _filter),
    (Concat, _concat),
    (Gate, _gate),
    (Vote, _vote),
    (Median, _statistic),
    (Mean, _statistic),
    (_ArgBest, _arg_best),
    (First, _first),
    (Merge, _merge),
    (Synthesize, _synthesize),
)


def _leaf(value: object, prefix: str) -> str:
    """A value inside a step: a condition, a band, an extract, a pattern, a field test."""

    if isinstance(value, Matches):
        flag = ", ignore_case=True" if value.ignore_case else ""
        return f"{prefix}matches({value.pattern!r}{flag})"
    if isinstance(value, FieldEquals):
        normalize = "" if value.normalize is None else f", normalize={value.normalize!r}"
        return f"{prefix}field({value.path!r}{normalize}) == {value.value!r}"
    # A condition, an extract or a band: each repr starts with the name it is built by
    # (signal(...), Extract(...), agreement()).
    assert isinstance(value, _Comparison | Extract | Signal | GateCondition | GateBand)
    return prefix + repr(value)


def _over(over: str | Extract, default: str, prefix: str) -> list[str]:
    if over == default:
        return []
    return [f"over={over!r}" if isinstance(over, str) else f"over={_leaf(over, prefix)}"]


def _weights(weights: tuple[float, ...] | Signal | None) -> list[str]:
    if weights is None:
        return []
    return [f"weights={weights.key!r}" if isinstance(weights, Signal) else f"weights={weights!r}"]


def _output(output: str | None) -> list[str]:
    return [] if output is None else [f"output={output!r}"]


def _members(members: tuple[Recipe, ...], prefix: str) -> str:
    return "[" + ", ".join(_member(member, prefix) for member in members) + "]"


def _signals(signals: Mapping[str, SignalSource], prefix: str) -> str:
    return (
        "{" + ", ".join(f"{name!r}: {prefix}{source!r}" for name, source in signals.items()) + "}"
    )


def _name(name: str, inferred: str) -> list[str]:
    return [] if name == inferred else [f"name={name!r}"]


def _rounds(max_rounds: int) -> list[str]:
    return [] if max_rounds == _DEFAULT_MAX_ROUNDS else [f"max_rounds={max_rounds!r}"]


def _call(prefix: str, head: str, arguments: list[str]) -> str:
    return f"{prefix}{head}({', '.join(arguments)})"


__all__ = ["render"]
