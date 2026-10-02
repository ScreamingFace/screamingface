"""regex@1 compiles with explicit RE2 options: silent, bounded, case by option (OME-1289).

FEATURE: a bad or oversized author pattern fails at spec check, quietly, before any member runs.
STORY: as an operator of an Engine worker, I never see an author's pattern in the worker logs, and
no pattern compiles to a program so large that one member call takes tens of milliseconds.
E4a gap-closure unit 2, RE2 review round (M1, M2, MINOR 2, MINOR 4).
"""

from __future__ import annotations

import time
from collections.abc import Mapping

import pytest
from combine_golden_support import stage

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import SpecInvalid, StageResult

_PATTERN = "SECRET-PATTERN-(?=x)"


def _check(args: Mapping[str, object]) -> None:
    descriptor = BUILTIN_OPERATORS.resolve("regex@1", "extract")
    assert descriptor.check_args is not None
    descriptor.check_args(args)


def test_a_rejected_pattern_is_never_written_to_stderr(capfd: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SpecInvalid) as raised:
        _check({"pattern": _PATTERN})
    captured = capfd.readouterr()
    assert "SECRET-PATTERN" not in captured.err
    assert "SECRET-PATTERN" not in captured.out
    assert "SECRET-PATTERN" not in str(raised.value)


def test_the_compile_error_names_the_re2_limits() -> None:
    with pytest.raises(SpecInvalid, match=r"lookarounds.*backreferences.*1000"):
        _check({"pattern": "(?=a)"})


def test_dollar_is_the_end_of_text_under_re2() -> None:
    # WHY pinned: stdlib `$` also matched before a final newline; RE2's `$` does not.
    assert stage("regex@1", "Final: B\n", {"pattern": r"Final: (\w)$", "group": 1}) == (
        StageResult(None, "no_match")
    )
    assert stage("regex@1", "Final: B\n", {"pattern": r"Final: (\w)\s*$", "group": 1}) == (
        StageResult("B", "voted")
    )


def test_ignore_case_is_an_option_not_a_prefix() -> None:
    args = {"pattern": r"(?P<ans>final): (b)", "group": 2, "ignore_case": True}
    _check(args)
    assert stage("regex@1", "FINAL: B", args) == StageResult("B", "voted")
    _check({"pattern": "(?P<ans>x)", "group": "ans", "ignore_case": True})


@pytest.mark.parametrize(
    "pattern",
    [r"(?:(.)|(.)|(.)|(.)){1000}x", r"(.{0,1000})(.{0,1000})(.{0,1000})x"],
)
def test_a_pattern_with_an_oversized_re2_program_is_spec_invalid(pattern: str) -> None:
    with pytest.raises(SpecInvalid, match="too large") as raised:
        _check({"pattern": pattern})
    assert pattern not in str(raised.value)


def test_a_pattern_just_under_the_program_cap_stays_fast() -> None:
    args = {"pattern": r".{0,300}x"}
    _check(args)
    text = "a" * 1023 + "!"
    best = min(_time(text, args) for _ in range(3))
    assert best < 0.005, f"{best * 1000:.2f} ms"


def _time(text: str, args: Mapping[str, object]) -> float:
    start = time.perf_counter()
    stage("regex@1", text, args)
    return time.perf_counter() - start
