"""The v1 extractors read one raw value out of one member text (OME-1289, E4a, unit 2).

FEATURE: a member's free text becomes one comparable candidate answer, deterministically.
STORY: as an author of a majority-vote Candidate, I choose how the answer is read from a reply.
"""

from __future__ import annotations

import time

import pytest
from combine_golden_support import find, stage

from screamingface_engine.combine.ports import OpArgs, SpecInvalid, is_signal_key


def _path(path: str) -> OpArgs:
    return {"path": path}


def test_json_field_args_take_exactly_one_valid_path() -> None:
    descriptor = find("json_field@1")
    bad: list[OpArgs] = [
        {},
        {"path": 1},
        {"path": "a", "extra": "b"},
    ]
    for args in bad:
        with pytest.raises(SpecInvalid):
            descriptor.check_args(args)


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


@pytest.mark.parametrize("path", ["a", "a.b[0]", "[0].a", "", "a.", "a[01]", "1a", "a b", "a..b"])
def test_json_field_paths_are_the_field_signal_grammar(path: str) -> None:
    try:
        find("json_field@1").check_args(_path(path))
        accepted = True
    except SpecInvalid:
        accepted = False
    assert accepted == is_signal_key("field:" + path)
