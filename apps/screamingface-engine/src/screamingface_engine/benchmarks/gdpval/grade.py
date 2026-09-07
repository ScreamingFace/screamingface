"""GDPval's grading hooks — everything this board still writes to be graded.

The spine owns the marking room (``spine/scored.py``); this module is the board's
contribution: its failure wording, its judge's identity, its private rubric reader, and
its official per-Case formula bound into the shared rubric ``grade_case``. The engine
ships mechanisms; a benchmark ships semantics.

INVARIANT: points come from the PRIVATE baked rubric on disk, never from anything that
has passed through a model. The judge decides whether a criterion was met; it never
decides what it is worth.

INVARIANT: failure codes and message texts are byte-identical to the pre-extraction
``gdpval/aggregate.py`` — the wording is this board's published voice.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.gdpval.case_evaluation import decode_case_evaluation
from screamingface_engine.benchmarks.gdpval.scoring import case_score
from screamingface_engine.benchmarks.spine.rows import RowReader, read_selected_cases
from screamingface_engine.benchmarks.spine.rubric import rubric_grade_case
from screamingface_engine.benchmarks.spine.scored import ScoredPath

_FAILURE_MESSAGES = {
    "missing_rubric_asset": "the baked rubric asset for this Case is missing or invalid",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
    "incomplete_verdicts": "not every rubric criterion received a valid judge verdict",
    "no_positive_points": "no judged criterion carries positive points (baked-asset defect)",
}


class AggregateError(ValueError):
    """The reducer's input is unusable — raised before any scoring."""


def load_rubric_points(root: Path, case_id: int) -> list[int] | None:
    """Read one Case's private points list; ``None`` when the asset is unusable."""

    path = root / "rubrics" / f"{case_id}.json"
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _points_from(decoded)


def _points_from(decoded: object) -> list[int] | None:
    items = decoded.get("items") if isinstance(decoded, Mapping) else None
    if not isinstance(items, list) or not items:
        return None
    points: list[int] = []
    for index, item in enumerate(items, start=1):
        value = item.get("points") if isinstance(item, Mapping) else None
        # INVARIANT: rubric_id is the 1-based position `prepare` assigned. A file whose ids do
        # not match their positions is unusable rather than partially usable — scoring the wrong
        # criterion is worse than reporting a missing asset.
        usable = (
            isinstance(item, Mapping)
            and not isinstance(value, bool)
            and isinstance(value, int)
            and item.get("rubric_id") == index
        )
        if not usable:
            return None
        assert isinstance(value, int)
        points.append(value)
    return points


def aggregate(
    raw_rows: str,
    root: Path,
    *,
    benchmark_id: str,
    benchmark_revision: str,
    case_ids: tuple[int, ...],
    mean: Callable[[Sequence[float]], float | None],
) -> dict[str, Any]:
    """Score every selected Case on the shared scored path, with this board's hooks.

    ``case_ids`` is authoritative: a Case that produced no row stays visible without a
    grade rather than vanishing from the roll call. ``mean`` is GDPval's plain
    unclipped average (``scoring.mean``) — its official metric is a pairwise win rate,
    so no published clip convention exists to match.
    """

    return _PATH.aggregate(
        raw_rows,
        benchmark_id=benchmark_id,
        benchmark_revision=benchmark_revision,
        selected_cases=read_selected_cases(
            root, case_ids, benchmark_label="GDPval", error_type=AggregateError
        ),
        grading_material=lambda case_id: load_rubric_points(root, case_id),
        mean=mean,
    )


# WHY bound at module bottom: the scored path lives in the spine (OME-1097); the hooks
# and the failure-message wording stay board-owned so per-case failure output is
# byte-identical to the pre-extraction copies (the goldens pin every failure code).
_PATH = ScoredPath(
    reader=RowReader(
        benchmark_label="GDPval",
        error_type=AggregateError,
        decode_case_evaluation=decode_case_evaluation,
    ),
    grade_case=rubric_grade_case(case_score=case_score, judge_producer_id="gdpval/judge"),
    failure_messages=_FAILURE_MESSAGES,
    method="rubric",
    grading_failure_code="gdpval_grading_failed",
    grading_failure_message="the GDPval grader could not grade this Case",
)

__all__ = ["AggregateError", "aggregate", "load_rubric_points"]
