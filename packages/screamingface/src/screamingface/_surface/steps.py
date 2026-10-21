"""The reduce steps ``Vote``, ``Median`` and ``Mean`` (E4b surface, surface §6 and §9).

FEATURE: a reduce step closes a block with one combine call. ``over=`` says what each member
answer the step reads (``refs.extractor``); ``weights=`` is one number per member or a signal key.
A step checks its options when it is built, through the reducer node that it lowers to, so a
bad option raises here and never after a model call.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, cast

from screamingface._signals import JUDGE_SIGNAL, Signal, _Comparison
from screamingface._surface.chain import Step, _Category
from screamingface._surface.refs import (
    Extractor,
    FieldEquals,
    Weights,
    extractor,
    field_extract,
    is_rule_name,
    output_field,
    signal_key,
    with_normalizer,
)
from screamingface._surface.refs import weights as weights_option
from screamingface.blocks import Extract, ExtractRule, Matches
from screamingface.fields import FieldRule, MergeNode
from screamingface.reducer import _DEFAULT_NORMALIZE, BENCHMARK_EXTRACT, _check_verify
from screamingface.reducer import _Step as _OperatorStep
from screamingface.selection import _DEFAULT_SEPARATOR


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Vote(Step):
    """Plurality vote: the first member (author order) that holds the most common answer, verbatim.

    ``over=`` is the extractor (``"last_line"``, ``"last_line@1"``, ``"field:<path>"`` or
    ``sf.Extract(...)``) and ``normalize=`` its normalizer. Set the normalizer on the step or on
    the ``sf.Extract``, not on both. ``over="benchmark"`` reads each answer with the benchmark's
    own grading rule.

    ``weights=`` is one positive number per member, a signal key such as ``"cost_usd"``, or
    ``sf.signal(key)``: each answer weighs the weights of its holders. ``weights="score:judge"``
    reads the scores of a ``sf.Judge`` step in the same block and uses each score as it is: with a
    rubric where a lower number is better, the worse members get more weight.

    ``verify=`` is reserved for a later verifier check and takes only None.
    """

    _category: ClassVar[_Category] = "reduce"
    over: Extractor
    normalize: str | None
    weights: Weights | None
    verify: None

    def __init__(
        self,
        *,
        over: str | Extract = "last_line",
        normalize: str | None = _DEFAULT_NORMALIZE,
        weights: Sequence[float] | Signal | str | None = None,
        verify: None = None,
    ) -> None:
        selected = extractor(over)
        # INVARIANT: the normalizer has one home, ``normalize``, and holds the one that applies,
        # so two equal votes always lower to equal bytes (EX-2).
        object.__setattr__(self, "normalize", _vote_normalizer(selected, normalize))
        object.__setattr__(self, "over", _bare(selected))
        object.__setattr__(self, "weights", weights_option(weights, "Vote weights"))
        _check_verify(verify)
        object.__setattr__(self, "verify", None)
        _check_by_lowering(self)

    def _reads_judge(self) -> bool:
        return reads_judge(self.weights)

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Median(Step):
    """Median of the members' numeric answers: the nearest member's text, or the number itself.

    ``over=`` is the extractor (``"last_number"``, ``"field:<path>"``, ``sf.Extract(...)``); the
    normalizer is always numeric. ``select="nearest"`` copies the member nearest to the median,
    ``select="value"`` returns the number. ``weights`` makes it a weighted median: a member with a
    missing or non-positive weight is dropped.
    """

    _category: ClassVar[_Category] = "reduce"
    over: Extractor
    select: str
    weights: Weights | None

    def __init__(
        self,
        *,
        over: str | Extract = "last_number",
        select: str = "nearest",
        weights: Sequence[float] | Signal | str | None = None,
    ) -> None:
        object.__setattr__(self, "over", _numeric_over(extractor(over), "Median"))
        object.__setattr__(self, "select", select)
        object.__setattr__(self, "weights", weights_option(weights, "Median weights"))
        _check_by_lowering(self)

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Mean(Step):
    """Mean of the members' numeric answers: the number itself, or the nearest member's text.

    ``over=``, ``weights=`` and ``select=`` work as in ``Median``; the default select is
    ``"value"``.
    """

    _category: ClassVar[_Category] = "reduce"
    over: Extractor
    select: str
    weights: Weights | None

    def __init__(
        self,
        *,
        over: str | Extract = "last_number",
        select: str = "value",
        weights: Sequence[float] | Signal | str | None = None,
    ) -> None:
        object.__setattr__(self, "over", _numeric_over(extractor(over), "Mean"))
        object.__setattr__(self, "select", select)
        object.__setattr__(self, "weights", weights_option(weights, "Mean weights"))
        _check_by_lowering(self)

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Rank(Step):
    """Keep the ``k`` members with the highest (``order="max"``) or lowest value of one signal.

    ``by`` is a signal key string (``"cost_usd"``, ``"field:confidence"``, ``"score:judge"``, a
    declared name) or ``sf.signal(key)``. A ``"field:<path>"`` key reads the field as a number; a
    member with no number for ``by`` is left out. A tie at the cut goes to the earlier member.
    """

    _category: ClassVar[_Category] = "narrow"
    k: int
    by: Signal
    order: Literal["max", "min"]

    def __init__(self, k: int, *, by: str | Signal, order: Literal["max", "min"] = "max") -> None:
        object.__setattr__(self, "k", k)
        object.__setattr__(self, "by", signal_key(by, "sf.Rank"))
        object.__setattr__(self, "order", order)
        _check_by_lowering(self)

    def _reads_judge(self) -> bool:
        return reads_judge(self.by)

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Filter(Step):
    """Keep the members that pass a test, in author order.

    ``where`` is ``sf.signal(key) <op> x`` (``>``, ``>=``, ``<``, ``<=``, ``==``) or
    ``sf.matches(pattern)``. ``over=`` (only with ``sf.matches``) is the extractor whose text the
    pattern tests: a rule name, ``"field:<path>"`` or ``sf.Extract(...)``.
    """

    _category: ClassVar[_Category] = "narrow"
    where: Matches | _Comparison
    over: Extractor | None  # as the user wrote it; ``filter_extract`` gives its sf.Extract

    def __init__(self, *, where: Matches | _Comparison, over: str | Extract | None = None) -> None:
        if not isinstance(where, Matches | _Comparison):
            raise TypeError(
                "sf.Filter where= takes sf.matches(...) or a signal comparison such as "
                "sf.signal(key) >= 0.6"
            )
        if over is not None and isinstance(where, _Comparison):
            raise ValueError(  # FI-1
                "sf.Filter over= reads the text for sf.matches: a signal comparison takes no over="
            )
        object.__setattr__(self, "where", where)
        selected_over = None if over is None else extractor(over)
        if selected_over is not None:
            filter_extract(selected_over)  # refuse a pinned rule name here, when it is built
        object.__setattr__(self, "over", selected_over)
        _check_by_lowering(self)

    def _reads_judge(self) -> bool:
        return isinstance(self.where, _Comparison) and reads_judge(self.where.signal)

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Concat(Step):
    """Join the members' texts for a ``sf.Synthesize`` writer, which must follow it.

    ``label=True`` heads each text with its member's name. The writer gets the joined text, with no
    envelope.
    """

    _category: ClassVar[_Category] = "narrow"
    _needs_writer: ClassVar[bool] = True
    separator: str
    label: bool

    def __init__(self, separator: str = _DEFAULT_SEPARATOR, *, label: bool = True) -> None:
        object.__setattr__(self, "separator", separator)
        object.__setattr__(self, "label", label)
        _check_by_lowering(self)

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class _ArgBest(Step):
    """The member with the best value of one signal: ``ArgMax`` and ``ArgMin`` set ``_order``."""

    _category: ClassVar[_Category] = "reduce"
    _order: ClassVar[Literal["max", "min"]]
    by: Signal
    output: str | None

    def __init__(self, by: str | Signal, *, output: str | None = None) -> None:
        label = f"sf.{type(self).__name__}"
        object.__setattr__(self, "by", signal_key(by, label))
        if output is not None and reads_judge(self.by):
            raise ValueError(  # JU-2
                "output= reads a member field; a judge pick returns the member text"
            )
        object.__setattr__(self, "output", output_field(output, label))
        _check_by_lowering(self)

    def _reads_judge(self) -> bool:
        return reads_judge(self.by)

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ArgMax(_ArgBest):
    """Copy the member with the highest value of one signal, unchanged.

    ``by`` is a signal key string or ``sf.signal(key)``; a member with no value is left out.
    ``by="score:judge"`` reads a ``sf.Judge`` step of the block. ``output="<field>"`` makes the
    answer that top-level field of the winner's JSON reply; a judge pick takes no ``output=``.
    """

    _order: ClassVar[Literal["max", "min"]] = "max"
    # WHY again: a frozen dataclass subclass adds __hash__; a step is unhashable like any recipe
    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ArgMin(_ArgBest):
    """Copy the member with the lowest value of one signal, unchanged (see ``sf.ArgMax``)."""

    _order: ClassVar[Literal["max", "min"]] = "min"
    # WHY again: a frozen dataclass subclass adds __hash__; a step is unhashable like any recipe
    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class First(Step):
    """Copy the first member, in author order, whose JSON field equals a value.

    ``where`` is ``sf.field(path, normalize=None) == value``. With no normalizer the value
    compares as JSON text, so ``== 7`` also matches the string ``"7"``. ``output`` works as in
    ``sf.ArgMax``.
    """

    _category: ClassVar[_Category] = "reduce"
    where: FieldEquals
    output: str | None

    def __init__(self, *, where: FieldEquals, output: str | None = None) -> None:
        if not isinstance(where, FieldEquals):
            raise TypeError("sf.First where= takes sf.field(path) == value")
        object.__setattr__(self, "where", where)
        object.__setattr__(self, "output", output_field(output, "sf.First"))
        _check_by_lowering(self)

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Merge(Step):
    """One JSON object with exactly the declared fields, each built by its ``sf.FieldRule``.

    A Merge reads the whole fanout context, and a model-written field makes its own call over
    every member, so a ``Merge`` cannot follow a narrow step.
    """

    _category: ClassVar[_Category] = "reduce"
    fields: Mapping[str, FieldRule] = field(compare=False)
    # WHY a tuple: the fields compile in their order, so two Merges are equal only in one order.
    _items: tuple[tuple[str, FieldRule], ...] = field(repr=False)

    def __init__(self, fields: Mapping[str, FieldRule]) -> None:
        # WHY the MergeNode holds the fields: it checks them and keeps them in a read-only map.
        checked = MergeNode(fields).fields
        object.__setattr__(self, "fields", checked)
        object.__setattr__(self, "_items", tuple(checked.items()))

    def _sees_every_member(self) -> bool:
        return True

    __hash__: ClassVar[Any] = None


def reads_judge(value: Weights | None) -> bool:
    """Whether a weight reads ``score:judge``, which only a ``sf.Judge`` step writes."""

    return isinstance(value, Signal) and value.key == JUDGE_SIGNAL


def _vote_normalizer(over: Extractor, normalize: str | None) -> str | None:
    """The normalizer that applies to a vote: the default is ``"text"`` for a rule name or a
    field, the ``sf.Extract``'s own (or none) for an extract, and none for ``"benchmark"``, which
    takes the benchmark's own."""

    passed = normalize is not _DEFAULT_NORMALIZE
    if passed and normalize is not None:
        _OperatorStep(normalize)  # TypeError for a non-str or blank name
    if isinstance(over, Extract):
        return _extract_normalizer(over, normalize if passed else None, passed=passed)
    if over == BENCHMARK_EXTRACT:
        return _benchmark_normalizer(passed=passed)
    return None if normalize is None else str(normalize)


