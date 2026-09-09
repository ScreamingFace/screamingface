"""The benchmark spine — grading machinery shared by every board (OME-1024).

Modules here are extracted one ticket at a time from the per-board aggregate files.
AIDEV-NOTE: never edit `benchmarks/aggregation.py` or `benchmarks/contract.py` from a
spine extraction — the live-progress branches (OME-932, OME-934) own those files; the
spine grows beside them as new modules only.
"""

from screamingface_engine.benchmarks.spine.exam import exam_scorer
from screamingface_engine.benchmarks.spine.payloads import CasePayload, TextPayload
from screamingface_engine.benchmarks.spine.rows import RowIndex, RowReader, read_selected_cases
from screamingface_engine.benchmarks.spine.rubric import rubric_grade_case
from screamingface_engine.benchmarks.spine.scored import (
    CaseGradeOutcome,
    GradeCase,
    GradeRequest,
    ScoredPath,
)
from screamingface_engine.benchmarks.spine.verdict import Verdict, VerdictShape, parse_verdict

__all__ = [
    "CaseGradeOutcome",
    "CasePayload",
    "exam_scorer",
    "GradeCase",
    "GradeRequest",
    "RowIndex",
    "RowReader",
    "ScoredPath",
    "TextPayload",
    "Verdict",
    "VerdictShape",
    "parse_verdict",
    "read_selected_cases",
    "rubric_grade_case",
]
