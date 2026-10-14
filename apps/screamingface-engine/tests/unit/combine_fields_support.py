"""Spec builders for the pick and merge tests (OME-1289 E4a, unit 9).

Test-only. One place for the real-operator specs that ``test_combine_fields``,
``combine_fields_scenarios`` and ``test_combine_writer_world`` share; the generic spec, context and
run builders stay in ``combine_support`` and are never copied.
"""

from __future__ import annotations

from typing import Any

from combine_support import vote_spec


def step(op_id: str, **args: Any) -> dict[str, Any]:
    """One spec step: a pinned operator id and its args."""
    return {"op": op_id, "args": args}


def pick_spec(
    count: int,
    select: dict[str, Any],
    *,
    normalize: str | None = "numeric@1",
    path: str = "confidence",
) -> dict[str, Any]:
    """A pick over the JSON field ``path`` of each member."""
    return vote_spec(
        count,
        reducer="pick",
        extract=step("json_field@1", path=path),
        normalize=None if normalize is None else step(normalize),
        reduce=step("values@1", field=path),
        select=select,
    )


def merge_spec(
    count: int, rules: list[dict[str, Any]], *, extract: str = "json_object@1"
) -> dict[str, Any]:
    """A merge whose ``field_rules@1`` step holds ``rules``."""
    return vote_spec(
        count,
        reducer="merge",
        extract=step(extract),
        normalize=None,
        reduce=step("field_rules@1", fields=rules),
        select=step("built@1"),
    )


def project_spec(count: int, field: str) -> dict[str, Any]:
    """The projection a writer model reads: the values of one field, by member."""
    return vote_spec(
        count,
        reducer="project",
        extract=step("json_object@1"),
        normalize=None,
        reduce=step("project_field@1", field=field),
        select=step("built@1"),
    )


__all__ = ["merge_spec", "pick_spec", "project_spec", "step"]
