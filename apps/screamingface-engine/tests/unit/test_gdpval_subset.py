"""The frozen GDPval text-subset selection — what this benchmark serves, and what it refuses.

INVARIANT under test: the selection is FROZEN. Its order is the Case order and the Case Digest
seals it (OME-1527: GDPval-text is a local Task now), so an edit is a new Benchmark revision.

FEATURE: the GDPval text subset — the prose-only slice of the 220-task open gold set that
the existing rubric judge can grade without artifact handling.
"""

from __future__ import annotations

# WHY this module: OME-1527 moved GDPval-text to a local Task; this code moved with it,
# and this test follows it (the module imports no inspect, so it runs extra-less).
from screamingface_engine_inspect.local_tasks.gdpval.subset import (
    EXCLUDED_TASK_IDS,
    TEXT_SUBSET_TASK_IDS,
)

# WHY: measured 2026-08-24 over the published parquet (all 220 rows). 109 tasks pass the
# prose-only extension filter; 7 of those have references that cannot be extracted to text,
# so this benchmark serves 102. See docs/spec/2026-08-24-OME-971-gdpval-text-subset.md F2/F4.
EXPECTED_CASE_COUNT = 102
EXPECTED_EXCLUSIONS = 7


def test_the_benchmark_serves_exactly_the_measured_case_count() -> None:
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
