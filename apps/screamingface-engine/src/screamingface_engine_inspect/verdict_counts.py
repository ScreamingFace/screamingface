"""Judge-verdict counts: how a judged local Task tells the run how many verdicts landed.

Think of a judged Case as a marking sheet with boxes for the judge to tick, one per rubric
line per pass. The Case score only says how the ticked boxes came out; it cannot say that
some boxes were never ticked because the judge's reply never parsed. The Report's "Grading
did not fully land" warning exists for exactly that, and it reads three run-level counts.

The convention, in one line: a scorer that judges writes ``verdicts_expected`` (boxes on
the sheet) and ``verdicts_accepted`` (boxes ticked with a usable verdict) into its
``Score.metadata``. The scorer adapter copies them onto the Case's grade metrics with
``verdicts_rejected`` = expected − accepted beside them (:func:`case_verdict_counts`), and
the run tally sums the three over the graded Cases (:func:`run_verdict_counts`). A scorer
that writes neither key publishes nothing new.

WHY ``rejected`` and not ``invalid`` or ``missing``: the hand-built DRACO grader (deleted at
OME-1527 row 18) split a shortfall three ways — ``rejected`` = expected − accepted (every box
left unticked), ``invalid`` = the judge replied but no verdict parsed, ``missing`` = no reply
at all. Two counts can only rebuild the first, so that is the one published; the lane never
claims a split it cannot see.

Pure Python on purpose: the run tally imports this module at Engine start, where inspect is
not imported.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

#: Boxes on the marking sheet: rubric lines × judge passes. Written by the scorer.
VERDICTS_EXPECTED = "verdicts_expected"
#: Boxes ticked with a usable verdict (after any redraws). Written by the scorer.
VERDICTS_ACCEPTED = "verdicts_accepted"
#: Boxes left unticked, expected − accepted. Derived here, never written by the scorer.
VERDICTS_REJECTED = "verdicts_rejected"

#: The Case grade and run metrics this convention publishes, in the Report's reading order.
VERDICT_COUNT_KEYS: tuple[str, ...] = (VERDICTS_EXPECTED, VERDICTS_ACCEPTED, VERDICTS_REJECTED)


def case_verdict_counts(metadata: Mapping[str, Any] | None) -> dict[str, int]:
    """One Case's verdict counts off its Score metadata, checked; ``{}`` when it has none.

    Worked example (draco-3pass, a rubric of 2 lines): 2 lines × 3 passes = 6 boxes; one
    reply never parsed, even after its redraws, so 5 landed. The scorer wrote
    ``{"verdicts_expected": 6, "verdicts_accepted": 5}``; this returns
    ``{"verdicts_expected": 6, "verdicts_accepted": 5, "verdicts_rejected": 1}``.

    Raises:
        ValueError: when the scorer wrote one count without the other, a count that is not
            a whole number from 0 up, or more accepted verdicts than expected ones. Each
            would publish a warning that lies, so the Case fails by name instead.
    """

    present: dict[str, object] = {
        key: metadata[key]
        for key in (VERDICTS_EXPECTED, VERDICTS_ACCEPTED)
        if metadata is not None and key in metadata
    }
    if not present:
        return {}
    if len(present) == 1:
        (written,) = present
        raise ValueError(
            f"the scorer wrote {written} without its pair; verdict counts need both "
            f"{VERDICTS_EXPECTED} and {VERDICTS_ACCEPTED}"
        )
    counts: dict[str, int] = {}
    for key, value in present.items():
        # bool before int — bool IS an int, and True is not a count.
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"the scorer's {key} must be a whole number from 0 up, got {value!r}")
        counts[key] = value
    expected: int = counts[VERDICTS_EXPECTED]
    accepted: int = counts[VERDICTS_ACCEPTED]
    if accepted > expected:
        raise ValueError(
            f"the scorer accepted {accepted} verdicts but expected only {expected}; "
            "accepted verdicts are a share of the expected ones"
        )
    return {
        VERDICTS_EXPECTED: expected,
        VERDICTS_ACCEPTED: accepted,
        VERDICTS_REJECTED: expected - accepted,
    }


def run_verdict_counts(case_metrics: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """The run's verdict counts: each graded Case's counts, added up; ``{}`` when none has any.

    Think of it as the tally clerk stacking the graded Cases' marking sheets and counting
    boxes across the pile. Only GRADED Cases are in the pile (the tally passes exactly
    those): a Case whose scorer raised has no sheet, and is already on the Report as a
    failed Case, as the hand-built grader left it out of its sums.

    Worked example: 3 graded Cases × 2 passes × 4 lines, so 8 boxes each. They landed 8, 7
    and 6 → expected 24, accepted 21, rejected 3, and the Report reads "Grading did not
    fully land: 3 rejected of 24 verdicts".

    Args:
        case_metrics: each graded Case's grade metrics; a Case without counts adds nothing.
    """

    sheets: list[Mapping[str, Any]] = [
        metrics for metrics in case_metrics if VERDICTS_EXPECTED in metrics
    ]
    if not sheets:
        return {}
    return {key: sum(int(metrics[key]) for metrics in sheets) for key in VERDICT_COUNT_KEYS}


__all__ = [
    "VERDICT_COUNT_KEYS",
    "VERDICTS_ACCEPTED",
    "VERDICTS_EXPECTED",
    "VERDICTS_REJECTED",
    "case_verdict_counts",
    "run_verdict_counts",
]
