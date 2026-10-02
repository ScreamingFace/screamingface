"""Deterministic Fusion synthesizers: pure rules compiled to one combine call (OME-1289)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, get_args

from screamingface._evaluation.operators import STAGES
from screamingface._immutable_json import freeze_mapping

type _ReducerKind = Literal["answer", "selection", "projection"]
type _ReducerName = Literal["vote", "median", "judge", "pick", "merge", "project", "rank", "concat"]
# One source for each vocabulary: the Literal above is the list, the sets are derived from it.
REDUCER_NAMES: frozenset[str] = frozenset(get_args(_ReducerName.__value__))
REDUCER_KINDS: frozenset[str] = frozenset(get_args(_ReducerKind.__value__))


@dataclass(frozen=True, slots=True, init=False)
class _Step:
    """One operator use: a short name ('last_number') or a pinned id ('last_number@1')."""

    op: str
    args: Mapping[str, object]

    def __init__(self, op: str, args: Mapping[str, object] | None = None) -> None:
        if not isinstance(op, str) or not op.strip():
            raise TypeError("a reducer operator must be a non-empty string")
        object.__setattr__(self, "op", op)
        object.__setattr__(
            self, "args", freeze_mapping({} if args is None else args, f"operator {op!r} args")
        )


@dataclass(frozen=True, slots=True)
class _Steps:
    reduce: _Step
    select: _Step
    extract: _Step | None = None
    normalize: _Step | None = None


@dataclass(frozen=True, slots=True)
class _ReducerPlan:
    """What a reducer compiles to: the combine spec minus its member list, with unpinned ops.

    SEAM (OME-1289 gap, block-api delta 1): sf.Reduce builds one now; the named reducers (unit 5+)
    build one too, so a block and its named form compile to the same bytes.
    """

    reducer: _ReducerName
    kind: _ReducerKind
    steps: _Steps
    weights: tuple[float, ...] | None = None


class Reducer(ABC):
    """Non-constructible umbrella type for deterministic Fusion synthesizers.

    A reducer is not a Recipe: it is valid only as ``sf.Fusion(..., synthesizer=<reducer>)``.
    """

    name: str

    @abstractmethod
    def _plan(self) -> _ReducerPlan:
        """The reducer name, kind (answer | selection | projection), unpinned operator steps and
        weights; the compiler pins the steps against the Engine catalog."""

    @classmethod
    @abstractmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Reducer:
        """Rebuild an equal reducer (pinned ids) from a decoded combine spec."""

    def _python(self) -> str:
        """The ``sf.`` source that rebuilds this reducer (read by ``Url4.to_python``)."""
        return f"sf.{self!r}"

    def _check_members(self, count: int) -> None:
        """Raise ValueError when this reducer cannot serve ``count`` members (Fusion build time)."""
        return None


# Concrete reducers register here (later units add more names beside vote and median).
_REDUCER_CLASSES: dict[str, type[Reducer]] = {}


_MEDIAN_SELECTS: frozenset[str] = frozenset({"nearest", "value"})


def _op_name(op: str | None) -> str | None:
    return None if op is None else op.split("@", 1)[0]


def _cannot_rebuild(name: str) -> ValueError:
    return ValueError(f"URL4 Candidate has a {name} spec this SDK version cannot rebuild")


def _spec_ops(spec: Mapping[str, object], name: str) -> dict[str, str | None]:
    """stage -> pinned op id (None for an absent step). Refuses step args: v1 takes none."""

    ops: dict[str, str | None] = {}
    for stage in STAGES:
        step = spec[stage]
        if step is None:
            ops[stage] = None
            continue
        assert isinstance(step, Mapping)
        if step["args"]:
            raise _cannot_rebuild(name)
        ops[stage] = str(step["op"])
    return ops


@dataclass(frozen=True, slots=True, init=False)
class Vote(Reducer):
    """Plurality vote: the first member (author order) holding the most common answer, verbatim."""

    name: str
    extract: str
    normalize: str | None

    def __init__(self, *, extract: str = "last_line", normalize: str | None = "text") -> None:
        _Step(extract)  # TypeError for a non-str or blank name
        if normalize is not None:
            _Step(normalize)
        object.__setattr__(self, "name", "vote")
        object.__setattr__(self, "extract", extract)
        object.__setattr__(self, "normalize", normalize)

    def _plan(self) -> _ReducerPlan:
        steps = _Steps(
            reduce=_Step("mode"),
            select=_Step("first_holder"),
            extract=_Step(self.extract),
            normalize=None if self.normalize is None else _Step(self.normalize),
        )
        return _ReducerPlan("vote", "answer", steps)

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Vote:
        ops = _spec_ops(spec, "vote")
        extract = ops["extract"]
        if (
            extract is None
            or _op_name(ops["reduce"]) != "mode"
            or _op_name(ops["select"]) != "first_holder"
            or spec["weights"] is not None
        ):
            raise _cannot_rebuild("vote")
        return cls(extract=extract, normalize=ops["normalize"])

    def __repr__(self) -> str:
        return f"Vote(extract={self.extract!r}, normalize={self.normalize!r})"

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False)
class Median(Reducer):
    """Median of the members' numeric answers: the nearest member's text, or the number itself."""

    name: str
    extract: str
    select: str

    def __init__(self, *, extract: str = "last_number", select: str = "nearest") -> None:
        _Step(extract)
        _Step(select)
        if _op_name(select) not in _MEDIAN_SELECTS:
            raise ValueError(f"Median select must be 'nearest' or 'value', not {select!r}")
        object.__setattr__(self, "name", "median")
        object.__setattr__(self, "extract", extract)
        object.__setattr__(self, "select", select)

    def _plan(self) -> _ReducerPlan:
        steps = _Steps(
            reduce=_Step("median"),
            select=_Step(self.select),
            extract=_Step(self.extract),
            normalize=_Step("numeric"),
        )
        return _ReducerPlan("median", "answer", steps)

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Median:
        ops = _spec_ops(spec, "median")
        extract = ops["extract"]
        select = ops["select"]
        if (
            extract is None
            or select is None
            or _op_name(ops["normalize"]) != "numeric"
            or _op_name(ops["reduce"]) != "median"
            or _op_name(select) not in _MEDIAN_SELECTS
            or spec["weights"] is not None
        ):
            raise _cannot_rebuild("median")
        return cls(extract=extract, select=select)

    def __repr__(self) -> str:
        return f"Median(extract={self.extract!r}, select={self.select!r})"

    __hash__: ClassVar[Any] = None


_REDUCER_CLASSES.update(vote=Vote, median=Median)

__all__ = ["Median", "Reducer", "Vote"]
