"""The v1 normalizers turn a raw extract into one comparable value (OME-1289, E4a, unit 2).

FEATURE: members that write the same answer in different shapes still vote together.
STORY: as an author of a majority-vote Candidate, `9`, `9.0` and `$9.` count as one answer.
"""

from __future__ import annotations

import pytest
from combine_golden_support import stage

from screamingface_engine.combine.ports import StageResult


def test_numeric_groups_9_9_0_9_00_and_9_dot() -> None:
    results = [stage("numeric@1", raw) for raw in ("9", "9.0", "9.00", "9.")]
    assert [(r.status, r.value) for r in results] == [("voted", "9")] * 4


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("1e3", "1000"),
        ("1000.0", "1000"),
        ("-0", "0"),
        ("$1,200", "1200"),
        ("\u20ac5", "5"),
        ("\u00a3 3.50", "3.5"),
        ("+7", "7"),
        (".5", "0.5"),
        ("12.50.", "12.5"),
        ("100", "100"),
        ("1e-3", "0.001"),
    ],
)
def test_numeric_canonical_form_cases(raw: str, value: str) -> None:
    assert stage("numeric@1", raw) == StageResult(value, "voted")


@pytest.mark.parametrize("raw", ["twelve", "1,2", "1e100", "1" * 65, "", "1.2.3"])
def test_numeric_rejects_text_that_is_not_a_number(raw: str) -> None:
    assert stage("numeric@1", raw) == StageResult(None, "not_numeric")


def test_unicode_minus_ok_fullwidth_not_numeric() -> None:
    assert stage("numeric@1", "\u22123") == StageResult("-3", "voted")
    assert stage("numeric@1", "\uff13") == StageResult(None, "not_numeric")
    assert stage("numeric@1", "\uff11\uff12") == StageResult(None, "not_numeric")


def test_text_normalize_trims_collapses_casefolds_strips_one_period() -> None:
    assert stage("text@1", "  Paris. ") == StageResult("paris", "voted")
    assert stage("text@1", "paris") == StageResult("paris", "voted")
    assert stage("text@1", "  A   B\tC  ") == StageResult("a b c", "voted")
    assert stage("text@1", "Stra\u00dfe") == StageResult("strasse", "voted")
    assert stage("text@1", "end..") == StageResult("end.", "voted")
    assert stage("text@1", ".") == StageResult(None, "empty")


def test_identity_keeps_the_raw_value_as_it_is() -> None:
    assert stage("identity@1", " x ") == StageResult(" x ", "voted")
    assert stage("identity@1", "Paris.") == StageResult("Paris.", "voted")
