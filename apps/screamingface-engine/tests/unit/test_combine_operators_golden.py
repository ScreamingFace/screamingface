"""Every v1 operator matches its hand-computed golden fixture (OME-1289, E4a, unit 2).

FEATURE: an operator's behavior is frozen per ``@version``; a changed output is a new version.
STORY: as an author, a recorded combine replays to the same answer after any engine upgrade.

The module tests run the fixtures against the plugin modules' ``OPERATORS`` tuples directly; OP-1
at the end of the file is the one exact-set check against the built-in registry. The ``flow/``
folder (units 8 to 10) runs in the same file, and its checks keep the two folders disjoint and a
fixture's stage the operator's stage.
"""

from __future__ import annotations

import json

import pytest
from combine_flow_support import FLOW_FIXTURE_DIR, find_builtin, load_flow_fixtures, run_flow_case
from combine_golden_support import (
    FIXTURE_DIR,
    MODULE_OPERATORS,
    find,
    load_fixtures,
    run_case,
)

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS

_FIXTURES = load_fixtures()
_CASES = [
    pytest.param(op_id, case, id=f"{op_id}-{case['name']}")
    for op_id, fixture in sorted(_FIXTURES.items())
    for case in fixture["cases"]
]
_FLOW = load_flow_fixtures()
_FLOW_CASES = [
    pytest.param(op_id, case, id=f"{op_id}-{case['name']}")
    for op_id, fixture in sorted(_FLOW.items())
    for case in fixture["cases"]
]


def test_every_fixture_file_names_a_module_operator_of_its_stage() -> None:
    assert _FIXTURES
    for op_id, fixture in _FIXTURES.items():
        assert (FIXTURE_DIR / f"{op_id}.json").is_file(), op_id
        assert fixture["stage"] == find(op_id).stage, op_id


def test_every_module_operator_has_a_fixture_file() -> None:
    assert MODULE_OPERATORS
    for descriptor in MODULE_OPERATORS:
        assert (FIXTURE_DIR / f"{descriptor.id}.json").is_file(), descriptor.id


@pytest.mark.parametrize(("op_id", "case"), _CASES)
def test_golden_case_matches_for_every_module_operator(op_id: str, case: dict[str, object]) -> None:
    assert run_case(find(op_id), case) == case["expect"]


def test_every_builtin_operator_has_exactly_one_golden_fixture() -> None:
    """OP-1: the one exact-set check -- every fixture file is a built-in operator, and back."""
    # WHY rglob over the whole fixture tree: later units keep their goldens in subfolders
    # (fixtures/combine/flow/), and this stays the ONE exact-set check over every built-in.
    every_fixture = {
        json.loads(path.read_text("utf-8"))["op"] for path in FIXTURE_DIR.rglob("*.json")
    }
    assert every_fixture == {descriptor.id for descriptor in BUILTIN_OPERATORS}
    for op_id, fixture in sorted(_FIXTURES.items()):
        assert BUILTIN_OPERATORS.resolve(op_id, fixture["stage"]).stage == fixture["stage"], op_id
    top, flow = set(_FIXTURES), set(_FLOW)
    assert flow
    # No silent replacement: one file for each loaded flow fixture, and the file stem is its op id.
    files = sorted(FLOW_FIXTURE_DIR.glob("*.json"))
    assert len(files) == len(_FLOW)
    assert {path.stem for path in files} == flow
    assert top.isdisjoint(flow)
    for op_id, fixture in _FLOW.items():
        assert (FLOW_FIXTURE_DIR / f"{op_id}.json").is_file(), op_id
        assert not (FIXTURE_DIR / f"{op_id}.json").exists(), op_id
        assert fixture["stage"] == find_builtin(op_id).stage, op_id
        assert fixture["stage"] in ("reduce", "select"), op_id


@pytest.mark.parametrize(("op_id", "case"), _FLOW_CASES)
def test_flow_golden_case_matches(op_id: str, case: dict[str, object]) -> None:
    assert run_flow_case(find_builtin(op_id), case) == case["expect"]
