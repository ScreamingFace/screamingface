"""A run on a fixed list of Case ids: `evaluate(..., cases=[3, 17, 42])` (OME-1739).

FEATURE (OME-1739): a researcher's development and held-out sets. A Case id is the Case's
position in the Benchmark's pinned order, 1 to N, the same number the Engine's roll call reports.

Think of it as a seating plan for one sitting: `limit=3` means "the first three seats",
`cases=[3, 17, 42]` means "seats 3, 17 and 42". This module owns the plan's three checks:

1. the door check, before anything is sent (F1, F7);
2. the roll-call positions a result graded, read back from the result itself, so a replayed run
   names its selection too;
3. the fingerprint a paper cites, `sha256:` of the sorted ids joined by commas.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from typing import cast

from screamingface._report_primitives import CaseId

# WHY 1,000: the SDK starts a run with the whole recipe in the URL, and the hosted edge answers
# normally only up to about 32 KiB of URL. Two URL-encoded copies of a 2,000-id list are about
# 26 KiB, so 1,000 leaves room for the rest of the recipe (owner-approved limit on OME-1739).
MAX_SELECTED_CASES = 1_000


def selected_cases(cases: object, limit: int | None) -> tuple[int, ...] | None:
    """Check `cases=` at the door and return the ids ascending, or None when not given.

    Worked example: `cases=[42, 3, 17]` returns `(3, 17, 42)`; `[0, 17, 17]` is refused for
    the 0 and for 17 twice; `cases=[3], limit=5` is refused because a run has one seating plan.

    INVARIANT: a refused list sends nothing to the Engine and spends nothing.
    WHY ascending: one set of Cases is one recipe whatever order it was typed in, and the Engine
    serves and reports the Cases in that order.
    """

    if cases is None:
        return None
    if limit is not None:
        raise TypeError("pass cases= or limit=, not both")
    numbers: list[int] = _whole_numbers(cases)
    if not numbers:
        raise ValueError("cases must name at least one Case id")
    if len(numbers) > MAX_SELECTED_CASES:
        raise ValueError(
            f"a run takes at most {MAX_SELECTED_CASES:,} Case ids; this list has {len(numbers):,}"
        )
    problems: list[str] = []
    if any(case_id < 1 for case_id in numbers):
        problems.append("ids must be at least 1")
    repeated: list[int] = sorted(case_id for case_id, seen in Counter(numbers).items() if seen > 1)
    problems.extend(f"{case_id} twice" for case_id in repeated)
    if problems:
        raise ValueError(f"Case ids must be distinct and at least 1 ({', '.join(problems)})")
    return tuple(sorted(numbers))


def _whole_numbers(cases: object) -> list[int]:
    """The list's ids as ints, refused when it is not a list of whole numbers."""

    if isinstance(cases, str | bytes) or not isinstance(cases, Sequence):
        raise TypeError("cases must be a list of Case ids, e.g. cases=[3, 17, 42]")
    ids: list[object] = list(cast(Sequence[object], cases))
    # WHY type() not isinstance: True is an int to isinstance, and a bool is never a Case id.
    if any(type(case_id) is not int for case_id in ids):
        raise TypeError("Case ids must be whole numbers, e.g. cases=[3, 17, 42]")
    return [cast(int, case_id) for case_id in ids]


def graded_positions(case_ids: Sequence[CaseId]) -> tuple[int, ...] | None:
    """The roll call's Case ids as positions, ascending, or None when one is not a position.

    The Engine reports a position as `3` or, for some hand-built Benchmarks, as `"3"`.
    """

    positions: list[int] = []
    for case_id in case_ids:
        if isinstance(case_id, int) and not isinstance(case_id, bool):
            positions.append(case_id)
        elif isinstance(case_id, str) and case_id.isascii() and case_id.isdigit():
            positions.append(int(case_id))
        else:
            return None
    return tuple(sorted(positions))


def selection_of(case_ids: Sequence[CaseId]) -> tuple[int, ...] | None:
    """The Cases a result graded when they are a selection, None when they are 1 to N.

    Worked example: a roll call `3, 17, 42` is the selection `(3, 17, 42)`; `1, 2, 3` is the
    same run as `limit=3` (the Engine writes a list of 1 to N as the count) and is None.
    """

    # WHY ascending (graded_positions sorts): the question is WHICH Cases were graded, never the
    # order they were listed in, so a full run listed out of order still reads as a full run.
    positions: tuple[int, ...] | None = graded_positions(case_ids)
    if not positions or positions == tuple(range(1, len(positions) + 1)):
        return None
    return positions


def selection_fingerprint(case_ids: Sequence[int]) -> str:
    """`sha256:` of the sorted ids joined by commas, e.g. `3,17,42`, for a paper to cite."""

    text: str = ",".join(str(case_id) for case_id in sorted(case_ids))
    return "sha256:" + hashlib.sha256(text.encode("ascii")).hexdigest()


__all__: list[str] = []
