"""The operator rules of the mean reducer in the combine spec (E4b, review P1 #4, erratum ER7).

FEATURE: the mean reducer is new in E4b, so it takes only its own ops: reduce `mean` or
`weighted_mean`, select `value` or `nearest` (erd section 2), by name in any version.
INVARIANT: a statistic op of the other reducer is refused, and no message repeats an op id.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from combine_support import vote_spec

from screamingface_engine.combine.ports import SpecInvalid
from screamingface_engine.combine.spec import parse_spec


def _mean(reduce: str, select: str) -> str:
    spec: dict[str, Any] = vote_spec(
        reducer="mean",
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": reduce, "args": {}},
        select={"op": select, "args": {}},
    )
    return json.dumps(spec)


@pytest.mark.parametrize(
    ("reduce", "select"),
    [
        ("fake_count@1", "value@1"),
        ("mode@1", "nearest@1"),
        ("mean@1", "fake_first@1"),
        ("weighted_mean@1", "first_holder@1"),
    ],
)
def test_the_mean_reducer_refuses_any_other_reduce_or_select_op(reduce: str, select: str) -> None:
    with pytest.raises(SpecInvalid) as caught:
        parse_spec(_mean(reduce, select))
    assert caught.value.code == "combine_spec_invalid"
    assert reduce not in str(caught.value) and select not in str(caught.value)


@pytest.mark.parametrize(
    ("reduce", "select"),
    [("mean@1", "value@1"), ("mean@2", "nearest@1"), ("weighted_mean@1", "nearest@2")],
)
def test_the_mean_reducer_accepts_its_own_ops_in_any_version(reduce: str, select: str) -> None:
    assert parse_spec(_mean(reduce, select)).reducer == "mean"


def test_a_median_op_of_another_version_under_the_mean_reducer_is_refused() -> None:
    with pytest.raises(SpecInvalid, match="forbids this statistic reduce step") as caught:
        parse_spec(_mean("median@2", "value@1"))
    assert caught.value.code == "combine_spec_invalid"
    assert "median@2" not in str(caught.value)
