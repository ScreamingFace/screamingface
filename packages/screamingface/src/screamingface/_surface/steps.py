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
from screamingface._surface.refs import Extractor, Weights, extractor
from screamingface._surface.refs import weights as weights_option
from screamingface.blocks import Extract
from screamingface.reducer import _DEFAULT_NORMALIZE, _check_verify


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
        _check_one_normalizer(selected, normalize)
        object.__setattr__(self, "over", selected)
        object.__setattr__(self, "normalize", normalize)
        object.__setattr__(self, "weights", weights_option(weights, "Vote weights"))
        _check_verify(verify)
        object.__setattr__(self, "verify", None)
        # WHY not for score:judge: that weight needs the block's sf.Judge, so its reducer is built
        # when the block closes.
        if not reads_judge(self.weights):
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
        object.__setattr__(self, "over", extractor(over))
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
        object.__setattr__(self, "over", extractor(over))
        object.__setattr__(self, "select", select)
        object.__setattr__(self, "weights", weights_option(weights, "Mean weights"))
        _check_by_lowering(self)

    __hash__: ClassVar[Any] = None


def reads_judge(value: Weights | None) -> bool:
    """Whether a weight reads ``score:judge``, which only a ``sf.Judge`` step writes."""

    return isinstance(value, Signal) and value.key == JUDGE_SIGNAL


def _check_one_normalizer(over: Extractor, normalize: str | None) -> None:
    """EX-2: the caller passes ``normalize=`` (not the default) and the ``sf.Extract`` has one."""

    if isinstance(over, Extract) and over.normalize is not None:
        if normalize is not _DEFAULT_NORMALIZE:
            raise ValueError("set normalize on sf.Extract or on the step, not on both")


def _check_by_lowering(step: Vote | Median | Mean) -> None:
    # WHY lazy: lowering.py imports this module
    from screamingface._surface.lowering import reducer_node

    reducer_node(step)


__all__ = ["Mean", "Median", "Vote"]
