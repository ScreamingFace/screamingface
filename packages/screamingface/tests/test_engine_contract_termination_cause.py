"""A run that failed in a Benchmark code step reports the step's declared code.

WHY: url4 heads the failure with `intent_error` (Spec C §13.6) and carries the handler's own
code and permanence in `cause`; that is the failure the user acts on.
"""

from __future__ import annotations

from screamingface._engine.contract import _termination_error


def test_the_cause_names_the_termination_error() -> None:
    error = _termination_error(
        {
            "code": "intent_error",
            "message": "code '/b/aggregate' failed: judge_reply_invalid: empty reply",
            "permanent": True,
            "cause": {"code": "judge_reply_invalid", "permanent": False},
        }
    )

    assert error is not None
    assert (error.code, error.permanent) == ("judge_reply_invalid", False)
    assert error.message.startswith("code '/b/aggregate' failed")


def test_a_termination_error_without_a_cause_is_unchanged() -> None:
    error = _termination_error({"code": "timeout", "message": "slow", "permanent": False})

    assert error is not None
    assert (error.code, error.permanent) == ("timeout", False)


def test_a_null_cause_is_no_cause() -> None:
    error = _termination_error(
        {"code": "intent_error", "message": "m", "permanent": True, "cause": None}
    )

    assert error is not None
    assert error.code == "intent_error"
