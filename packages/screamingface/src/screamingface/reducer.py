"""Deterministic Fusion synthesizers: pure rules compiled to one combine call (OME-1289)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from screamingface._immutable_json import freeze_mapping

type _ReducerKind = Literal["answer", "selection", "projection"]
type _ReducerName = Literal["vote", "median", "judge", "pick", "merge", "project", "rank", "concat"]
REDUCER_NAMES: frozenset[str] = frozenset(
    {"vote", "median", "judge", "pick", "merge", "project", "rank", "concat"}
)


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


class Reducer(ABC):
    """Non-constructible umbrella type for deterministic Fusion synthesizers.

    A reducer is not a Recipe: it is valid only as ``sf.Fusion(..., synthesizer=<reducer>)``.
    """

    name: str

    @property
    @abstractmethod
    def _reducer(self) -> _ReducerName:
        """The spec ``reducer`` value."""

    @property
    @abstractmethod
    def _kind(self) -> _ReducerKind:
        """answer | selection | projection (read by the later selection compile checks)."""

    @abstractmethod
    def _steps(self) -> _Steps:
        """Unpinned operator steps; the compiler pins them against the Engine catalog."""

    @classmethod
    @abstractmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Reducer:
        """Rebuild an equal reducer (pinned ids) from a decoded combine spec."""

    def _weights(self) -> tuple[float, ...] | None:
        return None

    def _check_members(self, count: int) -> None:
        """Raise ValueError when this reducer cannot serve ``count`` members (Fusion build time)."""
        return None


# Concrete reducers register here (later units: {"vote": Vote, "median": Median}, ...).
_REDUCER_CLASSES: dict[str, type[Reducer]] = {}


def _reducer_class(name: str) -> type[Reducer]:
    selected = _REDUCER_CLASSES.get(name)
    if selected is None:
        raise ValueError(
            f"URL4 Candidate uses the {name!r} reducer, which this SDK version cannot rebuild"
        )
    return selected


__all__ = ["Reducer"]
