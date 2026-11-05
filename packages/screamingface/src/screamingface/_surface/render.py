"""The one renderer of the new surface: ``repr`` and the rebuilt code (rebuild-display §1, §2).

FEATURE (E4b surface unit 6): ``render(value)`` is the ``repr`` of a chain or a step;
``render(value, "sf.")`` is code that names every step and value through the module alias ``sf``
(the url4 rebuild). A chain joins its steps with ``>>``; a named or optional chain, and a chain
whose first two stages are both recipes (``>>`` needs a step there), use the explicit
``Pipeline([...])`` form. A step shows only the arguments that differ from their defaults.
INVARIANT: the defaults are read from the constructors (``inspect.signature``), and the default
normalizer of a Vote from ``steps._vote_normalizer``, so the renderer never keeps its own copy.
The code of a value builds an equal value: the rebuild proves it by compiling both (RB-1).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from functools import cache
from typing import Any

from screamingface._signals import Signal
from screamingface._surface.chain import Pipeline, Step
from screamingface._surface.fanout import Fanout
from screamingface._surface.gate import Gate
from screamingface._surface.judge import _JudgeStep
from screamingface._surface.refs import FieldEquals
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
    _vote_normalizer,
)
from screamingface._surface.synthesize import Synthesize
from screamingface.blocks import Extract
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.model import Model
from screamingface.recipe import Recipe, _inferred_name, _inferred_self_name
from screamingface.reducer import _DEFAULT_NORMALIZE
from screamingface.signal_sources import SignalSource


def dispatch[F](table: tuple[tuple[type, F], ...], value: object) -> F | None:
    """The entry of the first class in ``table`` that ``value`` is an instance of; else None.

    The one dispatch idiom of the renderer and the rebuild (``rebuild.py``).
    """

    return next((entry for kind, entry in table if isinstance(value, kind)), None)


def model_options(model: Model) -> frozenset[str]:
    """The options a Model holds besides its route: ``name``, ``prompt``, ``params``,
    ``optional``. A Model with none shows as its route string."""

    held = {
        "name": model._sample_id is not None,
        "prompt": model.prompt is not None,
        "params": bool(model.params),
        "optional": model.optional,
    }
    return frozenset(name for name, is_set in held.items() if is_set)


def render(value: object, prefix: str = "") -> str:
    """``value`` as one line of Python: its ``repr`` with ``prefix=""``, code with ``"sf."``."""

    if isinstance(value, Pipeline):
        return _chain(value, prefix)
    if isinstance(value, Step):
        return _step(value, prefix)
    return _recipe(value, prefix) if isinstance(value, Recipe) else _leaf(value, prefix)


@cache
def _defaults(kind: type) -> Mapping[str, object]:
    """The keyword defaults of a constructor: the one source of every "only if not default"."""

    return {
        name: parameter.default
        for name, parameter in inspect.signature(kind).parameters.items()
        if parameter.default is not inspect.Parameter.empty
    }


def _keyword(value: object, kind: type, name: str, text: str | None = None) -> list[str]:
    """``name=<text>`` when ``value`` is not the constructor default of ``name``; else nothing."""

    if value == _defaults(kind)[name]:
        return []
    return [f"{name}={repr(value) if text is None else text}"]


def code(value: Recipe, target: str, *, width: int = 100) -> str:
    """``<target> = <value>`` as Python with the ``sf.`` prefix: one line when it fits in
    ``width``, else a chain shows one stage per line (a step inside a stage stays on its line)."""

    line = f"{target} = {render(value, 'sf.')}"
    if len(line) <= width or not isinstance(value, Pipeline):
        return line
    stages = [_stage(step, "sf.") for step in value.steps]
    if not _explicit(value):
        rest = [f"    >> {stage}" for stage in stages[1:]]
        return "\n".join([f"{target} = (", f"    {stages[0]}", *rest, ")"])
    head = [f"{target} = sf.Pipeline(", "    ["]
    listed = [f"        {stage}," for stage in stages]
    options = [f"    {option}," for option in _chain_options(value)]
    return "\n".join([*head, *listed, "    ],", *options, ")"])


def _explicit(chain: Pipeline) -> bool:
    """Whether a chain needs the ``Pipeline([...])`` form: named, optional, one stage, or two
    recipes first (``'a' >> 'b'`` is no chain)."""

    steps = chain.steps
    return (
        chain._is_named
        or chain.optional
        or len(steps) < 2
        or not any(isinstance(step, Step | Pipeline) for step in steps[:2])
    )


def _chain_options(chain: Pipeline) -> list[str]:
    options = [f"name={chain.name!r}"] if chain._is_named else []
    return [*options, *_keyword(chain.optional, Pipeline, "optional")]


def _chain(chain: Pipeline, prefix: str) -> str:
    steps = chain.steps
    if not _explicit(chain):
        return " >> ".join(_stage(step, prefix) for step in steps)
    arguments = ["[" + ", ".join(_stage(step, prefix) for step in steps) + "]"]
    return _call(prefix, "Pipeline", [*arguments, *_chain_options(chain)])


def _stage(value: Recipe | Step, prefix: str) -> str:
    """A chain stage: a Model always shows as ``Model(...)``, since ``'a' >> 'b'`` is no chain."""

    if isinstance(value, Model):
        return prefix + repr(value)
    return render(value, prefix)


def _member(value: Recipe, prefix: str) -> str:
    """A member or a writer: a Model with no option shows as its route string."""

    if isinstance(value, Model) and not model_options(value):
        return repr(value.model)
    return _stage(value, prefix)


def _recipe(value: Recipe, prefix: str) -> str:
    if isinstance(value, CorrectiveLoop):
        arguments = [
            _members(value.members, prefix),
            f"judge={_member(value.judge, prefix)}",
            *_keyword(value.max_rounds, CorrectiveLoop, "max_rounds"),
            *_name(value.name, _inferred_name(value.members)),
        ]
        return _call(prefix, "CorrectiveLoop", arguments)
    if isinstance(value, SelfCorrective):
        arguments = [
            _member(value.member, prefix),
            *_keyword(value.max_rounds, SelfCorrective, "max_rounds"),
            *_name(value.name, _inferred_self_name(value.member)),
        ]
        return _call(prefix, "SelfCorrective", arguments)
    # A Model, or an internal node in a chain (only built by hand): its own repr.
    return prefix + repr(value)


def _step(step: Step, prefix: str) -> str:
    rendering = dispatch(_STEPS, step)
    if rendering is None:  # pragma: no cover - every step class has a row
        raise TypeError(f"no rendering for sf.{type(step).__name__}")
    return _call(prefix, type(step).__name__, rendering(step, prefix))


def _fanout(step: Fanout, prefix: str) -> list[str]:
    arguments = [_members(step.members, prefix)]
    if step.signals is not None:
        arguments.append(f"signals={_signals(step.signals, prefix)}")
    arguments.extend(_keyword(step.quorum, Fanout, "quorum"))
    arguments.extend(_name(step.name, _inferred_name(step.members)))
    arguments.extend(_keyword(step.prompt, Fanout, "prompt"))
    return arguments


def _judge(step: _JudgeStep, _prefix: str) -> list[str]:
    params = dict(step.params) or None
    return [repr(step.model), f"rubric={step.rubric!r}", *_keyword(params, type(step), "params")]


def _vote(step: Vote, prefix: str) -> list[str]:
    # WHY the normalizer the constructor gives for the default: it depends on over= (EX-2)
    default = _vote_normalizer(step.over, _DEFAULT_NORMALIZE)
    normalize = [] if step.normalize == default else [f"normalize={step.normalize!r}"]
    return [*_over(step, prefix), *normalize, *_weights(step)]


def _statistic(step: Median | Mean, prefix: str) -> list[str]:
    return [*_over(step, prefix), *_keyword(step.select, type(step), "select"), *_weights(step)]


def _rank(step: Rank, _prefix: str) -> list[str]:
    return [repr(step.k), f"by={step.by.key!r}", *_keyword(step.order, Rank, "order")]


def _filter(step: Filter, prefix: str) -> list[str]:
    return [f"where={_leaf(step.where, prefix)}", *_over(step, prefix)]


def _concat(step: Concat, _prefix: str) -> list[str]:
    separator = [] if step.separator == _defaults(Concat)["separator"] else [repr(step.separator)]
    return [*separator, *_keyword(step.label, Concat, "label")]


def _arg_best(step: _ArgBest, _prefix: str) -> list[str]:
    return [repr(step.by.key), *_keyword(step.output, type(step), "output")]


def _first(step: First, prefix: str) -> list[str]:
    return [f"where={_leaf(step.where, prefix)}", *_keyword(step.output, First, "output")]


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
    return [_member(step.model, prefix), *_keyword(step.prompt, Synthesize, "prompt")]


# Each step class and the arguments it shows.
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
    """A value inside a step: a condition, a band, an extract, a pattern, a field test.

    A value with a ``_python()`` (``sf.matches(...)``, ``sf.signal(...) >= x``,
    ``sf.Extract(...)``) gives its own text; the gate condition and band give their repr, which
    starts with the name they are built by (``agreement()``, ``signal(...)``).
    """

    if isinstance(value, FieldEquals):
        normalize = "" if value.normalize is None else f", normalize={value.normalize!r}"
        return f"{prefix}field({value.path!r}{normalize}) == {value.value!r}"
    python = getattr(value, "_python", None)
    text = repr(value) if python is None else str(python()).removeprefix("sf.")
    return prefix + text


def _over(step: Vote | Median | Mean | Filter, prefix: str) -> list[str]:
    """``over=`` as the user wrote it: a rule name, ``"field:<path>"`` or ``sf.Extract(...)``."""

    over = step.over
    if over == _defaults(type(step))["over"]:
        return []
    return [f"over={_leaf(over, prefix)}" if isinstance(over, Extract) else f"over={over!r}"]


def _weights(step: Vote | Median | Mean) -> list[str]:
    weights = step.weights
    if weights is None:
        return []
    return [f"weights={weights.key!r}" if isinstance(weights, Signal) else f"weights={weights!r}"]


def _members(members: tuple[Recipe, ...], prefix: str) -> str:
    return "[" + ", ".join(_member(member, prefix) for member in members) + "]"


def _signals(signals: Mapping[str, SignalSource], prefix: str) -> str:
    return (
        "{" + ", ".join(f"{name!r}: {prefix}{source!r}" for name, source in signals.items()) + "}"
    )


def _name(name: str, inferred: str) -> list[str]:
    return [] if name == inferred else [f"name={name!r}"]


def _call(prefix: str, head: str, arguments: list[str]) -> str:
    return f"{prefix}{head}({', '.join(arguments)})"


__all__ = ["code", "dispatch", "model_options", "render"]
