"""regex@1 reads one group from the last 1024 characters, on the linear-time RE2 engine (OME-1289).

FEATURE: an author names a regex; the engine runs it deterministically and fast.
STORY: as an author of a majority-vote Candidate, I read the answer from a labelled line such as
"Final: B", and no pattern I write can freeze a worker: RE2 runs in linear time by construction.
RX#1 to RX#7 (RX-D1 to RX-D5) of the E4a gap-closure; unit 2, after the RE2 decision.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

import pytest
from combine_golden_support import find, stage
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS, BUILTIN_REGISTRATIONS
from screamingface_engine.combine.endpoint import CombineOutcome
from screamingface_engine.combine.ports import CombineError, SpecInvalid, StageResult
from screamingface_engine.combine.registry import OperatorRegistry

_CATASTROPHIC = [
    ("(a+)+$", "a" * 1023 + "!"),
    ("(a|aa)+$", "a" * 1023 + "!"),
    (r"\d*\d*\d*x", "1" * 1024),
    ("(.*a){12}", "a" * 11 + "b" * 1013),
]
_UNSUPPORTED = [r"(a)\1", "(?=a)", r"(?a:\w)"]
_ACCEPTED_TIMED = [
    # quadratic under the stdlib `re` (about 5 ms on a failing window); linear on RE2
    (r"(\d+)\s*$", "1" * 1023 + "x"),
    (r"Final: (\w+)", "Final: " * 146 + "xx"),
    (r"\\boxed\{([^{}]*)\}", "\\boxed{" * 146 + "x"),
    (r"(?P<ans>[A-D])\)", "A" * 1024),
]


def _args(pattern: Any, **more: Any) -> dict[str, Any]:
    return {"pattern": pattern, **more}


def _check(args: dict[str, Any]) -> None:
    find("regex@1").check_args(args)


def _builtin_run(spec: dict[str, Any], texts: list[str]) -> CombineOutcome:
    return run(spec_text(spec), context_text(texts), registry=BUILTIN_OPERATORS)


def _voted(value: str) -> StageResult:
    return StageResult(value, "voted")


# --- RX#1: RE2 runs in linear time ------------------------------------------------------------


def _best_of_three(pattern: str, text: str, **more: Any) -> float:
    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        stage("regex@1", text, _args(pattern, **more))
        best = min(best, time.perf_counter() - started)
    return best


@pytest.mark.parametrize(("pattern", "text"), _CATASTROPHIC)
def test_catastrophic_patterns_run_in_linear_time(pattern: str, text: str) -> None:
    assert len(text) <= 1024
    _check(_args(pattern))
    best = _best_of_three(pattern, text)
    assert best < 0.005, f"{pattern} took {best:.5f}s"


@pytest.mark.parametrize("pattern", _UNSUPPORTED)
def test_re2_unsupported_syntax_is_spec_invalid(pattern: str) -> None:
    with pytest.raises(SpecInvalid) as raised:
        _check(_args(pattern))
    assert "RE2" in str(raised.value)
    assert pattern not in str(raised.value)


@pytest.mark.parametrize(("pattern", "text"), _ACCEPTED_TIMED)
def test_accepted_patterns_finish_under_5ms_on_worst_input(pattern: str, text: str) -> None:
    assert len(text) <= 1024
    _check(_args(pattern))
    best = min(_best_of_three(pattern, text) for _ in range(2))
    assert best < 0.005, f"{pattern} took {best:.5f}s"


# --- RX#2: the args --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        _args("bad(group"),
        _args(""),
        _args("a" * 257),
        _args(5),
        {"pattern": "secret_xyz", "flags": "i"},
        {"group": 0},
        _args("secret_xyz", ignore_case="yes"),
        _args("secret_xyz", occurrence="middle"),
    ],
    ids=[
        "does-not-compile",
        "empty",
        "too-long",
        "not-a-string",
        "unknown-key",
        "no-pattern",
        "ignore-case-not-bool",
        "occurrence-unknown",
    ],
)
def test_regex_pattern_that_does_not_compile_is_spec_invalid(args: dict[str, Any]) -> None:
    with pytest.raises(SpecInvalid) as raised:
        _check(args)
    pattern = args.get("pattern")
    if isinstance(pattern, str) and pattern:
        assert pattern not in str(raised.value)


def test_regex_spec_invalid_is_raised_before_any_member_is_read() -> None:
    def crash(text: str, args: Any, /) -> StageResult:
        raise AssertionError("a member was read")

    descriptors = tuple(
        dataclasses.replace(d, run=crash) if d.id == "regex@1" else d for d in BUILTIN_REGISTRATIONS
    )
    spec = vote_spec(
        2,
        extract={"op": "regex@1", "args": _args("bad(group")},
        normalize={"op": "text@1", "args": {}},
        reduce={"op": "mode@1", "args": {}},
        select={"op": "first_holder@1", "args": {}},
    )
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context_text(["a", "b"]), registry=OperatorRegistry(descriptors))
    assert caught.value.code == "combine_spec_invalid"


_FINAL = _args(r"Final: (\w+)", group=1)


def test_regex_reads_text_with_a_lone_surrogate_without_failing() -> None:
    # JSON can carry "\ud800"; RE2 takes UTF-8 only, so the window reads it as U+FFFD.
    text = "x\ud800y Final: B"
    assert stage("regex@1", text, _FINAL) == _voted("B")
    assert stage("regex@1", "a\ud800b", _args("(a.b)", group=1)) == _voted("a\ufffdb")
    with pytest.raises(SpecInvalid):
        _check(_args("a\ud800"))


# --- RE2 options (RX-D1, RX-D2, RX-D3, RX-D4, RX-D5) -----------------------------------------


def test_a_rejected_pattern_is_never_written_to_stderr(capfd: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SpecInvalid) as raised:
        _check(_args("(?=x)"))
    captured = capfd.readouterr()
    assert "(?=x)" not in captured.err
    assert "(?=x)" not in captured.out
    assert "(?=x)" not in str(raised.value)


def test_dollar_is_the_end_of_text_under_re2() -> None:
    # WHY pinned: stdlib `$` also matched before a final newline; RE2's `$` does not.
    assert stage("regex@1", "Final: B\n", _args(r"Final: (\w)$", group=1)) == (
        StageResult(None, "no_match")
    )
    assert stage("regex@1", "Final: B\n", _args(r"Final: (\w)\s*$", group=1)) == (
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
        _check(_args(pattern))
    assert pattern not in str(raised.value)


def test_a_pattern_just_under_the_program_cap_stays_fast() -> None:
    args = _args(r".{0,300}x")
    _check(args)
    text = "a" * 1023 + "!"
    best = min(_best_of_three(pattern=args["pattern"], text=text) for _ in range(3))
    assert best < 0.005, f"{best * 1000:.2f} ms"
