"""Every flow operator matches its hand-computed golden fixture (OME-1289, E4a, units 8 to 10).

FEATURE: an operator's behavior is frozen per ``@version``; a changed output is a new version.
STORY: as an author, a recorded judge, pick, merge or rank replays to the same answer after any
engine upgrade.

The unit 2 file (``test_combine_operators_golden.py``) holds OP-1, the one exact-set check over
every fixture under ``fixtures/combine/``. This file runs the ``flow/`` folder, which the unit 2
harness does not glob, and keeps only the checks that the two folders do not overlap and that a
fixture's stage is the operator's stage.
"""

from __future__ import annotations

import pytest
from combine_flow_support import FLOW_FIXTURE_DIR, find_builtin, load_flow_fixtures, run_flow_case
from combine_golden_support import FIXTURE_DIR, load_fixtures

_FLOW = load_flow_fixtures()
_CASES = [
    pytest.param(op_id, case, id=f"{op_id}-{case['name']}")
    for op_id, fixture in sorted(_FLOW.items())
    for case in fixture["cases"]
]


def test_every_builtin_operator_has_exactly_one_golden_fixture() -> None:
    top, flow = set(load_fixtures()), set(_FLOW)
    assert flow
    assert top.isdisjoint(flow)
    for op_id, fixture in _FLOW.items():
        assert (FLOW_FIXTURE_DIR / f"{op_id}.json").is_file(), op_id
        assert not (FIXTURE_DIR / f"{op_id}.json").exists(), op_id
        assert fixture["stage"] == find_builtin(op_id).stage, op_id
        assert fixture["stage"] in ("reduce", "select"), op_id


@pytest.mark.parametrize(("op_id", "case"), _CASES)
def test_flow_golden_case_matches(op_id: str, case: dict[str, object]) -> None:
    assert run_flow_case(find_builtin(op_id), case) == case["expect"]


def test_find_builtin_names_the_missing_operator() -> None:
    with pytest.raises(LookupError, match="nope@1"):
        find_builtin("nope@1")
