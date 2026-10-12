"""Validate saved evaluation membership before discovery and grouping."""

from typing import Any

from screamingface.discovery import BenchmarkInfo


def membership_value(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Evaluation membership must be an object")
    report_id = value["id"]
    if (
        not isinstance(report_id, str)
        or not report_id
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for c in report_id
        )
    ):
        raise ValueError("Invalid evaluation id")
    names = value["candidates"]
    if (
        not isinstance(names, (list, tuple))
        or not names
        or any(not isinstance(name, str) or not name.strip() for name in names)
    ):
        raise ValueError("Invalid evaluation candidates")
    if len(set(names)) != len(names):
        raise ValueError("Duplicate evaluation candidates")
    _validate_size(value)
    return value


def _validate_size(value: dict[str, Any]) -> None:
    # WHY: older discovery-only records need not contain decoding context.
    count = value.get("case_count")
    if "case_count" in value and (
        isinstance(count, bool) or not isinstance(count, int) or count < 1
    ):
        raise ValueError("Invalid evaluation case count")
    if "benchmark" in value:
        benchmark = BenchmarkInfo(**value["benchmark"])
        if count is not None and count > benchmark.case_count:
            raise ValueError("Evaluation case count exceeds its benchmark")
