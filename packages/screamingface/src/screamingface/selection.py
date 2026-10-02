"""sf.Rank and sf.Concat: Fusion synthesizers that hand a selection to the NEXT stage (OME-1289).

A selection is not an answer. ``Rank`` keeps the top k original member texts, ``Concat`` joins every
original member text in author order; neither calls a model to rewrite anything (Rank by a judge
calls the judge model for scores, never for text). The compiler therefore refuses a selection
Fusion that ends a candidate, is a Fusion member, or feeds a corrective loop, and the next
Pipeline stage receives exactly the selection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, cast

from screamingface.judge import Judge, judge_from_signals
from screamingface.reducer import (
    _MAX_REDUCER_MEMBERS,
    _REDUCER_CLASSES,
    Reducer,
    _cannot_rebuild,
    _decoded,
    _field_path,
    _ModelSignal,
    _ReducerPlan,
    _require_steps,
    _spec_steps,
    _Step,
    _Steps,
)

# INVARIANT: the Engine's top_k@1 `_MAX_K` (operators/selection.py), copied; it is also the most
# members a reducer Fusion takes, so one constant serves both.
_MAX_K = _MAX_REDUCER_MEMBERS
# INVARIANT: the Engine's join@1 `_MAX_SEPARATOR_CHARS` (operators/selection.py), copied; a longer
# separator is refused here, before any call is made.
_MAX_SEPARATOR_CHARS = 1024
_DEFAULT_SEPARATOR = "\n\n---\n\n"
# WHY the exact id: scores@1 assumes the v1 output form of the numeric normalizer, so a later
# numeric@2 must not change what a Rank by field means.
_RANK_NORMALIZER = "numeric@1"


@dataclass(frozen=True, slots=True, init=False)
class Rank(Reducer):
    """Keep the ``k`` best-scored members: the next stage gets their original texts, best first.

    ``by=sf.Judge(..., returns="scores")`` scores every member with a judge model;
    ``by_field="score"`` reads a number from each member's JSON reply. A tie at the cut goes to the
    earlier member. A Rank Fusion must be followed by another Pipeline stage.
    """

    name: str
    k: int
    by: Judge | None
    by_field: str | None

    def __init__(self, k: int, *, by: Judge | None = None, by_field: str | None = None) -> None:
        if isinstance(k, bool) or not isinstance(k, int):
            raise TypeError("Rank k must be an integer")
        if not 1 <= k <= _MAX_K:
            raise ValueError(f"Rank k must be between 1 and {_MAX_K}")
        if (by is None) == (by_field is None):
            raise ValueError("Rank needs exactly one of by= or by_field=")
        if by is not None and not isinstance(by, Judge):
            raise TypeError("Rank by must be an sf.Judge")
        if by is not None and by.returns != "scores":
            raise ValueError("Rank(by=...) needs sf.Judge(..., returns='scores')")
        if by_field is not None:
            _field_path(by_field, "Rank by_field")
        object.__setattr__(self, "name", "rank")
        object.__setattr__(self, "k", k)
        object.__setattr__(self, "by", by)
        object.__setattr__(self, "by_field", by_field)

    def _plan(self) -> _ReducerPlan:
        select = _Step("top_k", {"k": self.k})
        if self.by_field is None:
            steps = _Steps(reduce=_Step("scores", {"source": "judge"}), select=select)
        else:
            steps = _Steps(
                extract=_Step("json_field", {"path": self.by_field}),
                normalize=_Step(_RANK_NORMALIZER),
                reduce=_Step("scores", {"source": "values"}),
                select=select,
            )
        calls = () if self.by is None else (self.by._signal_call(),)
        return _ReducerPlan("rank", "selection", steps, signal_calls=calls)

    def _check_members(self, count: int) -> None:
        if self.k > count:
            raise ValueError(f"Rank keeps k={self.k} members but the Fusion has {count}")

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Rank:
        return cls._rebuild(spec, ())

    @classmethod
    def _rebuild(cls, spec: Mapping[str, object], signals: tuple[_ModelSignal, ...]) -> Rank:
        steps = _spec_steps(spec)
        select, extract = steps["select"], steps["extract"]
        k = None if select is None else select[1].get("k")
        if isinstance(k, bool) or not isinstance(k, int):
            raise _cannot_rebuild("rank")
        if signals:
            rank = _decoded("rank", cls, k, by=judge_from_signals(signals, "scores"))
        else:
            path = None if extract is None else extract[1].get("path")
            if not isinstance(path, str):
                raise _cannot_rebuild("rank")
            rank = _decoded("rank", cls, k, by_field=path)
        _require_steps(spec, rank._plan().steps, "rank")
        # WHY: the Fusion refuses a k above its member count, so a recovery must too
        _decoded("rank", rank._check_members, len(cast("Sequence[str]", spec["members"])))
        return rank

    def _python(self) -> str:
        if self.by is None:
            return f"sf.{self!r}"
        return f"sf.Rank(k={self.k}, by={self.by._python()})"

    def __repr__(self) -> str:
        ranking = f"by={self.by!r}" if self.by is not None else f"by_field={self.by_field!r}"
        return f"Rank(k={self.k}, {ranking})"

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False)
class Concat(Reducer):
    """Join every member's original text in author order, with visible boundaries.

    No model is called. With ``label=True`` each part starts with ``[member_i]`` on its own line.
    A Concat Fusion must be followed by another Pipeline stage.
    """

    name: str
    separator: str
    label: bool

    def __init__(self, separator: str = _DEFAULT_SEPARATOR, *, label: bool = True) -> None:
        if not isinstance(separator, str):
            raise TypeError("Concat separator must be a string")
        if not separator:
            raise ValueError("Concat separator must not be empty")
        if len(separator) > _MAX_SEPARATOR_CHARS:
            raise ValueError(f"Concat separator must be at most {_MAX_SEPARATOR_CHARS} characters")
        if not isinstance(label, bool):
            raise TypeError("Concat label must be a bool")
        object.__setattr__(self, "name", "concat")
        object.__setattr__(self, "separator", separator)
        object.__setattr__(self, "label", label)

    def _plan(self) -> _ReducerPlan:
        steps = _Steps(
            reduce=_Step("join", {"separator": self.separator, "label": self.label}),
            select=_Step("all"),
        )
        return _ReducerPlan("concat", "selection", steps)

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Concat:
        reduce = _spec_steps(spec)["reduce"]
        args = {} if reduce is None else reduce[1]
        separator, label = args.get("separator"), args.get("label")
        if not isinstance(separator, str) or not isinstance(label, bool):
            raise _cannot_rebuild("concat")
        concat = _decoded("concat", cls, separator, label=label)
        _require_steps(spec, concat._plan().steps, "concat")
        return concat

    def __repr__(self) -> str:
        return f"Concat(separator={self.separator!r}, label={self.label!r})"

    __hash__: ClassVar[Any] = None


_REDUCER_CLASSES.update(rank=Rank, concat=Concat)

__all__ = ["Concat", "Rank"]
