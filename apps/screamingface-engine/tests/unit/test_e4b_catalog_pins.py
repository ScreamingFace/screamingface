"""E4b adds one failure code, ``logprobs_unsupported`` (E4b part 3, P13); every other new refusal
is ``combine_spec_invalid`` (E4b CS-D2, P7).

CHAR (CS#8): a new empty result is an abstain (a normal output), never a failure, so the declared
vocabulary has 66 codes (the 65 before E4b part 3 plus ``logprobs_unsupported``) and its three
combine codes.
INVARIANT defended: E4b part 3 adds exactly one code to ``test_failure_classes.py`` and the SDK
mirror.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.contract import DECLARED_FAILURE_CODES


def test_declared_failure_codes_gain_only_logprobs_unsupported_in_e4b() -> None:
    # E4c (OME-1291, guards #4, skip-members #2a) adds `fail_closed` and `quorum_not_met`: 66 -> 68;
    # the 2026-11-12 review adds `signal_missing`: 68 -> 69.
    assert len(DECLARED_FAILURE_CODES) == 69
    assert "logprobs_unsupported" in DECLARED_FAILURE_CODES
    assert {code for code in DECLARED_FAILURE_CODES if code.startswith("combine_")} == {
        "combine_spec_invalid",
        "combine_operator_unknown",
        "combine_input_too_large",
    }
    assert "judge_reply_invalid" in DECLARED_FAILURE_CODES
