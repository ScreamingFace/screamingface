"""The consistency counts of one member (E4b part 7; consistency-value PRD §2, erd §5).

FEATURE: count how many of one member's successful extra samples give the member's own answer,
so that a rule can read ``matched / succeeded`` as the member's consistency value (ans:Q4).
INVARIANT: pure, standard library only (contracts C7; the layering gate checks it): no I/O, no
clock, no operator import. The endpoint passes the match steps in as ``read``.
INVARIANT: ``value`` is None exactly when ``matched`` is None. A failed sample is never in the
denominator, and the member's own answer is not a sample (ans:Q4, P11).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SampleCount:
    """One member's samples: ``matched`` of the ``succeeded`` samples give the member's answer;
    ``failed`` samples gave no reply. ``matched`` is None when there is nothing to compare."""

    matched: int | None
    succeeded: int
    failed: int

    @property
    def value(self) -> float | None:
        """``matched / succeeded`` (Python float division); None when ``matched`` is None."""
        return None if self.matched is None else self.matched / self.succeeded


def count_samples(
    member_value: str | None,
    texts: Sequence[str],
    n: int,
    read: Callable[[str], str | None],
) -> SampleCount:
    """Stub (E4b part 7 unit 2, commit A): the body lands in commit B."""
    raise NotImplementedError("count_samples is built in E4b part 7 unit 2")


__all__ = ["SampleCount", "count_samples"]
