"""The reduce steps ``Vote``, ``Median`` and ``Mean`` (E4b surface, surface §6 and §9).

FEATURE: a reduce step closes a block with one combine call. ``over=`` says what each member
answer the step reads (``refs.extractor``); ``weights=`` is one number per member or a signal key.
A step checks its options when it is built, through the reducer of today that it lowers to, so a
bad option raises here and never after a model call.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from screamingface._signals import JUDGE_SIGNAL, Signal
from screamingface._surface.chain import Step, _Category
from screamingface._surface.refs import Extractor, Weights, extractor, with_normalizer
from screamingface._surface.refs import weights as weights_option
from screamingface.blocks import Extract
from screamingface.reducer import _DEFAULT_NORMALIZE, BENCHMARK_EXTRACT, _check_verify
from screamingface.reducer import _Step as _OperatorStep


@dataclass(frozen=True, slots=True, init=False)
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

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False)
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


@dataclass(frozen=True, slots=True, init=False)
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


def _check_by_lowering(step: Vote | Median | Mean) -> None:
    # WHY lazy: lowering.py imports this module
    from screamingface._surface.lowering import check_step

    check_step(step)


__all__ = ["Mean", "Median", "Vote"]