def _extract_normalizer(over: Extract, normalize: str | None, *, passed: bool) -> str | None:
    if over.normalize is None:
        return normalize
    if passed:
        raise ValueError("set normalize on sf.Extract or on the step, not on both")  # EX-2
    return over.normalize


def _benchmark_normalizer(*, passed: bool) -> None:
    if passed:
        raise ValueError(
            f"over={BENCHMARK_EXTRACT!r} takes the benchmark's own normalizer: leave out normalize="
        )


def _bare(over: Extractor) -> Extractor:
    """``over`` with no normalizer of its own: the step holds it (one home)."""

    return with_normalizer(over, None) if isinstance(over, Extract) else over


def _numeric_over(over: Extractor, label: str) -> Extractor:
    """A ``Median`` or ``Mean`` extract: its normalizer is always numeric, so it holds none."""

    if isinstance(over, Extract) and over.normalize is not None:
        if over.normalize != "numeric":
            raise ValueError(
                f"sf.{label} reads numbers, so its sf.Extract takes normalize='numeric' or none"
            )
        return with_normalizer(over, None)
    return over


def filter_extract(over: str | Extract) -> Extract:
    """The ``sf.Extract`` a Filter reads: a rule name with no version, a field, or an extract."""

    selected = extractor(over)
    if isinstance(selected, Extract):
        return selected
    if not is_rule_name(selected):
        return field_extract(selected, None)
    if "@" in selected:
        raise ValueError(
            "sf.Filter over= takes a rule name with no version, 'field:<path>' or "
            f"sf.Extract(...), not {selected!r}"
        )
    return Extract(cast("ExtractRule", selected))


def _check_by_lowering(step: Step) -> None:
    # WHY lazy: lowering.py imports this module
    from screamingface._surface.lowering import check_step

    check_step(step)


__all__ = [
    "ArgMax",
    "ArgMin",
    "Concat",
    "Filter",
    "First",
    "Mean",
    "Median",
    "Merge",
    "Rank",
    "Vote",
]
