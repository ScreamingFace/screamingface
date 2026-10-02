"""The v1 extractors read one raw value out of one member text (OME-1289, E4a, unit 2).

FEATURE: a member's free text becomes one comparable candidate answer, deterministically.
STORY: as an author of a majority-vote Candidate, I choose how the answer is read from a reply.
"""

from __future__ import annotations

import time

import pytest
from combine_golden_support import find, stage

from screamingface_engine.combine import ports
from screamingface_engine.combine.operators import extract
from screamingface_engine.combine.ports import OpArgs, SpecInvalid, StageResult, is_signal_key


def _path(path: str) -> OpArgs:
    return {"path": path}


def test_each_required_extractor() -> None:
    text = "\u2026 so x = 9, final \\boxed{12}"
    assert stage("last_number@1", text) == StageResult("12", "voted")
    assert stage("boxed@1", text) == StageResult("12", "voted")
    assert stage("json_field@1", '{"answer": {"value": 7}}', _path("answer.value")) == (
        StageResult("7", "voted")
    )
    assert stage("last_line@1", "a\n\nfinal: B\n  \n") == StageResult("final: B", "voted")
    assert stage("whole@1", "  Paris. ") == StageResult("  Paris. ", "voted")


def test_last_number_reads_thousands_separators() -> None:
    raw = stage("last_number@1", "The total is $1,200.")
    assert raw == StageResult("1,200", "voted")
    assert raw.value is not None
    assert stage("numeric@1", raw.value) == StageResult("1200", "voted")


def test_last_number_returns_the_whole_comma_run_and_numeric_judges_the_grouping() -> None:
    cases = {
        "Total: 1,00,000": "1,00,000",
        "1,2345": "1,2345",
        "12,345,6789": "12,345,6789",
        "1,23": "1,23",
        "$1,200": "1,200",
        "3.5e10": "10",
    }
    for text, raw in cases.items():
        assert stage("last_number@1", text) == StageResult(raw, "voted"), text
    for raw in ("1,00,000", "1,2345", "12,345,6789", "1,23"):
        assert stage("numeric@1", raw) == StageResult(None, "not_numeric"), raw
    assert stage("numeric@1", "1,200") == StageResult("1200", "voted")


def test_last_number_empty_and_bounded() -> None:
    assert stage("last_number@1", "no digits") == StageResult(None, "empty")
    assert stage("last_number@1", "9" * 200) == StageResult("9" * 128, "voted")


def test_boxed_reads_last_and_nested_braces() -> None:
    assert stage("boxed@1", "\\boxed{1} then \\boxed{2}") == StageResult("2", "voted")
    assert stage("boxed@1", "\\boxed{\\frac{1}{2}}") == StageResult("\\frac{1}{2}", "voted")
    assert stage("boxed@1", "\\boxed{ 5 }") == StageResult(" 5 ", "voted")
    nested_8 = "\\boxed{" + "{" * 7 + "x" + "}" * 8
    assert stage("boxed@1", nested_8).status == "voted"
    nested_9 = "\\boxed{" + "{" * 8 + "x" + "}" * 9
    assert stage("boxed@1", nested_9) == StageResult(None, "empty")
    # only the LAST \boxed{ counts: an unclosed last box is empty, though an earlier one closed.
    assert stage("boxed@1", "\\boxed{1} \\boxed{2") == StageResult(None, "empty")
    for text in ("\\boxed{}", "\\boxed{12", "no box"):
        assert stage("boxed@1", text) == StageResult(None, "empty")


def test_json_field_reads_path_and_fenced_block() -> None:
    assert stage("json_field@1", '{"a": [{"b": 1}, {"b": "x"}]}', _path("a[1].b")) == (
        StageResult("x", "voted")
    )
    assert stage("json_field@1", '[{"a":1}]', _path("[0].a")) == StageResult("1", "voted")
    fenced = 'Here you go:\n```json\n{"answer": 7}\n```\nDone.'
    assert stage("json_field@1", fenced, _path("answer")) == StageResult("7", "voted")
    two = '```json\n{"answer": 1}\n```\nno, rather\n```json\n{"answer": 2}\n```'
    assert stage("json_field@1", two, _path("answer")) == StageResult("2", "voted")


def test_json_field_value_forms() -> None:
    cases = {"null": None, '""': None, "[1,2]": "[1,2]", "true": "true", "7.50": "7.5"}
    for text, value in cases.items():
        result = stage("json_field@1", f'{{"v": {text}}}', _path("v"))
        assert result.value == value, text
        assert result.status == ("voted" if value is not None else "empty")
    assert stage("json_field@1", '"hello"', _path("[0]")) == StageResult(None, "field_missing")


