"""Which Cases one run covers: the first N, or a fixed list of Case ids (OME-1739).

Think of it as the seating plan for one sitting of an exam: either "the first 20 seats" or
"seats 3, 17 and 42". The plan is written into the recipe once per place that used to carry a
bare count (the Cases step, the aggregate, the early-result route), and every one of those
reads it back with :meth:`CaseSelection.parse`.

Worked example. ``CaseSelection.of([42, 3, 17])`` keeps ``case_ids = (3, 17, 42)`` and writes
``[3,17,42]``; the Cases step serves those three rows, url4 slices ``0:3``, and the aggregate
grades Cases 3, 17 and 42. ``CaseSelection.of([1, 2, 3])`` is the same selection as
``CaseSelection.first(3)`` and writes ``3``.

INVARIANT: a selection of Cases 1..N is written exactly as the count ``N``, so a ``limit=N``
recipe, its cache keys and every frozen copy already pinned stay byte-identical.

WHY the text forms cannot be confused: a count is bare digits and an id list is always a JSON
array, so ``3`` (Cases 1 to 3) and ``[3]`` (Case 3 only) read back differently.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

# WHY 1,000 (OME-1739 limits check, 2026-11-02): the SDK starts a run with the whole recipe in
# the URL, and the hosted edge answers normally only up to about 32 KiB of URL. The id list
# rides that recipe more than once, and two URL-encoded copies of ~2,000 ids already reach
# ~26 KiB, so a list is capped well under that.
MAX_SELECTED_CASE_IDS = 1000


@dataclass(frozen=True, slots=True)
class CaseSelection:
    """The Case ids one run covers, ascending and distinct, each at least 1."""

    case_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        ids: tuple[int, ...] = self.case_ids
        if not ids:
            raise ValueError("a selection must name at least one Case")
        # WHY type() not isinstance: a JSON true is a Python bool, which isinstance counts
        # as int, and True is not Case 1.
        if any(type(case_id) is not int or case_id < 1 for case_id in ids):
            raise ValueError("Case ids must be whole numbers of at least 1")
        if any(later <= earlier for earlier, later in zip(ids, ids[1:], strict=False)):
            raise ValueError("Case ids must be ascending and distinct")

    @classmethod
    def first(cls, count: int) -> CaseSelection:
        """Cases 1 to ``count`` — what ``limit=count`` has always meant."""

        if type(count) is not int or count < 1:
            raise ValueError(f"a Case count must be a positive integer, got {count!r}")
        return cls(tuple(range(1, count + 1)))

    @classmethod
    def of(cls, case_ids: Iterable[object]) -> CaseSelection:
        """An explicit id list, sorted ascending; duplicates and the cap are refused."""

        ids: list[int] = []
        for case_id in case_ids:
            if type(case_id) is not int:
                raise ValueError("Case ids must be whole numbers of at least 1")
            ids.append(case_id)
        repeated: list[int] = sorted(case_id for case_id, seen in Counter(ids).items() if seen > 1)
        if repeated:
            raise ValueError(f"Case ids must be distinct (repeated: {repeated})")
        if len(ids) > MAX_SELECTED_CASE_IDS:
            raise ValueError(
                f"at most {MAX_SELECTED_CASE_IDS} Case ids per run; this list has {len(ids)}"
            )
        return cls(tuple(sorted(ids)))

    @classmethod
    def coerce(cls, value: int | CaseSelection) -> CaseSelection:
        """Accept the historic bare count wherever a selection is taken."""

        return value if isinstance(value, CaseSelection) else cls.first(value)

    @classmethod
    def parse(cls, text: str, *, available: int) -> CaseSelection:
        """Read the recipe's text form back (``3`` or ``[3,17,42]``) for a Benchmark of
        ``available`` Cases.

        INVARIANT: the bound is checked BEFORE a count is expanded into ids. Anyone can run a
        hand-written recipe, so ``aggregate:9999999999`` must be refused as text, never by
        building a ten-billion-entry tuple first.

        Raises:
            ValueError: anything else, including ``[]``, ``[3,3]``, ``[true]``, ``3)!/x`` and a
                count or id above ``available``.
        """

        if text.startswith("["):
            try:
                decoded: object = json.loads(text)
            except ValueError as exc:
                raise ValueError(f"invalid Case id list {text!r}") from exc
            if not isinstance(decoded, list):
                raise ValueError(f"invalid Case id list {text!r}")
            return cls.of(decoded).require_within(available)
        count: int = int(text)
        if not 1 <= count <= available:
            raise ValueError(f"selected {count} of {available} Cases")
        return cls.first(count)

    @property
    def count(self) -> int:
        """How many Cases the run covers."""

        return len(self.case_ids)

    @property
    def is_prefix(self) -> bool:
        """True for Cases 1..N, which is written as the bare count."""

        return self.case_ids[-1] == self.count

    def require_within(self, available: int) -> CaseSelection:
        """Return this selection, or refuse an id above the Benchmark's ``available`` Cases."""

        if self.case_ids[-1] > available:
            above: list[int] = [case_id for case_id in self.case_ids if case_id > available]
            raise ValueError(
                f"the Benchmark has {available} Cases; {', '.join(map(str, above))} out of range"
            )
        return self

    def __str__(self) -> str:
        """The recipe's text form: the count for 1..N, else a compact JSON array."""

        if self.is_prefix:
            return str(self.count)
        return json.dumps(list(self.case_ids), separators=(",", ":"))


__all__ = ["MAX_SELECTED_CASE_IDS", "CaseSelection"]
