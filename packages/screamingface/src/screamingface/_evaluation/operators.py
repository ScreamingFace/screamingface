"""The Engine's combine-operator catalog: domain type, pinning, and wire decoder (OME-1289)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, NoReturn, cast

from screamingface._core.wire import mapping as _wire_mapping
from screamingface.errors import PlanningError

type Stage = Literal["extract", "normalize", "reduce", "select"]
STAGES: tuple[Stage, ...] = ("extract", "normalize", "reduce", "select")
_NAME = re.compile(r"[a-z][a-z0-9_]*")
_ID = re.compile(r"([a-z][a-z0-9_]*)@([1-9][0-9]*)")
_LABEL = "SF Engine operator catalog"


@dataclass(frozen=True, slots=True)
class _OperatorEntry:
    id: str
    name: str
    version: int
    stage: Stage


@dataclass(frozen=True, slots=True)
class _OperatorCatalog:
    """The Engine's operators, used to pin short names to exact ``name@version`` ids."""

    entries: tuple[_OperatorEntry, ...]

    def pin(self, stage: Stage, value: str) -> str:
        """Return the pinned id for ``value`` in ``stage`` or raise a ValueError naming the fix."""

        if _ID.fullmatch(value) is not None:
            return self._pin_id(stage, value)
        if _NAME.fullmatch(value) is not None:
            return self._pin_name(stage, value)
        raise ValueError(
            f"{stage} operator {value!r} must be a name like 'last_number' "
            "or a pinned id like 'last_number@1'"
        )

    def _pin_id(self, stage: Stage, value: str) -> str:
        entry = next((item for item in self.entries if item.id == value), None)
        if entry is None:
            raise ValueError(
                f"{stage} operator {value!r} is not in this SF Engine's operator catalog; "
                f"known {stage} operator ids: {self._known(stage, 'id')}"
            )
        if entry.stage != stage:
            raise ValueError(
                f"operator {value!r} is a {entry.stage} operator, not a {stage} operator"
            )
        return value

    def _pin_name(self, stage: Stage, value: str) -> str:
        matches = [item for item in self.entries if item.stage == stage and item.name == value]
        if not matches:
            raise ValueError(
                f"unknown {stage} operator {value!r}; "
                f"known {stage} operators: {self._known(stage, 'name')}"
            )
        return max(matches, key=lambda item: item.version).id

    def _known(self, stage: Stage, attribute: Literal["id", "name"]) -> str:
        values = sorted({getattr(item, attribute) for item in self.entries if item.stage == stage})
        return ", ".join(values) if values else f"this SF Engine has no {stage} operators"

    @classmethod
    def from_pinned(cls, pairs: Iterable[tuple[Stage, str]]) -> _OperatorCatalog:
        """Build the catalog a url4's own pinned ids describe (url4 recovery recompiles)."""

        entries: dict[tuple[Stage, str], _OperatorEntry] = {}
        for stage, value in pairs:
            match = _ID.fullmatch(value)
            if match is None:
                raise ValueError(f"{stage} operator {value!r} is not a pinned id")
            entries.setdefault(
                (stage, value),
                _OperatorEntry(
                    id=value, name=match.group(1), version=int(match.group(2)), stage=stage
                ),
            )
        return cls(entries=tuple(entries.values()))


def is_pinned_operator_id(value: str) -> bool:
    """Whether ``value`` is a pinned ``name@version`` operator id."""

    return _ID.fullmatch(value) is not None


def decode_operator_catalog(payload: object) -> _OperatorCatalog:
    """Decode ``GET /v1/operators``; extra keys are ignored, malformed content refuses."""

    root = _wire_mapping(payload, _LABEL, _invalid)
    rows = root.get("data")
    if root.get("object") != "list" or not isinstance(rows, list):
        _invalid(f"{_LABEL} must be an object list with a data array")
    entries: list[_OperatorEntry] = []
    seen: set[str] = set()
    for row in cast(list[object], rows):
        entry = _entry(_wire_mapping(row, f"{_LABEL} entry", _invalid))
        if entry.id in seen:
            _invalid(f"{_LABEL} contains duplicate id {entry.id!r}")
        seen.add(entry.id)
        entries.append(entry)
    return _OperatorCatalog(entries=tuple(entries))


def _entry(item: Mapping[str, object]) -> _OperatorEntry:
    name = item.get("name")
    version = item.get("version")
    stage = item.get("stage")
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        _invalid(f"{_LABEL} entry name must match {_NAME.pattern}")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        _invalid(f"{_LABEL} entry version must be a positive integer")
    if stage not in STAGES:
        _invalid(f"{_LABEL} entry stage must be one of {', '.join(STAGES)}")
    if item.get("id") != f"{name}@{version}":
        _invalid(f"{_LABEL} entry id must be name@version")
    if not isinstance(item.get("args_schema"), Mapping):
        _invalid(f"{_LABEL} entry args_schema must be an object")
    summary = item.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        _invalid(f"{_LABEL} entry summary must be non-blank text")
    return _OperatorEntry(
        id=f"{name}@{version}", name=name, version=version, stage=cast(Stage, stage)
    )


def _invalid(message: str) -> NoReturn:
    raise PlanningError(message, code="invalid_catalogue", permanent=True)


__all__: list[str] = []