def test_json_field_statuses_not_json_and_field_missing() -> None:
    assert stage("json_field@1", "answer: 7", _path("answer")) == StageResult(None, "not_json")
    assert stage("json_field@1", "", _path("a")) == StageResult(None, "not_json")
    assert stage("json_field@1", "NaN", _path("a")) == StageResult(None, "not_json")
    assert stage("json_field@1", "```json\n{oops\n```", _path("a")) == (
        StageResult(None, "not_json")
    )
    assert stage("json_field@1", '{"other": 1}', _path("answer")) == (
        StageResult(None, "field_missing")
    )
    assert stage("json_field@1", "[1]", _path("[3]")) == StageResult(None, "field_missing")
    assert stage("json_field@1", '{"a": 1}', _path("a.b")) == StageResult(None, "field_missing")


def test_json_field_rejects_depth_over_64() -> None:
    for depth in (65, 1000, 100_000):
        text = "[" * depth + "]" * depth
        assert stage("json_field@1", text, _path("[0]")) == StageResult(None, "not_json")
    at_limit = "[" * 64 + "]" * 64
    assert stage("json_field@1", at_limit, _path("[0]")) == (
        StageResult("[" * 63 + "]" * 63, "voted")
    )


def test_json_field_args_take_exactly_one_valid_path() -> None:
    descriptor = find("json_field@1")
    descriptor.check_args({"path": "a.b[0]"})
    descriptor.check_args({"path": "[0].a"})
    bad: list[OpArgs] = [
        {},
        {"path": 1},
        {"path": "a", "extra": "b"},
        {"path": ""},
        {"path": "a."},
        {"path": "a[01]"},
        {"path": "1a"},
        {"path": "a b"},
    ]
    for args in bad:
        with pytest.raises(SpecInvalid):
            descriptor.check_args(args)


def test_json_field_drops_a_number_json_cannot_hold() -> None:
    result = stage("json_field@1", '{"v": 1e999}', _path("v"))
    assert result == StageResult(None, "not_json")


def test_last_line_skips_blank_lines() -> None:
    assert stage("last_line@1", "a\n\nfinal: B\n  \n") == StageResult("final: B", "voted")
    assert stage("last_line@1", "one line") == StageResult("one line", "voted")
    assert stage("last_line@1", "x\r\ny\r\n") == StageResult("y", "voted")
    assert stage("last_line@1", "  indented  ") == StageResult("indented", "voted")
    assert stage("last_line@1", "\n\n  \n") == StageResult(None, "empty")


def test_whole_keeps_the_text_and_rejects_blank() -> None:
    assert stage("whole@1", "  Paris. ") == StageResult("  Paris. ", "voted")
    assert stage("whole@1", "") == StageResult(None, "empty")
    assert stage("whole@1", "   \n") == StageResult(None, "empty")


def test_only_json_field_takes_args() -> None:
    for op_id in (
        "last_number@1",
        "boxed@1",
        "last_line@1",
        "whole@1",
        "set@1",
        "inspect_number@1",
        "inspect_aime@1",
        "inspect_numeric@1",
    ):
        with pytest.raises(SpecInvalid, match="no args"):
            find(op_id).check_args({"x": 1})


_MIB = 1024 * 1024
_HOSTILE = {
    "comma_ones": "1," * (_MIB // 2),
    "boxed_repeated": "\\boxed{" * 149796,
    "boxed_then_braces": "\\boxed{" + "{}" * 500000,
    "open_brackets": "[" * _MIB,
    "newlines": "\n" * _MIB,
    "letters": "a" * _MIB,
}


_HOSTILE_ARGS: dict[str, OpArgs] = {
    "json_field@1": _path("a"),
    "regex@1": {"pattern": "Final: (\\w+)"},
}


@pytest.mark.parametrize(
    "op_id", ["last_number@1", "boxed@1", "json_field@1", "regex@1", "last_line@1", "whole@1"]
)
def test_extractors_finish_under_50ms_on_hostile_1mib_input(op_id: str) -> None:
    args = _HOSTILE_ARGS.get(op_id, {})
    for name, text in _HOSTILE.items():
        best = float("inf")
        for _ in range(3):
            started = time.perf_counter()
            stage(op_id, text, args)
            best = min(best, time.perf_counter() - started)
        assert best < 0.05, f"{op_id} took {best:.4f}s on {name}"


def test_json_field_reads_paths_through_the_ports_walk() -> None:
    assert not hasattr(extract, "_walk")
    assert not hasattr(extract, "_decode")
    assert not hasattr(extract, "_PATH")
    assert extract.walk_field_path is ports.walk_field_path
    assert extract.decode_json_reply is ports.decode_json_reply


@pytest.mark.parametrize("path", ["a", "a.b[0]", "[0].a", "", "a.", "a[01]", "1a", "a b", "a..b"])
def test_json_field_paths_are_the_field_signal_grammar(path: str) -> None:
    try:
        find("json_field@1").check_args(_path(path))
        accepted = True
    except SpecInvalid:
        accepted = False
    assert accepted == is_signal_key("field:" + path)
