"""Decode Engine model and Benchmark discovery wire values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NoReturn

from screamingface._benchmark_identity import benchmark_id as _benchmark_id
from screamingface._catalogue_vocabulary import INVERTED_GRADE_KEY
from screamingface._core.wire import mapping as _wire_mapping
from screamingface._core.wire import text as _wire_text
from screamingface._ui.catalog import _ModelCatalog
from screamingface.discovery import BenchmarkProvenance, ModelInfo, PublishedScore
from screamingface.errors import PlanningError


@dataclass(frozen=True, slots=True)
class _BenchmarkEntry:
    id: str
    title: str
    description: str
    revision: str
    case_count: int
    origin: str
    interaction: str | None
    difficulty: str | None
    inverted_grade: bool
    provenance: BenchmarkProvenance | None
    saturation: str


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
        interaction=_optional_axis(item, "interaction"),
        difficulty=_optional_axis(item, "difficulty"),
        inverted_grade=_inverted_grade(item),
        provenance=_provenance(item),
        saturation=_saturation(item),
    )


_PROVENANCE_TEXT_KEYS: tuple[str, ...] = (
    "paper_url",
    "authors",
    "citation",
    "homepage_url",
    "harness_url",
    "license",
    "license_note",
    "content_warning",
    "notebook",
)
_PROVENANCE_HANDLE_KEYS: tuple[str, ...] = ("inspect_contributors",)
_PROVENANCE_SCORE_KEYS: tuple[str, ...] = ("human_baseline", "frontier_score")
#: Every provenance key the Engine serves flat on a catalogue entry — the SDK's ONE copy of
#: the list. The local seed twin (`_runtime/bootstrap.py`) reads it from here.
#: INVARIANT: key-for-key the Engine's `PROVENANCE_FIELD_NAMES`; the Engine's conformance
#: test parses the three tuples above and asserts it.
PROVENANCE_KEYS: tuple[str, ...] = (
    _PROVENANCE_TEXT_KEYS + _PROVENANCE_HANDLE_KEYS + _PROVENANCE_SCORE_KEYS
)


def _provenance(item: Mapping[str, object]) -> BenchmarkProvenance | None:
    """The Benchmark Provenance block, cut from the flat keys the Engine serves (OME-1455).

    INVARIANT (the two-axis doctrine): an ABSENT key means "never declared"; a PRESENT key
    must have its shape, or it is a catalogue defect surfaced by name. None, never an empty
    block, when the Engine sent no provenance key at all.
    """

    fields: dict[str, object] = {
        **_provenance_texts(item),
        **_provenance_handles(item),
        **_provenance_scores(item),
    }
    if not fields:
        return None
    try:
        return BenchmarkProvenance(**fields)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        _catalog_invalid(str(exc))


def _provenance_texts(item: Mapping[str, object]) -> dict[str, object]:
    return {
        key: _wire_text(item.get(key), f"Benchmark {key}", _catalog_invalid)
        for key in _PROVENANCE_TEXT_KEYS
        if key in item
    }


def _provenance_handles(item: Mapping[str, object]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key in _PROVENANCE_HANDLE_KEYS:
        if key not in item:
            continue
        handles = item.get(key)
        if not isinstance(handles, list):
            _catalog_invalid(f"Benchmark {key} must be an array of GitHub usernames")
        fields[key] = tuple(
            _wire_text(handle, f"Benchmark {key} entry", _catalog_invalid) for handle in handles
        )
    return fields


def _provenance_scores(item: Mapping[str, object]) -> dict[str, object]:
    return {
        key: _published_score(item.get(key), f"Benchmark {key}")
        for key in _PROVENANCE_SCORE_KEYS
        if key in item
    }


def _published_score(value: object, label: str) -> PublishedScore:
    block = _wire_mapping(value, label, _catalog_invalid)
    score = block.get("score")
    if isinstance(score, bool) or not isinstance(score, int | float):
        _catalog_invalid(f"{label} score must be a number")
    try:
        return PublishedScore(
            score=float(score),
            source_url=_wire_text(block.get("source_url"), f"{label} source_url", _catalog_invalid),
            model=_optional_axis(block, "model"),
            as_of=_optional_axis(block, "as_of"),
        )
    except ValueError as exc:
        _catalog_invalid(f"{label}: {exc}")


def _saturation(item: Mapping[str, object]) -> str:
    """The saturation verdict verbatim; an Engine predating it means no frontier score is
    recorded, which is exactly what "unknown" says. Open set: a new word decodes."""

    if "saturation" not in item:
        return "unknown"
    return _wire_text(item.get("saturation"), "Benchmark saturation", _catalog_invalid)


def _inverted_grade(item: Mapping[str, object]) -> bool:
    """The refusal-rate mark (OME-1400): the Engine publishes it only when true, so absence
    means False. An Engine that serves xstest_unsafe but predates the mark lists it with no
    key, so the Engine change that adds a flipped Benchmark and the one that adds the mark
    ship in one release."""

    value: object = item.get(INVERTED_GRADE_KEY, False)
    if not isinstance(value, bool):
        _catalog_invalid("Benchmark inverted_grade must be a boolean")
    return value


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


def _optional_axis(item: Mapping[str, object], key: str) -> str | None:
    """Carry one grouping axis verbatim; older Engines mean 'never declared'.

    FEATURE: two-axis catalogue grouping (OME-1257).
    INVARIANT: an ABSENT key decodes as None (an Engine predating the axis — unlike
    ``origin`` there is no true-fact default to state), while a PRESENT key must be
    non-blank text: a blank or non-string value is Engine data corruption, surfaced
    as a catalogue defect rather than coerced to None. The SDK never validates the
    value against the Engine's closed set (origin tolerance doctrine, OME-1114).
    """

    if key not in item:
        return None
    return _wire_text(item.get(key), f"Benchmark {key}", _catalog_invalid)


def _catalog_invalid(message: str) -> NoReturn:
    raise ValueError(message)


def _invalid(message: str) -> NoReturn:
    raise PlanningError(
        message,
        code="invalid_catalogue",
        permanent=True,
    )


__all__: list[str] = []
