"""Partial-score advisory policy at the Scoreboard write boundary."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

from screamingface._environment import running_in_notebook
from screamingface._notices import PARTIAL_SUBMISSION_NOTICE, ClientNotice
from screamingface._ui.notice_view import display_notebook_notice
from screamingface.report import CandidateResult
from screamingface.warnings import EvaluationWarning

_SDK_PACKAGE_ROOT = str(Path(__file__).resolve().parents[1])


def prepare_submission_notice(candidate_result: CandidateResult) -> ClientNotice | None:
    """Apply the caller's warning policy before a write, and reserve rich notebook output.

    INVARIANT: the policy is uniform — a notebook is not an escape hatch. `-W error` aborts
    before the POST in both environments, and `-W ignore` silences the advisory in both.
    """

    if not _is_partial_submission(candidate_result):
        return None
    if not running_in_notebook():
        _warn()
        return None
    # WHY the recording context: it applies the caller's filters — an "error" policy raises
    # straight through it, an "ignore" policy records nothing — while swallowing the stderr
    # write that IPython would otherwise render as a red block beside the branded notice.
    # AIDEV-NOTE: `catch_warnings` mutates process-global filter state, so this block is not
    # thread-safe. It holds exactly one `warn` call and no I/O, and async submission awaits
    # nothing inside it, so the window is a few microseconds on the calling thread.
    with warnings.catch_warnings(record=True) as recorded:
        _warn()
    # AIDEV-NOTE: __warningregistry__ dedup means a repeat submission from one source line
    # records nothing and therefore displays nothing. That matches the headless once-per-line
    # semantics, and each notebook cell execution is a fresh filename, so re-runs still show.
    return PARTIAL_SUBMISSION_NOTICE if recorded else None


def display_submission_notice(notice: ClientNotice | None) -> None:
    """Publish a reserved notebook notice after the Scoreboard confirms the write."""

    if notice is not None:
        try:
            display_notebook_notice(notice)
        except Exception:
            # INVARIANT: presentation happens after persistence and therefore must not raise.
            # The score already exists on the Scoreboard; letting a display failure propagate
            # would discard the returned id and leave the caller unable to recover the write.
            print(notice.message, file=sys.stderr)


def _warn() -> None:
    """Emit the advisory at the caller's own source line."""

    # WHY skip_file_prefixes over a fixed stacklevel: the module-level facade and the explicit
    # Client add different numbers of SDK frames, so no single count blames the user's line.
    warnings.warn(
        PARTIAL_SUBMISSION_NOTICE.message,
        EvaluationWarning,
        skip_file_prefixes=(_SDK_PACKAGE_ROOT,),
    )


def _is_partial_submission(candidate_result: CandidateResult) -> bool:
    # INVARIANT: the retained Cases are the authority on completeness, not `coverage`. The
    # Engine reports coverage as round(gradeable / case_count, 4), so on a large Benchmark a
    # handful of missing grades rounds to exactly 1.0 and would read as a complete run. A
    # limited Evaluation is the other half: every selected Case can be graded while most of
    # the Benchmark was never run.
    return len(candidate_result.cases) != candidate_result.benchmark.case_count or any(
        case.grade is None or case.grade.score is None for case in candidate_result.cases
    )


__all__: list[str] = []
