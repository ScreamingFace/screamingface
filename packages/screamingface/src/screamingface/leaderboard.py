"""Immutable public values returned by Scoreboard leaderboard discovery."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from screamingface._immutable_json import freeze_mapping
from screamingface.url4 import Url4


@dataclass(frozen=True, slots=True)
class LeaderboardInfo:
    """One benchmark registered with the public Scoreboard."""

    id: str
    display_name: str
    description: str | None
    dataset_url: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _text(self.id, "Leaderboard id"))
        object.__setattr__(
            self,
            "display_name",
            _text(self.display_name, "Leaderboard display_name"),
        )
        for name in ("description", "dataset_url"):
            object.__setattr__(
                self, name, _optional_text(getattr(self, name), f"Leaderboard {name}")
            )
        _aware_datetime(self.created_at, "Leaderboard created_at")


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    """One best-per-spec ranked result on a Leaderboard."""

    rank: int
    spec_id: str
    score: float
    total_questions: int
    ran_with_providers: tuple[str, ...]
    submitted_at: datetime
    submitted_by: str | None
    verified_by_screamingface: bool
    url4: Url4
    # Public Scoreboard JSON strips domains; these are immutable display identifiers.
    authors: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        _positive_int(self.rank, "Leaderboard rank")
        object.__setattr__(self, "spec_id", _text(self.spec_id, "Leaderboard spec_id"))
        _score(self.score, "Leaderboard score")
        _positive_int(self.total_questions, "Leaderboard total_questions")
        object.__setattr__(
            self,
            "ran_with_providers",
            _names(self.ran_with_providers, "Leaderboard ran_with_providers"),
        )
        _aware_datetime(self.submitted_at, "Leaderboard submitted_at")
        object.__setattr__(
            self,
            "submitted_by",
            _optional_text(self.submitted_by, "Leaderboard submitted_by"),
        )
        if not isinstance(self.verified_by_screamingface, bool):
            raise TypeError("Leaderboard verified_by_screamingface must be a boolean")
        object.__setattr__(
            self,
            "url4",
            Url4(_text(self.url4, "Leaderboard url4")),
        )
        if self.authors is not None:
            object.__setattr__(
                self,
                "authors",
                _authors(self.authors, "Leaderboard authors"),
            )


@dataclass(frozen=True, slots=True)
class LeaderboardScore:
    """One persisted candidate score returned by the public Scoreboard."""

    id: UUID
    version: int
    benchmark_id: str
    spec_id: str
    url4: Url4
    submitted_by: str | None
    submitted_at: datetime
    score: float
    total_questions: int
    # WHY optional: only binary-graded benchmarks ever had a correctness count —
    # DRACO/HealthBench submissions carry None (OME-866).
    correct_questions: int | None
    ran_with_providers: tuple[str, ...]
    ran_at_local: datetime | None
    client_name: str | None
    client_version: str | None
    client_platform: str | None
    verified_by_screamingface: bool
    metadata: Mapping[str, object] | None
    scoreboard_url: str | None = None
    # Public Scoreboard JSON strips domains; full author emails never enter this read model.
    authors: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("Leaderboard score id must be a UUID")
        _positive_int(self.version, "Leaderboard score version")
        for name in ("benchmark_id", "spec_id"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), f"Leaderboard score {name}"),
            )
        object.__setattr__(
            self,
            "url4",
            Url4(_text(self.url4, "Leaderboard score url4")),
        )
        optional_fields = (
            "submitted_by",
            "client_name",
            "client_version",
            "client_platform",
            "scoreboard_url",
        )
        for name in optional_fields:
            object.__setattr__(
                self,
                name,
                _optional_text(getattr(self, name), f"Leaderboard score {name}"),
            )
        _aware_datetime(self.submitted_at, "Leaderboard score submitted_at")
        _score(self.score, "Leaderboard score score")
        _positive_int(self.total_questions, "Leaderboard score total_questions")
        _optional_correct_questions(self.correct_questions, self.total_questions)
        object.__setattr__(
            self,
            "ran_with_providers",
            _names(self.ran_with_providers, "Leaderboard score ran_with_providers"),
        )
        if self.ran_at_local is not None:
            _aware_datetime(self.ran_at_local, "Leaderboard score ran_at_local")
        if not isinstance(self.verified_by_screamingface, bool):
            raise TypeError("Leaderboard score verified_by_screamingface must be a boolean")
        if self.metadata is not None:
            object.__setattr__(
                self,
                "metadata",
                freeze_mapping(self.metadata, "Leaderboard score metadata"),
            )
        if self.authors is not None:
            object.__setattr__(
                self,
                "authors",
                _authors(self.authors, "Leaderboard score authors"),
            )

    def __repr__(self) -> str:
        # WHY custom: the dataclass auto-repr printed the ENTIRE compiled url4
        # expression (thousands of characters) the moment submit() returned into a
        # notebook cell. The repr is a glanceable summary — the expression stays a
        # field away on .url4, same trade Leaderboard.__repr__ already makes.
        return (
            f"LeaderboardScore({self.benchmark_id!r}, spec_id={self.spec_id!r}, "
            f"score={self.score}, submitted_at={self.submitted_at.isoformat()}, "
            f"id={str(self.id)!r})"
        )

    def _repr_html_(self) -> str:
        from screamingface._ui.score_view import leaderboard_score_html

        return leaderboard_score_html(self)


@dataclass(frozen=True, slots=True)
class LeaderboardBaseline:
    """One imported single-Model baseline shown alongside community entries."""

    id: UUID
    benchmark_id: str
    model_name: str
    score: float
    source: str
    source_url: str | None
    imported_at: datetime
    metadata: Mapping[str, object] | None

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("Leaderboard baseline id must be a UUID")
        for name in ("benchmark_id", "model_name", "source"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), f"Leaderboard baseline {name}"),
            )
        _score(self.score, "Leaderboard baseline score")
        if self.source_url is not None:
            selected = _text(self.source_url, "Leaderboard baseline source_url")
            parts = urlsplit(selected)
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                raise ValueError("Leaderboard baseline source_url must be HTTP(S)")
            object.__setattr__(self, "source_url", selected)
        _aware_datetime(self.imported_at, "Leaderboard baseline imported_at")
        if self.metadata is not None:
            object.__setattr__(
                self,
                "metadata",
                freeze_mapping(self.metadata, "Leaderboard baseline metadata"),
            )


@dataclass(frozen=True, slots=True)
class Leaderboard:
    """One benchmark's ranked entries and imported baselines."""

    benchmark: LeaderboardInfo
    entries: tuple[LeaderboardEntry, ...]
    baselines: tuple[LeaderboardBaseline, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.benchmark, LeaderboardInfo):
            raise TypeError("Leaderboard benchmark must be LeaderboardInfo")
        entries = _instances(self.entries, LeaderboardEntry, "Leaderboard entries")
        baselines = _instances(self.baselines, LeaderboardBaseline, "Leaderboard baselines")
        if tuple(entry.rank for entry in entries) != tuple(range(1, len(entries) + 1)):
            raise ValueError("Leaderboard entry ranks must be consecutive from 1")
        if any(baseline.benchmark_id != self.benchmark.id for baseline in baselines):
            raise ValueError("Leaderboard baseline benchmark_id must match its Leaderboard")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "baselines", baselines)

    def __repr__(self) -> str:
        return (
            f"Leaderboard({self.benchmark.id!r}, entries={len(self.entries)}, "
            f"baselines={len(self.baselines)})"
        )

    def _repr_html_(self) -> str:
        from screamingface._ui.leaderboard_view import leaderboard_html

        return leaderboard_html(self)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not value.strip():
        raise ValueError(f"{label} must be non-empty")
    return value.strip()


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _positive_int(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")


def _nonnegative_int(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")


def _optional_correct_questions(correct: int | None, total: int) -> None:
    if correct is None:
        return
    _nonnegative_int(correct, "Leaderboard score correct_questions")
    if correct > total:
        raise ValueError("Leaderboard score correct_questions cannot exceed total_questions")


def _score(value: object, label: str) -> None:
    # INVARIANT (OME-866): benchmark-native — any finite number, higher is better
    # within a benchmark. There is no universal 0..1 range (DRACO is fractional,
    # HealthBench worst-30 is negative); finiteness is the only universal bound.
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")


def _aware_datetime(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _names(values: object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError(f"{label} must be a sequence")
    selected = tuple(_text(value, label) for value in values)
    if len(set(selected)) != len(selected):
        raise ValueError(f"{label} must not contain duplicates")
    return selected


def _authors(values: object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError(f"{label} must be a sequence")
    selected = tuple(_text(value, label) for value in values)
    if not selected:
        raise ValueError(f"{label} must not be empty")
    if len(selected) > 10:
        raise ValueError(f"{label} must contain at most 10 values")
    # INVARIANT (OME-1053): authorship is an ordered credit line. Unlike provider names,
    # duplicates are preserved because the client must not rewrite the Scoreboard's public value.
    return selected


def _instances[T](values: object, kind: type[T], label: str) -> tuple[T, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError(f"{label} must be a sequence")
    selected = tuple(values)
    if any(not isinstance(value, kind) for value in selected):
        raise TypeError(f"{label} contain an invalid value")
    return selected


__all__ = [
    "Leaderboard",
    "LeaderboardBaseline",
    "LeaderboardEntry",
    "LeaderboardInfo",
    "LeaderboardScore",
]
