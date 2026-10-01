"""Every v1 operator matches its hand-computed golden fixture (OME-1289, E4a, unit 2).

FEATURE: an operator's behavior is frozen per ``@version``; a changed output is a new version.
STORY: as an author, a recorded combine replays to the same answer after any engine upgrade.

PHASE A runs the fixtures against the plugin modules' ``OPERATORS`` tuples directly.
"""

from __future__ import annotations

import pytest
from combine_golden_support import MODULE_OPERATORS, find, load_fixtures, run_case

_FIXTURES = load_fixtures()
_CASES = [
    pytest.param(op_id, case, id=f"{op_id}-{case['name']}")
    for op_id, fixture in sorted(_FIXTURES.items())
    for case in fixture["cases"]
]


def test_every_module_operator_has_one_fixture_file() -> None:
    assert set(_FIXTURES) == {descriptor.id for descriptor in MODULE_OPERATORS}
    assert len(MODULE_OPERATORS) == 15


def test_each_fixture_names_the_stage_of_its_operator() -> None:
    for op_id, fixture in _FIXTURES.items():
        assert fixture["stage"] == find(op_id).stage, op_id


@pytest.mark.parametrize(("op_id", "case"), _CASES)
def test_golden_case_matches_for_every_module_operator(op_id: str, case: dict[str, object]) -> None:
    assert run_case(find(op_id), case) == case["expect"]
