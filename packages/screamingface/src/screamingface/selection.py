"""sf.Rank and sf.Concat: Fusion synthesizers that hand a selection to the NEXT stage (OME-1289).

A selection is not an answer. ``Rank`` keeps the top k original member texts, ``Concat`` joins every
original member text in author order; neither calls a model to rewrite anything (Rank by a judge
calls the judge model for scores, never for text). The compiler therefore refuses a selection
Fusion that ends a candidate, is a Fusion member, or feeds a corrective loop, and the next
Pipeline stage receives exactly the selection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, cast

from screamingface._signals import JUDGE_SIGNAL, Signal, _Comparison, _comparison
from screamingface.blocks import (
    _MAX_K,
    _MAX_SEPARATOR_CHARS,
    Extract,
    Matches,
    _answer_steps,
    _extract_from_spec,
    _matches_args,
    _normalize_from_spec,
)
from screamingface.judge import (
    JudgeNode,
    judge_from_signals,
)
from screamingface.reducer import (
    _REDUCER_CLASSES,
    Reducer,
    _cannot_rebuild,
    _check_judge_pair,
    _decoded,
    _ModelSignal,
    _op_name,
    _ReducerPlan,
    _refuse_judge_signal,
    _require_steps,
    _spec_steps,
    _Step,
    _Steps,
)

_DEFAULT_SEPARATOR = "\n\n---\n\n"


def _check_rank_source(by: object, by_signal: object) -> None:
    """Refuse a Rank source the Engine would only refuse after the paid member calls."""

    # INVARIANT: the lowering and the url4 rebuild give a scores judge (the sf.Judge step).
    assert by is None or (isinstance(by, JudgeNode) and by.returns == "scores")
    if by_signal is not None and not isinstance(by_signal, Signal):
        raise TypeError("sf.Rank by must be a sf.signal")
    if isinstance(by_signal, Signal):
        _refuse_judge_signal(by_signal, "sf.Rank", "sf.Judge(...) after sf.Fanout")


def _check_rank_order(order: object) -> Literal["max", "min"]:
    if order not in ("max", "min"):
        raise ValueError("sf.Rank order must be 'max' or 'min'")
    return cast("Literal['max', 'min']", order)


@dataclass(frozen=True, slots=True, init=False)
class RankNode(Reducer):
    """Keep the ``k`` best-scored members: the next stage gets their original texts, best first.

    ``by=sf.Judge(..., returns="scores")`` scores every member with a judge model;
    ``by_signal=sf.signal(key)`` reads a named number on each member's Answer (for example
    ``cost_usd``). Give exactly one.
    ``order="max"`` (the default) keeps the highest scores and ``order="min"`` the lowest. A tie at
    the cut goes to the earlier member. A Rank Fusion must be followed by another Pipeline stage.
    """

    name: str
    k: int
    by: JudgeNode | None
    by_signal: Signal | None
    order: Literal["max", "min"]
    _carries_narrow: ClassVar[bool] = True  # the narrow carrier: see Reducer._carries_narrow
    _narrow: tuple[Reducer, ...] = field(default=(), init=False, repr=False)

    def __init__(
        self,
        k: int,
        *,
        by: JudgeNode | None = None,
        by_signal: Signal | None = None,
        order: Literal["max", "min"] = "max",
    ) -> None:
        if isinstance(k, bool) or not isinstance(k, int):
            raise TypeError("sf.Rank k must be an integer")
        if not 1 <= k <= _MAX_K:
            raise ValueError(f"sf.Rank k must be between 1 and {_MAX_K}")
        assert (by is None) != (by_signal is None)  # a judge or a signal, never both
        _check_rank_source(by, by_signal)
        object.__setattr__(self, "name", "rank")
        object.__setattr__(self, "_narrow", ())
        object.__setattr__(self, "k", k)
        object.__setattr__(self, "by", by)
        object.__setattr__(self, "by_signal", by_signal)
        object.__setattr__(self, "order", _check_rank_order(order))

    def _plan(self) -> _ReducerPlan:
        if self.by_signal is not None:
            return _signal_plan(self.k, self.by_signal, self.order)
        # WHY the order only when it is "min": the "max" default keeps the bytes Rank wrote before
        # it had an order.
        select = _Step("top_k", {"k": self.k, **({} if self.order == "max" else {"order": "min"})})
        steps = _Steps(reduce=_Step("scores", {"source": "judge"}), select=select)
        assert self.by is not None  # a Rank holds a judge or a signal
        return _ReducerPlan("rank", "selection", steps, signal_calls=(self.by._signal_call(),))

    def _check_members(self, count: int) -> None:
        if self.k > count:
            raise ValueError(f"sf.Rank keeps k={self.k} members but the sf.Fanout has {count}")

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> RankNode:
        return cls._rebuild(spec, ())

    @classmethod
    def _rebuild(cls, spec: Mapping[str, object], signals: tuple[_ModelSignal, ...]) -> RankNode:
        steps = _spec_steps(spec)
        select = steps["select"]
        args = {} if select is None else select[1]
        k = args.get("k")
        if isinstance(k, bool) or not isinstance(k, int):
            raise _cannot_rebuild("rank")
        source = _recovered_source(steps, signals)
        rank = _decoded("rank", cls, k, order=args.get("order", "max"), **source)
        _require_steps(spec, rank._plan().steps, "rank")
        # WHY: the Fusion refuses a k above its member count, so a recovery must too
        _decoded("rank", rank._check_members, len(cast("Sequence[str]", spec["members"])))
        return rank

    def __repr__(self) -> str:
        if self.by_signal is not None:
            ranking = f"by_signal={self.by_signal!r}"
        else:
            ranking = f"by={self.by!r}"
        order = ", order='min'" if self.order == "min" else ""
        return f"Rank(k={self.k}, {ranking}{order})"

    __hash__: ClassVar[Any] = None


def _signal_plan(k: int, signal: Signal, order: str) -> _ReducerPlan:
    """The plan of a Rank by signal: ``by_signal@1`` scores each member, ``top_k@1`` keeps k.

    INVARIANT (10E F3): the SAME order goes in both steps; the Engine does not cross-check them,
    and the select step's order decides which members are kept.
    """

    steps = _Steps(
        reduce=_Step("by_signal", {"key": signal.key, "order": order}),
        select=_Step("top_k", {"k": k, "order": order}),
    )
    return _ReducerPlan("rank", "selection", steps, reads=signal)


def _recovered_source(
    steps: Mapping[str, tuple[str, Mapping[str, object]] | None],
    signals: tuple[_ModelSignal, ...],
) -> dict[str, object]:
    """The ``by`` or ``by_signal`` keyword a decoded Rank spec holds, else refuse (a rank by a
    JSON field has no step since the map/select/reduce surface: it cannot rebuild)."""

    reduce = steps["reduce"]
    if reduce is not None and _op_name(reduce[0]) == "by_signal":
        key = reduce[1].get("key")
        if not isinstance(key, str):
            raise _cannot_rebuild("rank")
        return {"by_signal": _decoded("rank", Signal, key)}  # an unknown key is a hand edit
    if not signals:
        raise _cannot_rebuild("rank")
    return {"by": judge_from_signals(signals, "scores")}


@dataclass(frozen=True, slots=True, init=False)
class ConcatNode(Reducer):
    """Join every member's original text in author order, with visible boundaries.

    No model is called. With ``label=True`` each part starts with ``[member_i]`` on its own line.
    A Concat Fusion must be followed by another Pipeline stage.
    """

    name: str
    separator: str
    label: bool
    _carries_narrow: ClassVar[bool] = True  # the narrow carrier: see Reducer._carries_narrow
    _narrow: tuple[Reducer, ...] = field(default=(), init=False, repr=False)

    def __init__(self, separator: str = _DEFAULT_SEPARATOR, *, label: bool = True) -> None:
        if not isinstance(separator, str):
            raise TypeError("sf.Concat separator must be a string")
        if not separator:
            raise ValueError("sf.Concat separator must not be empty")
        if len(separator) > _MAX_SEPARATOR_CHARS:
            raise ValueError(
                f"sf.Concat separator must be at most {_MAX_SEPARATOR_CHARS} characters"
            )
        if not isinstance(label, bool):
            raise TypeError("sf.Concat label must be a bool")
        object.__setattr__(self, "name", "concat")
        object.__setattr__(self, "_narrow", ())
        object.__setattr__(self, "separator", separator)
        object.__setattr__(self, "label", label)

    def _plan(self) -> _ReducerPlan:
        steps = _Steps(
            reduce=_Step("join", {"separator": self.separator, "label": self.label}),
            select=_Step("all"),
        )
        return _ReducerPlan("concat", "selection", steps)

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> ConcatNode:
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


def _check_filter_judge(where: Matches | _Comparison, judge: object) -> None:
    """The Filter pairing rule (FJ-E3, FJ-E4), the same rule as Vote's (``_check_judge_pair``):
    a score:judge comparison and a scores judge go together."""

    signal = f"where=sf.signal({JUDGE_SIGNAL!r})"
    _check_judge_pair(
        judge,
        isinstance(where, _Comparison) and where.signal.key == JUDGE_SIGNAL,
        "sf.Filter",
        reader="filter",
        read_by=f"a {signal} comparison",
        unpaired=f"sf.Filter {signal}",
    )


@dataclass(frozen=True, slots=True, init=False)
class FilterNode(Reducer):
    """Keep the members that pass a test: the next stage gets their original texts, in author order.

    ``where=sf.matches(pattern)`` keeps a member whose original text matches the regex.
    ``where=sf.signal(key) >= 0.6`` keeps a member whose named signal passes the comparison
    (``>``, ``>=``, ``<``, ``<=`` or ``==``; there is no ``!=``). ``extract=`` reads each member's
    answer first: a member whose answer cannot be read is dropped. A member with no value for the
    signal is dropped too. A Filter Fusion must be followed by another Pipeline stage. A Filter that
    keeps no member abstains: the next stage gets the input and no member,
    ``{"input": ..., "selected": []}``.

    ``sf.signal("field:x") == True`` also passes a numeric ``1.0``: a signal holds a float, so
    ``True`` means ``1.0`` to the Engine. Compare with ``== 1`` for the number, or keep the bool in
    your JSON and read it through ``sf.Extract`` and ``sf.matches``.

    ``judge=sf.Judge(..., returns="scores")`` goes with
    ``where=sf.signal("score:judge") <op> x`` and never alone: one judge call scores every member,
    and the Filter keeps each member whose score passes. The judge is always told that a higher
    number is better, also for ``<``. A half pair, a label judge or an ``order="min"`` judge raises
    when the Filter is built.
    """

    name: str
    where: Matches | _Comparison
    extract: Extract | None
    judge: JudgeNode | None
    _carries_narrow: ClassVar[bool] = True  # the narrow carrier: see Reducer._carries_narrow
    _narrow: tuple[Reducer, ...] = field(default=(), init=False, repr=False)

    def __init__(
        self,
        *,
        where: Matches | _Comparison,
        extract: Extract | None = None,
        judge: JudgeNode | None = None,
    ) -> None:
        # INVARIANT: sf.Filter and the url4 rebuild give a pattern or a signal comparison.
        assert isinstance(where, Matches | _Comparison)
        if extract is not None and not isinstance(extract, Extract):
            raise TypeError("sf.Filter extract must be a sf.Extract")
        _check_filter_judge(where, judge)
        object.__setattr__(self, "name", "filter")
        object.__setattr__(self, "_narrow", ())
        object.__setattr__(self, "where", where)
        object.__setattr__(self, "extract", extract)
        object.__setattr__(self, "judge", judge)

    def _plan(self) -> _ReducerPlan:
        extract, normalize, benchmark = (
            (None, None, False) if self.extract is None else _answer_steps(self.extract)
        )
        where = self.where
        args = where._args() if isinstance(where, _Comparison) else _matches_args(where)
        steps = _Steps(
            extract=extract,
            normalize=normalize,
            reduce=_Step("filter", args),
            select=_Step("kept"),
        )
        reads = where.signal if isinstance(where, _Comparison) else None
        calls = () if self.judge is None else (self.judge._signal_call(),)
        return _ReducerPlan(
            "filter", "selection", steps, benchmark_rule=benchmark, reads=reads, signal_calls=calls
        )

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> FilterNode:
        return cls._rebuild(spec, ())

    @classmethod
    def _rebuild(cls, spec: Mapping[str, object], signals: tuple[_ModelSignal, ...]) -> FilterNode:
        # A judge call means a judge Filter; judge_from_signals refuses any other call.
        judge = judge_from_signals(signals, "scores") if signals else None
        reduce = _spec_steps(spec)["reduce"]
        where = _decoded("filter", _recovered_where, {} if reduce is None else reduce[1])
        filtered = _decoded(
            "filter", cls, where=where, extract=_recovered_extract(spec), judge=judge
        )
        _require_steps(spec, filtered._plan().steps, "filter")
        return filtered

    def __repr__(self) -> str:
        extract = "" if self.extract is None else f", extract={self.extract._python()}"
        judge = "" if self.judge is None else f", judge={self.judge!r}"
        return f"Filter(where={self.where._python()}{extract}{judge})"

    __hash__: ClassVar[Any] = None


def _recovered_where(args: Mapping[str, object]) -> Matches | _Comparison:
    """The predicate a decoded filter step holds: a regex, or a signal comparison."""

    if "pattern" in args:
        return Matches(cast("str", args["pattern"]), args.get("ignore_case", False))  # type: ignore[arg-type]
    key, cmp, value = args.get("key"), args.get("cmp"), args.get("value")
    if not isinstance(key, str) or not isinstance(cmp, str):
        raise ValueError("a filter step without a predicate")
    return _comparison(Signal(key), cmp, value)


def _recovered_extract(spec: Mapping[str, object]) -> Extract | None:
    """The Extract a decoded filter spec reads its answers with, else refuse."""

    if spec["extract"] is None:
        return None
    try:
        return _extract_from_spec(spec, _normalize_from_spec(spec))
    except (KeyError, TypeError, ValueError):
        raise _cannot_rebuild("filter") from None


_REDUCER_CLASSES.update(rank=RankNode, concat=ConcatNode, filter=FilterNode)

__all__ = ["ConcatNode", "FilterNode", "RankNode"]
