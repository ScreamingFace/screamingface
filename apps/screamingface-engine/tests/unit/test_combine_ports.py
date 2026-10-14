"""Characterization of the combine ports (OME-1289 E4a, unit 1, U1-1).

FEATURE: the shared pure helpers and value types every combine operator builds on.
These tests describe the committed ``combine/ports.py``; they pass at once by design.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from screamingface_engine.combine.ports import (
    ACCOUNTING_SIGNALS,
    FIELD_PATH,
    CombineInput,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    Selection,
    SignalRead,
    StageResult,
    accepted,
    canonical_decimal,
    decode_json_reply,
    finite_float,
    is_signal_key,
    loads_bounded,
    rejected,
    utf8_exceeds,
    walk_field_path,
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


# --- the field-path grammar, the JSON reply reader and the signal keys (gap-closure unit 1) ---


@pytest.mark.parametrize("path", ["a", "a.b[0]", "[0].x", "a_1.b2", "a[0][1]"])
def test_field_path_accepts(path: str) -> None:
    assert FIELD_PATH.fullmatch(path) is not None


@pytest.mark.parametrize("path", ["", ".a", "a..b", "a[01]", "a-b", "a.", "a[]", "1a", "a[-1]"])
def test_field_path_rejects(path: str) -> None:
    assert FIELD_PATH.fullmatch(path) is None


def test_field_path_grammar_and_walk_match_json_field() -> None:
    document = {"a": {"b": [10, {"c": True}]}, "list": [[1, 2], [3]]}
    assert walk_field_path(document, "a.b[0]") == (True, 10)
    assert walk_field_path(document, "a.b[1].c") == (True, True)
    assert walk_field_path(document, "list[0][1]") == (True, 2)
    assert walk_field_path([5, 6], "[1]") == (True, 6)
    for missing in ("a.x", "a.b[2]", "list[1][1]", "a.b.c", "[0]"):
        assert walk_field_path(document, missing) == (False, None)


def test_decode_json_reply_reads_whole_text_then_last_fence() -> None:
    assert decode_json_reply(' \n{"a": 1}\t') == {"a": 1}
    fenced = 'first ```json\n{"a": 1}\n``` then ```json\n{"a": 2}\n``` done'
    assert decode_json_reply(fenced) == {"a": 2}
    for bad in ("no json at all", '```json\n{"a": 1}', "NaN", "[" * 100000):
        with pytest.raises(ValueError):
            decode_json_reply(bad)


def test_signal_keys_are_the_accounting_keys_and_field_paths() -> None:
    assert ACCOUNTING_SIGNALS == ("cost_usd", "latency_ms", "tokens_in", "tokens_out")
    for key in (*ACCOUNTING_SIGNALS, "score:judge", "field:c", "field:a.b[0]", "field:[0].x"):
        assert is_signal_key(key)
    # the rest are not signals at all.
    for key in ("logprob_mean", "field:", "field:a..b", "Cost_usd", "", 1, None):
        assert not is_signal_key(key)


def _reduce(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    return Reduction()


def _select(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    return Selection(chosen=())


def _hook(args: OpArgs) -> SignalRead:
    return SignalRead("cost_usd")


def test_only_a_reduce_operator_may_declare_a_signal_read() -> None:
    with pytest.raises(ValueError):
        OperatorDescriptor("late_read", 1, "select", "s", _select, signal_read=_hook)
    descriptor = OperatorDescriptor("early_read", 1, "reduce", "s", _reduce, signal_read=_hook)
    assert descriptor.signal_read is _hook
    assert "signal_read" not in descriptor.catalog_entry()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3, 3.0),
        (Decimal("0.0042"), 0.0042),
        (10**400, None),
        (float("inf"), None),
        (Decimal("NaN"), None),
        (True, None),
        ("1.5", None),
        (None, None),
    ],
)
def test_finite_float_is_the_one_finite_number_rule(value: object, expected: float | None) -> None:
    assert finite_float(value) == expected
