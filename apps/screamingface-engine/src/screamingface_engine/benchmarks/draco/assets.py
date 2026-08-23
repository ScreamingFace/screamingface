"""Load DRACO's private grading assets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.draco import scoring, tasks
from screamingface_engine.benchmarks.draco.errors import AggregateError


def load_rubrics(directory: Path) -> dict[int, dict[str, Any]]:
    """Load ``<directory>/<case_id>.json`` for every rubric on disk.

    The rubrics ship in the benchmark image rather than the control plane so that grading assets
    have their own build lifecycle — NOT because they are secret. The upstream dataset is public,
    and each Case Result publishes the requirement text, weight, and axis of every graded
    criterion (see ``case_results._checks``). Do not add a secrecy guarantee on top of this.

    INVARIANT: an absent or empty directory raises. Returning ``{}`` makes every case an
    "unknown case_id" failure, which reaches the client as a terminated-succeeded run carrying a
    plausible zero score. A misconfigured path must be loud.
    """
    rubrics: dict[int, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            case_id = int(path.stem)
        except ValueError:
            continue
        rubrics[case_id] = json.loads(path.read_text(encoding="utf-8"))
    if not rubrics:
        raise AggregateError(
            f"no rubrics under {str(directory)!r}; the installed DRACO assets are incomplete"
        )
    return rubrics


def load_rubric(directory: Path, case_id: int) -> dict[str, Any]:
    """Load one selected rubric after world installation validated protocol alignment."""

    path = directory / f"{case_id}.json"
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AggregateError(f"DRACO rubric {case_id} is unavailable: {exc}") from None
    if not isinstance(decoded, dict):
        raise AggregateError(f"DRACO rubric {case_id} must be a JSON object")
    return decoded


def validate_protocol_assets(
    root: Path,
    cases: list[dict[str, object]],
) -> dict[int, dict[str, Any]]:
    """Validate complete Case/criteria/rubric alignment before installing any route."""
    rubrics = load_rubrics(root / "rubrics")
    seen_case_ids: set[int] = set()
    for index, case in enumerate(cases):
        case_id = tasks.positive_case_id(case.get("id"))
        if case_id in seen_case_ids:
            raise ValueError(f"DRACO Case sequence repeats case_id {case_id}")
        seen_case_ids.add(case_id)
        _validate_case_assets(root, rubrics, case, index, case_id)
    return rubrics


def _validate_case_assets(
    root: Path,
    rubrics: dict[int, dict[str, Any]],
    case: dict[str, object],
    index: int,
    case_id: int,
) -> None:
    question = case.get("input")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"DRACO Case {index} must carry non-empty input text")
    rubric = rubrics.get(case_id)
    if rubric is None:
        raise ValueError(f"Case {case_id} has no installed DRACO rubric")
    rubric_ids = [str(criterion.get("id")) for criterion in scoring.flatten_criteria(rubric)]
    if not rubric_ids:
        raise ValueError(f"Case {case_id} has no DRACO rubric criteria")
    if len(set(rubric_ids)) != len(rubric_ids):
        raise ValueError(f"Case {case_id} DRACO rubric repeats a criterion id")
    criteria = tasks.load_criteria(root / "criteria", case_id)
    validated_tasks = tasks.build_tasks(case_id, question, "asset validation", criteria)
    criteria_ids = [task["criterion_id"] for task in validated_tasks]
    if criteria_ids != rubric_ids:
        raise ValueError(f"Case {case_id} criterion assets do not match its installed DRACO rubric")
