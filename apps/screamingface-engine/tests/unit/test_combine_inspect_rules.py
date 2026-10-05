"""inspect_number@1, inspect_aime@1 and inspect_numeric@1 follow Inspect's numeric rule (OME-1289).

FEATURE: members whose numeric answers Inspect would grade equal land in one tally row.
STORY: as an author of a GSM8K or AIME Candidate, "The total is $1,200." and "1200" are one
answer, and 123456 and 123457 are one answer too (Inspect compares five significant digits).
Base lane: no Inspect install; the parity with the real grader is in
``inspect/test_combine_grader_parity.py``. GP#13, F10 and F11 of the E4a gap-closure.
"""

from __future__ import annotations

import random
import time
from typing import Any

import pytest
from combine_golden_support import stage
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.operators import extract
from screamingface_engine.combine.operators._inspect_vendor import remove_boxed_from_ans
from screamingface_engine.combine.ports import StageResult


def _builtin_run(spec: dict[str, Any], texts: list[str]) -> Any:
    return run(spec_text(spec), context_text(texts), registry=BUILTIN_OPERATORS)


def test_grader_equal_texts_share_one_tally_row() -> None:
    spec = vote_spec(
        5,
        extract={"op": "inspect_number@1", "args": {}},
        normalize={"op": "inspect_numeric@1", "args": {}},
        reduce={"op": "mode@1", "args": {}},
        select={"op": "first_holder@1", "args": {}},
    )
    texts = ["The total is $1,200.", "1200", "123456", "123457", "x=42"]
    evidence = _builtin_run(spec, texts).evidence
    assert [(row.value, row.score, row.holders) for row in evidence.tally or []] == [
        ("1200", 2.0, ["member_1", "member_2"]),
        ("1.2346e+05", 2.0, ["member_3", "member_4"]),
    ]
    assert (evidence.members[4].status, evidence.members[4].reason) == ("fail", "empty")


def test_unbox_equals_the_vendored_remove_boxed() -> None:
    rng = random.Random(1289)
    pieces = ["\\boxed{", "}", "{", "x", "1", " ", "\\"]
    lines = ["".join(rng.choice(pieces) for _ in range(rng.randint(0, 12))) for _ in range(5000)]
    lines += ["\\boxed{\\boxed{5}}", "\\boxed{}", "a}\\boxed{b", "\\boxed{1} and \\boxed{2}"]
    for line in lines:
        assert extract._unbox(line) == remove_boxed_from_ans(line), line


def test_inspect_rules_read_the_last_number_word() -> None:
    assert stage("inspect_number@1", "x=42") == StageResult(None, "empty")
    assert stage("inspect_number@1", "(42)") == StageResult("(42)", "voted")
    assert stage("inspect_numeric@1", "123456") == StageResult("1.2346e+05", "voted")
    assert stage("inspect_numeric@1", "abc") == StageResult(None, "not_numeric")
    assert stage("inspect_aime@1", "$$\n\\boxed{70}\n$$") == StageResult("70", "voted")
    assert stage("inspect_aime@1", "\n\n") == StageResult(None, "empty")


_HOSTILE_LINES = {
    "digit_words": "1a " * (256 * 1024 // 3),
    "unicode_words": "é " * (256 * 1024 // 2),
    "boxed_run": "\\boxed{" * (256 * 1024 // 7),
}


@pytest.mark.parametrize("op_id", ["inspect_number@1", "inspect_aime@1"])
def test_inspect_rules_stay_linear_on_hostile_input(op_id: str) -> None:
    # F10 and F11: the exact Inspect semantics cost O(words) but never O(n^2); the vendored boxed
    # regex alone would take tens of seconds on the last text.
    # WHY CPU time and a 5s budget: the engine gate runs the suite under `pytest -n auto` with
    # coverage (OME-1444). There a worker shares the machine, so a 2s wall-clock bound failed on
    # linear code (about 1.8s of CPU per line under that load, 0.6s alone). A quadratic
    # regression still costs tens of seconds, well past this budget.
    for name, text in _HOSTILE_LINES.items():
        started = time.process_time()
        stage(op_id, text)
        assert time.process_time() - started < 5, f"{op_id} took too long on {name}"


@pytest.mark.parametrize("op_id", ["inspect_number@1", "inspect_aime@1"])
def test_inspect_rules_read_long_prose_in_a_few_milliseconds(op_id: str) -> None:
    prose = ("The quick brown fox jumps over the lazy dog. " * 1500)[: 64 * 1024]
    text = prose + " The answer is 42."
    assert stage(op_id, text).value is not None
    # WHY CPU time and a 50ms budget: under the engine gate's `pytest -n auto` with coverage, a
    # loaded machine stretched the 5ms wall-clock bound (7.1ms seen). One read costs about 1.3ms
    # of CPU alone; an O(words^2) rule on these ~13k words would cost seconds, so it still fails.
    best = float("inf")
    for _ in range(3):
        started = time.process_time()
        stage(op_id, text)
        best = min(best, time.process_time() - started)
    assert best < 0.05, f"{op_id} took {best:.5f}s of CPU"
