"""Decode one flat Engine-owned Benchmark expression resource."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NoReturn, cast

from screamingface._core.wire import mapping as _wire_mapping
from screamingface._core.wire import text as _wire_text
from screamingface._evaluation.model import _canonical_url4
from screamingface.discovery import BenchmarkInfo
from screamingface.errors import PlanningError

_BENCHMARK_SCHEMA = "screamingface.benchmark.v1"
_CHECK_COSTS = frozenset({"free", "paid"})
type _CheckCost = Literal["free", "paid"]


@dataclass(frozen=True, slots=True)
class _CheckSurface:
    """One benchmark's advertised mid-run checking capability (OME-796).

    A loop recipe compiles ``check_route`` into its check steps; an ABSENT
    surface means the benchmark cannot check mid-run and the runner's preflight
    refuses a loop recipe before any money moves.
    """

    check_route: str
    feedback_intent: str
    expected_check_cost: _CheckCost


@dataclass(frozen=True, slots=True)
class _BenchmarkResource:
    info: BenchmarkInfo
    case_count: int
    url4: str
    check_surface: _CheckSurface | None = None


def _decode_benchmark_resource(
    decoded: object,
    *,
    requested_id: str,
    requested_limit: int | None,
) -> _BenchmarkResource:
    """Validate the one executable resource selected by its complete Benchmark id."""

    resource = _wire_mapping(decoded, "Benchmark resource", _invalid)
    if resource.get("schema") != _BENCHMARK_SCHEMA:
        _invalid(f"Benchmark resource schema must be {_BENCHMARK_SCHEMA!r}")
    benchmark_id = _wire_text(resource.get("id"), "Benchmark id", _invalid)
    if benchmark_id != requested_id:
        _invalid("Benchmark resource has the wrong Benchmark id")
    for field in ("title", "description"):
        _wire_text(resource.get(field), f"Benchmark {field}", _invalid)
    installed_case_count = _positive(resource.get("case_count"), "case_count")
    try:
        url4 = _canonical_url4(resource.get("url4"), "Benchmark")
        info = BenchmarkInfo(
            id=benchmark_id,
            revision=_wire_text(resource.get("revision"), "Benchmark revision", _invalid),
            case_count=installed_case_count,
            # WHY absent means False: the Engine publishes the mark only when true. An Engine
            # without the mark (before OME-1400's second PR) sends no key for ANY Benchmark —
            # including xstest_unsafe if the first PR's Engine is deployed alone — so the two
            # Engine changes deploy together.
            inverted_grade=_inverted_grade(resource.get("inverted_grade", False)),
        )
    except (TypeError, ValueError) as exc:
        _invalid(str(exc))

    return _BenchmarkResource(
        info=info,
        case_count=(
            installed_case_count
            if requested_limit is None
            else min(requested_limit, installed_case_count)
        ),
        url4=url4,
        check_surface=_check_surface(resource.get("check_surface")),
    )


def _inverted_grade(value: object) -> bool:
    """The Benchmark-level refusal-rate mark, refused unless it is a real boolean."""

    if not isinstance(value, bool):
        _invalid("Benchmark inverted_grade must be a boolean")
    return value


def _check_surface(value: object) -> _CheckSurface | None:
    """Decode the optional check-surface block; absent = no mid-run checking."""

    if value is None:
        return None
    block = _wire_mapping(value, "Benchmark check_surface", _invalid)
    if set(block) != {"check_route", "feedback_intent", "expected_check_cost"}:
        _invalid(
            "Benchmark check_surface must carry exactly check_route, feedback_intent, "
            "and expected_check_cost"
        )
    check_route = _wire_text(block.get("check_route"), "Benchmark check_route", _invalid)
    if not check_route.startswith("/"):
        _invalid("Benchmark check_route must be an absolute route path")
    feedback_intent = _wire_text(
        block.get("feedback_intent"), "Benchmark feedback_intent", _invalid
    )
    cost = block.get("expected_check_cost")
    if cost not in _CHECK_COSTS:
        _invalid("Benchmark expected_check_cost must be 'free' or 'paid'")
    assert isinstance(cost, str)
    return _CheckSurface(
        check_route=check_route,
        feedback_intent=feedback_intent,
        expected_check_cost=cast(_CheckCost, cost),
    )


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _invalid(f"Benchmark resource {label} must be a positive integer")
    return cast(int, value)


def _invalid(message: str) -> NoReturn:
    raise PlanningError(
        message,
        code="invalid_benchmark_resource",
        permanent=True,
    )


__all__: list[str] = []
