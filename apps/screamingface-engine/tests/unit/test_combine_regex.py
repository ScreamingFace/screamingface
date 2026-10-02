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
    ("(a+){10}$", "a" * 1023 + "!"),
    ("(a+)+$", "a" * 1023 + "!"),
    ("(a|aa)+$", "a" * 1023 + "!"),
    ("(a|aa){1,60}$", "a" * 1023 + "!"),
    ("(?:a+)?(?:a+)?(?:a+)?$", "a" * 1023 + "!"),
    (r"\d*\d*\d*x", "1" * 1024),
    ("[^x]+X+[^x]+X+$", "aX" * 512),
    ("(.*a){12}", "ab" * 512),
]
_UNSUPPORTED = [r"(a)\1", "(?=a)", "(?!a)", "(?<=a)b", "(?<!a)b", "a{1,9999}", r"(?a:\w)"]
_ACCEPTED_TIMED = [
    (r"Final: (\w+)", "Final: " * 146 + "xx"),
    (r"ANSWER:\s*([A-Da-d])", "ANSWER:" + " " * 1017),
    (r"\\boxed\{([^{}]*)\}", "\\boxed{" * 146 + "x"),
    (r"answer is (\w+)", "answer is " * 102 + "!!!!"),
    (r'"answer":\s*"([^"]*)"', '"answer": "' + "a" * 1011),
    (r"(\d+(?:\.\d+)?)", "1." * 512),
    (r"#### (-?[0-9,]+)", "#### " + "1" * 1019),
    (r"(?P<ans>[A-D])\)", "A" * 1024),
    # quadratic under the stdlib `re` (about 5 ms on a failing window); linear on RE2
    (r"(\d+)\s*$", "1" * 1023 + "x"),
    ("[a-z]+[0-9]+", "a" * 1024),
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


# --- RX#3 ------------------------------------------------------------------------------------


def test_regex_group_must_exist() -> None:
    for group in (2, "name", True, -1):
        with pytest.raises(SpecInvalid):
            _check(_args(r"(\w+)", group=group))
    _check(_args(r"(?P<ans>\w+)", group="ans"))
    _check(_args(r"(\w+)", group=0))
    _check(_args(r"(\w+)", group=1))


# --- RX#4 to RX#6 ----------------------------------------------------------------------------

_FINAL = _args(r"Final: (\w+)", group=1)


def _final_vote(count: int) -> dict[str, Any]:
    return vote_spec(
        count,
        extract={"op": "regex@1", "args": _FINAL},
        normalize={"op": "text@1", "args": {}},
        reduce={"op": "mode@1", "args": {}},
        select={"op": "first_holder@1", "args": {}},
    )


def test_regex_takes_last_match_group_by_default() -> None:
    assert stage("regex@1", "Final: A\nFinal: B", _FINAL) == _voted("B")
    assert stage("regex@1", "Final: A\nFinal: B", {**_FINAL, "occurrence": "first"}) == _voted("A")
    texts = ["thinking... Final: B", "Final: b", "Final: c"]
    outcome = _builtin_run(_final_vote(3), texts)
    assert outcome.output == texts[0]
    evidence = outcome.evidence
    assert [(row.value, row.holders) for row in evidence.tally or []] == [
        ("b", ["member_1", "member_2"]),
        ("c", ["member_3"]),
    ]


def test_regex_no_match_is_fail_no_match() -> None:
    assert stage("regex@1", "no marker", _FINAL) == StageResult(None, "no_match")
    outcome = _builtin_run(_final_vote(3), ["Final: A", "nothing here", "Final: A"])
    rows = outcome.evidence.members
    assert (rows[1].status, rows[1].reason) == ("fail", "no_match")
    assert outcome.evidence.dropped == 1
    assert outcome.evidence.result.status == "answered"


def test_regex_scans_only_last_1024_characters() -> None:
    args = _args(r"Final: ([A-Z])", group=1)
    assert stage("regex@1", "Final: A" + "x" * 1024, args) == StageResult(None, "no_match")
    assert stage("regex@1", "Final: A" + "x" * 1016, args) == _voted("A")
    assert stage("regex@1", "Final: AB" + "x" * 1016, args) == StageResult(None, "no_match")


# --- RX#7: RE2's Unicode rules ----------------------------------------------------------------


def test_regex_unicode_rules_are_pinned_to_re2() -> None:
    # RE2: \w and \d are ASCII; \p{L} and \p{N} name the Unicode classes.
    no_match = StageResult(None, "no_match")
    assert stage("regex@1", "name \u00dc", _args(r"(\w+)$", group=1)) == no_match
    assert stage("regex@1", "name \u00dc", _args(r"(\w+)", group=1)) == _voted("name")
    assert stage("regex@1", "name \u00dc", _args(r"(\p{L}+)$", group=1)) == _voted("\u00dc")
    assert stage("regex@1", "total \uff11\uff12", _args(r"(\d+)", group=1)) == no_match
    assert stage("regex@1", "total \uff11\uff12", _args(r"(\p{N}+)", group=1)) == _voted(
        "\uff11\uff12"
    )
    ignore = {"ignore_case": True, "group": 1}
    assert stage("regex@1", "FINAL: B", _args("final: (b)", **ignore)) == _voted("B")
    assert stage("regex@1", "\u00dc", _args("(\u00fc)", **ignore)) == _voted("\u00dc")


def test_regex_reads_text_with_a_lone_surrogate_without_failing() -> None:
    # JSON can carry "\ud800"; RE2 takes UTF-8 only, so the window reads it as U+FFFD.
    text = "x\ud800y Final: B"
    assert stage("regex@1", text, _FINAL) == _voted("B")
    assert stage("regex@1", "a\ud800b", _args("(a.b)", group=1)) == _voted("a\ufffdb")
    with pytest.raises(SpecInvalid):
        _check(_args("a\ud800"))
