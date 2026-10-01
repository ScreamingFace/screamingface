"""Characterization of the combine ports (OME-1289 E4a, unit 1, U1-1).

FEATURE: the shared pure helpers and value types every combine operator builds on.
These tests describe the committed ``combine/ports.py``; they pass at once by design.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from screamingface_engine.combine.ports import (
    OperatorDescriptor,
    StageResult,
    accepted,
    canonical_decimal,
    loads_bounded,
    rejected,
    utf8_exceeds,
)


def _nested(depth: int) -> str:
    return "[" * depth + "]" * depth


def test_loads_bounded_rejects_nan_depth_over_64_and_duplicate_keys() -> None:
    for bad in ("NaN", "Infinity", "-Infinity", _nested(65), "[" * 100000):
        with pytest.raises(ValueError):
            loads_bounded(bad)
    with pytest.raises(ValueError):
        loads_bounded('{"a":1,"a":2}', unique_keys=True)
    assert loads_bounded('{"a":1,"a":2}') == {"a": 2}
    assert loads_bounded(_nested(64)) is not None


def test_canonical_decimal_forms() -> None:
    cases = {
        "9.00": "9",
        "1E+3": "1000",
        "-0.0": "0",
        "0.50": "0.5",
        "1E-3": "0.001",
    }
    for source, expected in cases.items():
        assert canonical_decimal(Decimal(source)) == expected


def test_utf8_exceeds_counts_bytes_not_chars() -> None:
    limit = 1000
    assert utf8_exceeds("é" * (limit // 2 + 1), limit)
    assert not utf8_exceeds("é" * (limit // 2), limit)
    assert not utf8_exceeds("\ud800", limit)  # a lone surrogate must not crash


def test_stage_result_value_iff_voted() -> None:
    assert accepted("x") == StageResult("x", "voted")
    assert rejected("empty") == StageResult(None, "empty")
    with pytest.raises(ValueError):
        StageResult(None, "voted")
    with pytest.raises(ValueError):
        StageResult("x", "empty")


@pytest.mark.parametrize(
    ("name", "version", "stage"),
    [
        ("Bad", 1, "extract"),
        ("ok_name", 0, "extract"),
        ("ok_name", 1_000_000, "extract"),
        ("ok_name", True, "extract"),
        ("ok_name", 1, "bogus"),
    ],
    ids=["upper-name", "version-zero", "version-too-big", "version-bool", "bad-stage"],
)
def test_descriptor_rejects_bad_name_version_or_stage(name: str, version: int, stage: str) -> None:
    with pytest.raises(ValueError):
        OperatorDescriptor(name, version, stage, "s", lambda text, args: accepted(text))  # type: ignore[arg-type]
