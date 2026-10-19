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
from collections.abc import Callable

import pytest
from combine_golden_support import stage

from screamingface_engine.combine.operators import extract
from screamingface_engine.combine.operators._inspect_vendor import remove_boxed_from_ans


def test_unbox_equals_the_vendored_remove_boxed() -> None:
    rng = random.Random(1289)
    pieces = ["\\boxed{", "}", "{", "x", "1", " ", "\\"]
    lines = ["".join(rng.choice(pieces) for _ in range(rng.randint(0, 12))) for _ in range(5000)]
    lines += ["\\boxed{\\boxed{5}}", "\\boxed{}", "a}\\boxed{b", "\\boxed{1} and \\boxed{2}"]
    for line in lines:
        assert extract._unbox(line) == remove_boxed_from_ans(line), line


#: The repeating unit of each hostile line; the check reads each at a small and a large size.
_HOSTILE_UNITS = {
    "digit_words": "1a ",
    "unicode_words": "é ",
    "boxed_run": "\\boxed{",
}
_SMALL_BYTES = 32 * 1024
_LARGE_BYTES = 4 * _SMALL_BYTES
#: Linear work grows about 4x from the small line to the large one, quadratic work about 16x.
#: 8x sits between the two with room for noise either way.
#: AIDEV-NOTE: two sizes only see the dominant term. A rule with a large linear cost and a
#: small quadratic one grows somewhere between 4x and 16x (a real O(n^2) change measured
#: 5.1x to 7.0x in review) and passes; the old fixed 5s budget missed it too. Fitting the
#: slope over three or more sizes would catch it, at the cost of longer reads.
_MAX_GROWTH = 8.0
#: Below this much CPU on the large line there is nothing to measure: a fixed cost dominates
#: and the ratio is noise (boxed_run reads in about 2ms). It can only pass a fast read, never
#: fail a slow one, so machine load cannot turn it into a failure.
_TOO_FAST_TO_MEASURE = 0.05


def _cpu_seconds(read: Callable[[str], object], text: str) -> float:
    """The fastest of two reads of `text`, in CPU seconds of this process."""

    best = float("inf")
    for _ in range(2):
        started = time.process_time()
        read(text)
        best = min(best, time.process_time() - started)
    return best


def _small_and_large_seconds(read: Callable[[str], object], unit: str) -> tuple[float, float]:
    """CPU seconds to read a line made of `unit` at the small size, then at 4x that size."""

    small = _cpu_seconds(read, unit * (_SMALL_BYTES // len(unit)))
    large = _cpu_seconds(read, unit * (_LARGE_BYTES // len(unit)))
    return small, large


def _stays_linear(small: float, large: float) -> bool:
    """Does a 4x longer line cost about 4x, not 16x?

    Worked example: inspect_number@1 on unicode_words costs 0.057s at 32 KB and 0.231s at
    128 KB, growth 4.0, so it stays linear; the quadratic stand-in below costs 0.016s and
    0.256s, growth 16, so it does not.
    """

    return large < _TOO_FAST_TO_MEASURE or large <= _MAX_GROWTH * small


@pytest.mark.parametrize("op_id", ["inspect_number@1", "inspect_aime@1"])
def test_inspect_rules_stay_linear_on_hostile_input(op_id: str) -> None:
    # F10 and F11: the exact Inspect semantics cost O(words) but never O(n^2); the vendored boxed
    # regex alone grows 16x on the last text (0.27s at 32 KB, 4.3s at 128 KB).
    # WHY growth, not a CPU budget: the engine gate runs the suite under `pytest -n auto` with
    # coverage, where one read of the 256 KB unicode line cost over 5s of CPU on linear code,
    # so a fixed 5s budget failed CI on unchanged code. How fast the machine is cancels out of
    # the ratio; how the cost grows with the input is what F10 and F11 are about.
    for name, unit in _HOSTILE_UNITS.items():
        small, large = _small_and_large_seconds(lambda text: stage(op_id, text), unit)
        # The times are in the message so a reader can tell noise (8.3x) from a regression (16x).
        assert _stays_linear(small, large), (
            f"{op_id} grows faster than linear on {name}: {small:.3f}s at "
            f"{_SMALL_BYTES // 1024} KB, {large:.3f}s at {_LARGE_BYTES // 1024} KB, "
            f"growth {large / small:.1f}x, limit {_MAX_GROWTH:.0f}x"
        )


def test_the_linearity_check_fails_a_quadratic_rule() -> None:
    # WHY: pins that the check above still catches the regression it guards. The stand-in
    # rescans the line from the start every 8 characters, so its cost grows with the square
    # of the line's length (about 16x for a 4x longer line, 0.25s at 128 KB).
    def quadratic_read(text: str) -> None:
        for end in range(0, len(text), 8):
            text.count("§", 0, end)

    assert not _stays_linear(
        *_small_and_large_seconds(quadratic_read, _HOSTILE_UNITS["unicode_words"])
    )


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
