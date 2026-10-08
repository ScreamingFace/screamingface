"""The order-blind seal (OME-1492 PR 2): a broken Case Digest says whether only the order moved.

INVARIANT: the explanation carries counts only, never a Case's text, because the build log is
public and some datasets are gated or licensed.
"""

from __future__ import annotations

from screamingface_engine_inspect.case_set import case_set_digest, what_moved
from screamingface_engine_inspect.prepare import PreparedCase, TaskReplayCasesSpec, case_digest


def _case(position: int, text: str, target: str) -> PreparedCase:
    """One prepared Case at a serving position, shaped as the shared Case writer shapes it."""
    return {
        "case": {"id": position, "case_id": str(position), "input": text},
        "grading_material": {"target": target},
    }


def _sealed(cases: list[PreparedCase]) -> TaskReplayCasesSpec:
    """A declaration sealed on these Cases, with both digests."""
    return TaskReplayCasesSpec(
        task="stand_in:arithmetic",
        case_count=len(cases),
        case_digest=case_digest(cases),
        case_set_digest=case_set_digest(cases),
    )


#: Stand-in Cases; they simulate a replay's output, not any real Benchmark's Cases.
_SEALED: list[PreparedCase] = [
    _case(1, "What is 6 times 7?", "42"),
    _case(2, "What is 2 plus 2?", "4"),
]
#: The same two Cases served in the other order: the writer renumbers positions.
_SWAPPED: list[PreparedCase] = [
    _case(1, "What is 2 plus 2?", "4"),
    _case(2, "What is 6 times 7?", "42"),
]


def test_a_reorder_keeps_the_case_set_digest() -> None:
    """The point of the second seal: a shuffle changes the Case Digest, not this one."""
    assert case_digest(_SWAPPED) != case_digest(_SEALED)
    assert case_set_digest(_SWAPPED) == case_set_digest(_SEALED)


def test_rewritten_text_changes_the_case_set_digest() -> None:
    reworded: list[PreparedCase] = [_SEALED[0], _case(2, "What is two plus two?", "4")]

    assert case_set_digest(reworded) != case_set_digest(_SEALED)


def test_a_reorder_reads_as_order_only() -> None:
    assert what_moved(_sealed(_SEALED), _SWAPPED) == " — same 2 Cases in another order"


def test_rewritten_text_reads_as_text_changed() -> None:
    reworded: list[PreparedCase] = [_SEALED[0], _case(2, "What is two plus two?", "four")]

    explanation: str = what_moved(_sealed(_SEALED), reworded)

    assert explanation == " — same count, different Cases: text changed"
    for text in ("What is", "42", "four", "two plus two"):
        assert text not in explanation


def test_a_row_sealed_before_the_case_set_digest_adds_nothing() -> None:
    """The 57 rows sealed before OME-1492 keep today's sentence until backfilled."""
    unsealed: TaskReplayCasesSpec = TaskReplayCasesSpec(
        task="stand_in:arithmetic", case_count=2, case_digest=case_digest(_SEALED)
    )

    assert what_moved(unsealed, _SWAPPED) == ""


def test_a_duplicated_case_counts_every_time_it_appears() -> None:
    """INVARIANT: the seal counts copies, not only which Cases exist. Some datasets repeat a
    row; a rewrite that turns [A, A, B] into [A, B, B] holds the same distinct Cases, so a
    seal that dropped copies would read "order only" and hide a changed Case."""
    six, two = ("What is 6 times 7?", "42"), ("What is 2 plus 2?", "4")
    sealed: list[PreparedCase] = [_case(1, *six), _case(2, *six), _case(3, *two)]
    rewritten: list[PreparedCase] = [_case(1, *six), _case(2, *two), _case(3, *two)]

    assert case_set_digest(rewritten) != case_set_digest(sealed)
    assert what_moved(_sealed(sealed), rewritten) == " — same count, different Cases: text changed"
