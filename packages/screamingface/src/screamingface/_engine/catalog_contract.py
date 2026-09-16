"""Decode Engine model and Benchmark discovery wire values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NoReturn

from screamingface._benchmark_identity import benchmark_id as _benchmark_id
from screamingface._core.wire import mapping as _wire_mapping
from screamingface._core.wire import text as _wire_text
from screamingface._ui.catalog import _ModelCatalog
from screamingface.discovery import ModelInfo
from screamingface.errors import PlanningError


@dataclass(frozen=True, slots=True)
class _BenchmarkEntry:
    id: str
    title: str
    description: str
    revision: str
    case_count: int
    origin: str


@dataclass(frozen=True, slots=True)
class _BenchmarkCatalogData:
    entries: tuple[_BenchmarkEntry, ...]


@dataclass(frozen=True, slots=True)
class _ModelCatalogData:
    models: Sequence[ModelInfo]


def _decode_model_catalog(payload: object) -> _ModelCatalogData:
    root = _wire_mapping(payload, "model catalogue", _invalid)
    if root.get("object") != "list":
        _invalid("model catalogue object must be 'list'")
    rows = root.get("data")
    if not isinstance(rows, list):
        _invalid("model catalogue must contain a data array")
    values = []
    seen: set[str] = set()
    for row in rows:
        item = _wire_mapping(row, "model catalogue entry", _invalid)
        try:
            model = ModelInfo(
                id=_wire_text(item.get("id"), "Model id", _invalid),
                provider=_wire_text(item.get("owned_by"), "Model provider", _invalid),
                supported_parameters=_string_tuple(
                    item.get("supported_parameters"),
                    "Model supported_parameters",
                ),
                supported_tools=_string_tuple(
                    item.get("supported_tools"),
                    "Model supported_tools",
                ),
            )
        except (TypeError, ValueError) as exc:
            _invalid(str(exc))
        if item.get("object") != "model":
            _invalid("model catalogue entry object must be 'model'")
        if item.get("unsupported_parameter_behavior") != "reject":
            _invalid("Model unsupported_parameter_behavior must be 'reject'")
        _wire_text(
            item.get("parameter_contract_url"),
            "Model parameter_contract_url",
            _invalid,
        )
        if model.id in seen:
            _invalid(f"model catalogue contains duplicate id {model.id!r}")
        seen.add(model.id)
        values.append(model)
    return _ModelCatalogData(models=_ModelCatalog(values))


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        _invalid(f"{label} must be an array")
    selected = tuple(_wire_text(item, label, _invalid) for item in value)
    if len(set(selected)) != len(selected):
        _invalid(f"{label} must not contain duplicates")
    return selected


def _decode_benchmarks(payload: object) -> _BenchmarkCatalogData:
    try:
        return _decode_benchmark_catalog(payload)
    except ValueError as exc:
        _invalid(str(exc))


def _decode_benchmark_catalog(payload: object) -> _BenchmarkCatalogData:
    root = _wire_mapping(payload, "Benchmark catalog", _catalog_invalid)
    if root.get("object") != "list":
        _catalog_invalid("Benchmark catalog object must be 'list'")
    rows = root.get("data")
    if not isinstance(rows, list):
        _catalog_invalid("Benchmark catalog must contain a data array")
    return _BenchmarkCatalogData(entries=_benchmark_entries(rows))


def _benchmark_entries(rows: list[object]) -> tuple[_BenchmarkEntry, ...]:
    values: list[_BenchmarkEntry] = []
    seen: set[str] = set()
    for row in rows:
        item = _wire_mapping(row, "Benchmark catalog entry", _catalog_invalid)
        if item.get("object") != "benchmark":
            _catalog_invalid("Benchmark catalog entry object must be 'benchmark'")
        entry = _benchmark_entry(item)
        if entry.id in seen:
            _catalog_invalid(f"Benchmark catalog contains duplicate id {entry.id!r}")
        seen.add(entry.id)
        values.append(entry)
    return tuple(values)


def _benchmark_entry(item: Mapping[str, object]) -> _BenchmarkEntry:
    case_count = item.get("case_count")
    if isinstance(case_count, bool) or not isinstance(case_count, int) or case_count < 1:
        _catalog_invalid("Benchmark case_count must be a positive integer")
    return _BenchmarkEntry(
        id=_benchmark_id(_wire_text(item.get("id"), "Benchmark id", _catalog_invalid)),
        title=_wire_text(item.get("title"), "Benchmark title", _catalog_invalid),
        description=_wire_text(item.get("description"), "Benchmark description", _catalog_invalid),
        revision=_wire_text(item.get("revision"), "Benchmark revision", _catalog_invalid),
        case_count=case_count,
        origin=_benchmark_origin(item),
    )


def _benchmark_origin(item: Mapping[str, object]) -> str:
    """Carry the Engine's provenance stamp verbatim; older Engines mean our own shelf.

    FEATURE: benchmark provenance tabs (OME-1114).
    INVARIANT: the SDK accepts ANY non-blank origin string — it never validates
    against the Engine's closed set, so an older SDK keeps decoding a newer
    Engine's catalogue when a new origin ships.
    """

    # WHY: an Engine predating OME-1112 emits no origin key; everything it hosts
    # was authored in this repo, so the default states a true fact, not a guess.
    if "origin" not in item:
        return "screamingface"
    return _wire_text(item.get("origin"), "Benchmark origin", _catalog_invalid)


def _catalog_invalid(message: str) -> NoReturn:
    raise ValueError(message)


def _invalid(message: str) -> NoReturn:
    raise PlanningError(
        message,
        code="invalid_catalogue",
        permanent=True,
    )


__all__: list[str] = []
