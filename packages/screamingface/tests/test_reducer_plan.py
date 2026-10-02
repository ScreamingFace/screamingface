"""The combine spec is built from one reducer plan (OME-1289 gap, block-api delta 1).

GUARD: this passes at once. The refactor to `_ReducerPlan` keeps every existing golden; this test
pins that a reducer needs only `_plan` and `_from_spec`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from _reducer_fixtures import fixture_operators

from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.reducer import Reducer, _ReducerPlan, _Step, _Steps


class _OnlyAPlan(Reducer):
    """A test-only reducer that implements nothing beyond the two abstract methods."""

    name = "vote"

    def _plan(self) -> _ReducerPlan:
        steps = _Steps(
            extract=_Step("last_number"),
            normalize=_Step("numeric"),
            reduce=_Step("mode"),
            select=_Step("first_holder"),
        )
        return _ReducerPlan("vote", "answer", steps, weights=(1, 2, 3.5))  # type: ignore[arg-type]

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Reducer:
        del spec
        return cls()


def test_combine_spec_reads_only_the_reducer_plan() -> None:
    text = combine_spec_text(_OnlyAPlan(), member_count=3, operators=fixture_operators())

    assert json.loads(text) == {
        "schema": "screamingface.combine-spec.v1",
        "reducer": "vote",
        "members": ["member_1", "member_2", "member_3"],
        "extract": {"op": "last_number@2", "args": {}},
        "normalize": {"op": "numeric@1", "args": {}},
        "reduce": {"op": "mode@1", "args": {}},
        "select": {"op": "first_holder@1", "args": {}},
        "weights": {"member_1": 1.0, "member_2": 2.0, "member_3": 3.5},
    }
    assert text.startswith('{"extract":')
    reducer = _OnlyAPlan()
    assert reducer._python() == f"sf.{reducer!r}"
