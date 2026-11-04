"""E4b adds no failure code: every new refusal is ``combine_spec_invalid`` (E4b CS-D2, P7).

CHAR (CS#8): passes before and after every E4b unit. A new empty result is an abstain (a normal
output), never a failure, so the declared vocabulary keeps its 65 codes and its three combine codes.
INVARIANT defended: E4b leaves ``test_failure_classes.py`` and the SDK mirror unchanged.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.contract import DECLARED_FAILURE_CODES


def test_declared_failure_codes_are_unchanged_by_e4b() -> None:
    assert len(DECLARED_FAILURE_CODES) == 65
    assert {code for code in DECLARED_FAILURE_CODES if code.startswith("combine_")} == {
        "combine_spec_invalid",
        "combine_operator_unknown",
        "combine_input_too_large",
    }
    assert "judge_reply_invalid" in DECLARED_FAILURE_CODES
