"""Every v1 operator matches its hand-computed golden fixture (OME-1289, E4a, unit 2).

FEATURE: an operator's behavior is frozen per ``@version``; a changed output is a new version.
STORY: as an author, a recorded combine replays to the same answer after any engine upgrade.

The module tests run the fixtures against the plugin modules' ``OPERATORS`` tuples directly; OP-1
at the end of the file is the one exact-set check against the built-in registry.
"""

from __future__ import annotations

import json

import pytest
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


def test_every_fixture_file_names_a_module_operator_of_its_stage() -> None:
    assert _FIXTURES
    for op_id, fixture in _FIXTURES.items():
        assert (FIXTURE_DIR / f"{op_id}.json").is_file(), op_id
        assert fixture["stage"] == find(op_id).stage, op_id


def test_every_module_operator_has_a_fixture_file() -> None:
    assert MODULE_OPERATORS
    for descriptor in MODULE_OPERATORS:
        assert (FIXTURE_DIR / f"{descriptor.id}.json").is_file(), descriptor.id


def test_find_names_the_missing_operator() -> None:
    with pytest.raises(LookupError, match="nope@1"):
        find("nope@1")


@pytest.mark.parametrize(("op_id", "case"), _CASES)
def test_golden_case_matches_for_every_module_operator(op_id: str, case: dict[str, object]) -> None:
    assert run_case(find(op_id), case) == case["expect"]


def test_golden_outputs_match_for_every_registered_operator() -> None:
    """OP-1: the one exact-set check -- every fixture file is a built-in operator, and back."""
    # WHY rglob over the whole fixture tree: later units keep their goldens in subfolders
    # (fixtures/combine/flow/), and this stays the ONE exact-set check over every built-in.
    every_fixture = {
        json.loads(path.read_text("utf-8"))["op"] for path in FIXTURE_DIR.rglob("*.json")
    }
    assert every_fixture == {descriptor.id for descriptor in BUILTIN_OPERATORS}
    for op_id, fixture in sorted(_FIXTURES.items()):
        descriptor = BUILTIN_OPERATORS.resolve(op_id, fixture["stage"])
        assert descriptor.stage == fixture["stage"], op_id
        for case in fixture["cases"]:
            assert run_case(descriptor, case) == case["expect"], (op_id, case["name"])
