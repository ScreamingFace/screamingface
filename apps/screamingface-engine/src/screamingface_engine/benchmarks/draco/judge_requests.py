"""Prepare weight-free DRACO judge requests at the case-to-criterion scope boundary.

INVARIANT: Judge inputs contain one criterion's public requirement and type, never its weight,
axis score, sibling criteria, or private rubric structure.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.draco.validation import (
    optional_integer,
    require_positive_integer,
    require_text,
)


class JudgeRequestError(ValueError):
    """The case payload or prepared criterion data is unusable."""


def build_judge_requests(
    case_id: int,
    question: str,
    answer: str,
    criteria: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Join one dynamic Candidate answer to Engine-owned, weight-free judge inputs."""
    selected_case_id = positive_case_id(case_id)
    selected_question = _text(question, "question")
    selected_answer = _answer(answer)

    judge_requests: list[dict[str, str]] = []
    for index, criterion in enumerate(criteria):
        if not isinstance(criterion, Mapping):
            raise JudgeRequestError(f"criterion {index} must be a JSON object")
        criterion_type = _text(criterion.get("criterion_type"), "criterion_type")
        if criterion_type not in {"positive", "negative"}:
            raise JudgeRequestError(
                f"criterion {index} has invalid criterion_type {criterion_type!r}"
            )
        judge_requests.append(
            {
                "case_id": str(selected_case_id),
                "question": selected_question,
                "answer": selected_answer,
                "criterion_id": _text(criterion.get("id"), "criterion id"),
                "criterion": _text(criterion.get("requirement"), "criterion requirement"),
                "criterion_type": criterion_type,
            }
        )
    if not judge_requests:
        raise JudgeRequestError(f"case {selected_case_id} has no judge criteria")
    return judge_requests


def load_criteria(directory: Path, case_id: int) -> list[dict[str, Any]]:
    path = directory / f"{case_id}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JudgeRequestError(f"could not read criteria for case {case_id}: {exc}") from None
    except ValueError as exc:
        raise JudgeRequestError(f"criteria for case {case_id} are not JSON: {exc}") from None
    if not isinstance(value, list):
        raise JudgeRequestError(f"criteria for case {case_id} must be a JSON array")
    return value


def load_question(directory: Path, case_id: int) -> str:
    path = directory.parent / "cases.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JudgeRequestError(f"could not read DRACO cases: {exc}") from None
    except ValueError as exc:
        raise JudgeRequestError(f"DRACO cases are not JSON: {exc}") from None
    if not isinstance(value, list):
        raise JudgeRequestError("DRACO cases must be a JSON array")
    for row in value:
        if isinstance(row, Mapping) and _case_id(row.get("id")) == case_id:
            return _text(row.get("input"), "question")
    raise JudgeRequestError(f"unknown DRACO case {case_id}")


def positive_case_id(value: object) -> int:
    """Decode the case id carried in a Benchmark route intent."""
    try:
        return require_positive_integer(value, "case_id")
    except ValueError as exc:
        raise JudgeRequestError(str(exc)) from None


def _case_id(value: object) -> int | None:
    return optional_integer(value)


def _text(value: object, label: str) -> str:
    try:
        return require_text(value, label)
    except ValueError as exc:
        raise JudgeRequestError(str(exc)) from None


def _answer(value: object) -> str:
    if not isinstance(value, str):
        raise JudgeRequestError("answer must be text")
    return value


__all__ = [
    "JudgeRequestError",
    "build_judge_requests",
    "load_criteria",
    "load_question",
    "positive_case_id",
]
