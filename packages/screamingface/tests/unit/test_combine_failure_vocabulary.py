"""The SDK's combine failure vocabulary after the abstain change (OME-1289 E4a, AB#16).

FEATURE: a vote with no usable member abstains instead of failing, so ``combine_no_votes`` is no
longer a declared failure code; the other combine codes stay.
"""

from __future__ import annotations

from screamingface._report_primitives import DECLARED_FAILURE_CODES, is_declared_failure_code


def test_combine_no_votes_is_not_a_declared_code() -> None:
    assert "combine_no_votes" not in DECLARED_FAILURE_CODES
    assert not is_declared_failure_code("combine_no_votes")


def test_the_three_remaining_combine_codes_are_declared() -> None:
    for code in ("combine_spec_invalid", "combine_operator_unknown", "combine_input_too_large"):
        assert code in DECLARED_FAILURE_CODES
