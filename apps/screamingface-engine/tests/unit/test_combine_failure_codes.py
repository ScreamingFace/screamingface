"""The combine failure codes are declared (FW-7, OME-1289 E4a, unit 1)."""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.contract import DECLARED_FAILURE_CODES
from screamingface_engine.combine.ports import (
    CombineError,
    InputTooLarge,
    JudgeReplyInvalid,
    NoVotes,
    OperatorUnknown,
    SpecInvalid,
)


@pytest.mark.parametrize(
    "error",
    [SpecInvalid, OperatorUnknown, NoVotes, InputTooLarge, JudgeReplyInvalid],
    ids=lambda error: error.__name__,
)
def test_new_failure_codes_are_declared(error: type[CombineError]) -> None:
    assert error.code in DECLARED_FAILURE_CODES


def test_the_combine_error_codes_are_the_pinned_names() -> None:
    assert {SpecInvalid.code, OperatorUnknown.code, NoVotes.code, InputTooLarge.code} == {
        "combine_spec_invalid",
        "combine_operator_unknown",
        "combine_no_votes",
        "combine_input_too_large",
    }
    assert JudgeReplyInvalid.code == "judge_reply_invalid"
