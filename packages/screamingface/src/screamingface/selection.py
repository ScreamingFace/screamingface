"""sf.Rank and sf.Concat: Fusion synthesizers that hand a selection to the NEXT stage (OME-1289).

A selection is not an answer. ``Rank`` keeps the top k original member texts, ``Concat`` joins every
original member text in author order; neither calls a model to rewrite anything (Rank by a judge
calls the judge model for scores, never for text). The compiler therefore refuses a selection
Fusion that ends a candidate, is a Fusion member, or feeds a corrective loop, and the next
Pipeline stage receives exactly the selection.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, cast

from screamingface._signals import Signal, _Comparison, _comparison
from screamingface.blocks import (
    _BLOCK_FORMS,
    _MAX_K,
    _MAX_SEPARATOR_CHARS,
    Extract,
    Matches,
    _answer_steps,
    _BlockForm,
    _extract_from_spec,
    _matches_args,
    _normalize_from_spec,
)
from screamingface.judge import Judge, judge_from_signals
from screamingface.reducer import (
    _REDUCER_CLASSES,
    Reducer,
    _as_python,
    _cannot_rebuild,
    _decoded,
    _field_path,
    _ModelSignal,
    _op_name,
    _ReducerPlan,
    _refuse_judge_signal,
    _refuse_min_order_judge,
    _require_steps,
    _spec_steps,
    _Step,
    _Steps,
)

_DEFAULT_SEPARATOR = "\n\n---\n\n"
# WHY the exact id: scores@1 assumes the v1 output form of the numeric normalizer, so a later
# numeric@2 must not change what a Rank by field means.
_RANK_NORMALIZER = "numeric@1"


def _check_rank_source(by: object, by_field: object, by_signal: object) -> None:
    """Refuse a Rank source the Engine would only refuse after the paid member calls."""

    if by is not None and not isinstance(by, Judge):
        raise TypeError("Rank by must be an sf.Judge")
    if by is not None and by.returns != "scores":
        raise ValueError("Rank(by=...) needs sf.Judge(..., returns='scores')")
    if by is not None:
        _refuse_min_order_judge(by, "Rank")
    if by_field is not None:
        _field_path(by_field, "Rank by_field")
    if by_signal is not None and not isinstance(by_signal, Signal):
        raise TypeError("Rank by_signal must be an sf.signal")
    if isinstance(by_signal, Signal):
        _refuse_judge_signal(by_signal, "Rank", "sf.Rank(k, by=sf.Judge(..., returns='scores'))")


def _check_rank_order(order: object) -> Literal["max", "min"]:
    if order not in ("max", "min"):
        raise ValueError("Rank order must be 'max' or 'min'")
    return cast("Literal['max', 'min']", order)


@dataclass(frozen=True, slots=True, init=False)
class Rank(Reducer):
    """Keep the ``k`` best-scored members: the next stage gets their original texts, best first.

    ``by=sf.Judge(..., returns="scores")`` scores every member with a judge model;
    ``by_field="score"`` reads a number from each member's JSON reply; ``by_signal=sf.signal(key)``
    reads a named number on each member's Answer (for example ``cost_usd``). Give exactly one.
    ``order="max"`` (the default) keeps the highest scores and ``order="min"`` the lowest. A tie at
    the cut goes to the earlier member. A Rank Fusion must be followed by another Pipeline stage.
    """

    name: str
    k: int
    by: Judge | None
    by_field: str | None
    by_signal: Signal | None
    order: Literal["max", "min"]

    def __init__(
        self,
        k: int,
        *,
        by: Judge | None = None,
        by_field: str | None = None,
        by_signal: Signal | None = None,
        order: Literal["max", "min"] = "max",
    ) -> None:
        if isinstance(k, bool) or not isinstance(k, int):
            raise TypeError("Rank k must be an integer")
        if not 1 <= k <= _MAX_K:
            raise ValueError(f"Rank k must be between 1 and {_MAX_K}")
        if sum(source is not None for source in (by, by_field, by_signal)) != 1:
            raise ValueError("Rank needs exactly one of by=, by_field= or by_signal=")
        _check_rank_source(by, by_field, by_signal)
        object.__setattr__(self, "name", "rank")
        object.__setattr__(self, "k", k)
        object.__setattr__(self, "by", by)
        object.__setattr__(self, "by_field", by_field)
        object.__setattr__(self, "by_signal", by_signal)
        object.__setattr__(self, "order", _check_rank_order(order))

    def _plan(self) -> _ReducerPlan:
        if self.by_signal is not None:
            return _signal_plan(self.k, self.by_signal, self.order)
        # WHY the order only when it is "min": the "max" default keeps the bytes Rank wrote before
        # it had an order.
        select = _Step("top_k", {"k": self.k, **({} if self.order == "max" else {"order": "min"})})
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

    def _python(self) -> str:
        return self._render("sf.Rank", _as_python)

    def __repr__(self) -> str:
        return self._render("Rank", repr)

    def _render(self, head: str, show: Callable[[object], str]) -> str:
        if self.by_signal is not None:
            ranking = f"by_signal={show(self.by_signal)}"
        elif self.by is not None:
            ranking = f"by={show(self.by)}"
        else:
            ranking = f"by_field={show(self.by_field)}"
        order = ", order='min'" if self.order == "min" else ""
        return f"{head}(k={self.k}, {ranking}{order})"

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
    """The ``by``, ``by_field`` or ``by_signal`` keyword a decoded Rank spec holds, else refuse."""

    reduce, extract = steps["reduce"], steps["extract"]
    if reduce is not None and _op_name(reduce[0]) == "by_signal":
        key = reduce[1].get("key")
        if not isinstance(key, str):
            raise _cannot_rebuild("rank")
        return {"by_signal": _decoded("rank", Signal, key)}  # an unknown key is a hand edit
    if signals:
        return {"by": judge_from_signals(signals, "scores")}
    path = None if extract is None else extract[1].get("path")
    if not isinstance(path, str):
        raise _cannot_rebuild("rank")
    return {"by_field": path}


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


def _top_k_from_options(options: Mapping[str, object]) -> Rank:
    return Rank(
        cast("int", options["k"]),
        by=cast("Judge | None", options.get("by")),
        by_field=cast("str | None", options.get("by_field")),
        by_signal=cast("Signal | None", options.get("by_signal")),
        order=cast("Literal['max', 'min']", options.get("order", "max")),
    )


def _top_k_options(named: Reducer) -> Mapping[str, object]:
    """The canonical options of a top_k block, in op-table row order: the default order ``max``
    is not stored."""

    rank = cast("Rank", named)
    source = {
        name: getattr(rank, name) for name in _RANK_SOURCES if getattr(rank, name) is not None
    }
    return {"k": rank.k, **source, **({"order": "min"} if rank.order == "min" else {})}


def _check_filter_where(where: object) -> None:
    if not isinstance(where, Matches | _Comparison):
        raise TypeError(
            "Filter where must be sf.matches(...) or a signal comparison like sf.signal(key) >= 0.6"
        )
    if isinstance(where, _Comparison):
        _refuse_judge_signal(
            where.signal,
            "Filter",
            "sf.Rank(k, by=sf.Judge(..., returns='scores')), which keeps the k best-judged members",
        )


@dataclass(frozen=True, slots=True, init=False)
class Filter(Reducer):
    """Keep the members that pass a test: the next stage gets their original texts, in author order.

    ``where=sf.matches(pattern)`` keeps a member whose original text matches the regex.
    ``where=sf.signal(key) >= 0.6`` keeps a member whose named signal passes the comparison
    (``>``, ``>=``, ``<``, ``<=`` or ``==``; there is no ``!=``). ``extract=`` reads each member's
    answer first: a member whose answer cannot be read is dropped. A member with no value for the
    signal is dropped too. A Filter Fusion must be followed by another Pipeline stage. A Filter that
    keeps no member abstains: the next stage gets an empty text.

    ``sf.signal("field:x") == True`` also passes a numeric ``1.0``: a signal holds a float, so
    ``True`` means ``1.0`` to the Engine. Compare with ``== 1`` for the number, or keep the bool in
    your JSON and read it through ``sf.Extract`` and ``sf.matches``.
    """

    name: str
    where: Matches | _Comparison
    extract: Extract | None
    judge: Judge | None

    def __init__(
        self,
        *,
        where: Matches | _Comparison,
        extract: Extract | None = None,
        judge: Judge | None = None,
    ) -> None:
        _check_filter_where(where)
        if extract is not None and not isinstance(extract, Extract):
            raise TypeError("Filter extract must be an sf.Extract")
        object.__setattr__(self, "name", "filter")
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
        return _ReducerPlan("filter", "selection", steps, benchmark_rule=benchmark, reads=reads)

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Filter:
        reduce = _spec_steps(spec)["reduce"]
        where = _decoded("filter", _recovered_where, {} if reduce is None else reduce[1])
        filtered = _decoded("filter", cls, where=where, extract=_recovered_extract(spec))
        _require_steps(spec, filtered._plan().steps, "filter")
        return filtered

    def _python(self) -> str:
        return self._render("sf.Filter")

    def __repr__(self) -> str:
        return self._render("Filter")

    def _render(self, head: str) -> str:
        extract = "" if self.extract is None else f", extract={self.extract._python()}"
        return f"{head}(where={self.where._python()}{extract})"

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


def _filter_from_options(options: Mapping[str, object]) -> Filter:
    return Filter(
        where=cast("Matches | _Comparison", options["where"]),
        extract=cast("Extract | None", options.get("extract")),
    )


def _filter_options(named: Reducer) -> Mapping[str, object]:
    filtered = cast("Filter", named)
    return {
        "where": filtered.where,
        **({} if filtered.extract is None else {"extract": filtered.extract}),
    }


def _concat_from_options(options: Mapping[str, object]) -> Concat:
    return Concat(
        cast("str", options.get("separator", _DEFAULT_SEPARATOR)),
        label=cast("bool", options.get("label", True)),
    )


def _concat_options(named: Reducer) -> Mapping[str, object]:
    """The canonical options of a concat block: the defaults are not stored."""

    concat = cast("Concat", named)
    separator = {} if concat.separator == _DEFAULT_SEPARATOR else {"separator": concat.separator}
    return {**separator, **({} if concat.label else {"label": False})}


_RANK_SOURCES = ("by", "by_field", "by_signal")
_REDUCER_CLASSES.update(rank=Rank, concat=Concat, filter=Filter)
_BLOCK_FORMS["top_k"] = _BlockForm(build=_top_k_from_options, options=_top_k_options)
_BLOCK_FORMS["concat"] = _BlockForm(build=_concat_from_options, options=_concat_options)
_BLOCK_FORMS["filter"] = _BlockForm(build=_filter_from_options, options=_filter_options)

__all__ = ["Concat", "Filter", "Rank"]
