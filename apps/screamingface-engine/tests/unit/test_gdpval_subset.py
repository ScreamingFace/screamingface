"""The frozen GDPval text-subset selection — what this board serves, and what it refuses.

INVARIANT under test: the selection is FROZEN. Its sha participates in the board's revision
hash, so an edit here re-addresses every route — an expression written against the old
revision physically cannot resolve against a changed selection.

FEATURE: the GDPval text subset — the prose-only slice of the 220-task open gold set that
the existing rubric judge can grade without artifact handling.
"""

from __future__ import annotations

import hashlib

from screamingface_engine.benchmarks.gdpval.subset import (
    EXCLUDED_TASK_IDS,
    TEXT_SUBSET_TASK_IDS,
    subset_sha,
)

# WHY: measured 2026-08-24 over the published parquet (all 220 rows). 109 tasks pass the
# prose-only extension filter; 7 of those have references that cannot be extracted to text,
# so this board serves 102. See docs/spec/2026-08-24-OME-971-gdpval-text-subset.md F2/F4.
EXPECTED_CASE_COUNT = 102
EXPECTED_EXCLUSIONS = 7


def test_the_board_serves_exactly_the_measured_case_count() -> None:
    assert len(TEXT_SUBSET_TASK_IDS) == EXPECTED_CASE_COUNT


def test_the_selection_holds_no_duplicates() -> None:
    # WHY: a duplicate would inflate case_count while grading the same task twice, which the
    # aggregate has no way to detect.
    assert len(set(TEXT_SUBSET_TASK_IDS)) == len(TEXT_SUBSET_TASK_IDS)


def test_every_excluded_task_carries_a_documented_reason() -> None:
    assert len(EXCLUDED_TASK_IDS) == EXPECTED_EXCLUSIONS
    for task_id, reason in EXCLUDED_TASK_IDS.items():
        assert task_id, "an exclusion must name its task"
        assert reason.strip(), f"exclusion {task_id} has no reason"


def test_excluded_tasks_are_absent_from_the_selection() -> None:
    # INVARIANT: a task whose references failed extraction must never be served — its low
    # score would read as model weakness rather than as a broken input.
    assert not (set(TEXT_SUBSET_TASK_IDS) & set(EXCLUDED_TASK_IDS))


def test_subset_sha_fingerprints_the_selection_in_order() -> None:
    expected = hashlib.sha256("\n".join(TEXT_SUBSET_TASK_IDS).encode()).hexdigest()
    assert subset_sha() == expected


def test_subset_sha_is_stable_across_calls() -> None:
    assert subset_sha() == subset_sha()
