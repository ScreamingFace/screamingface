"""A ``filter@1`` step pairs only with ``kept@1`` (E4b part 2, review P2 #1).

FEATURE: the threshold form of ``filter@1`` gives a member with no signal the mark 0, and its
evidence row says ``excluded`` / ``no_signal``. Only ``kept@1`` reads the marks as pass or miss; any
other select step reads them as scores and can choose the excluded member.
STORY: as a spec author, a ``filter@1`` with another select is refused as ``combine_spec_invalid``,
so the engine never crashes on its own evidence check.
INVARIANT: an excluded member is never chosen (CE-I3).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from combine_fields_support import step
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import SpecInvalid

_THRESHOLD = step("filter@1", key="field:confidence", cmp="ge", value=0.5)
# member_1 has no confidence: the filter marks it 0 and its row is excluded / no_signal.
_OUTPUTS = ["{}", json.dumps({"confidence": 0.8}), json.dumps({"confidence": 0.2})]


def _spec(reducer: str, select: dict[str, Any]) -> dict[str, Any]:
    return vote_spec(
        3, reducer=reducer, extract=None, normalize=None, reduce=_THRESHOLD, select=select
    )


@pytest.mark.parametrize(
    ("reducer", "select"),
    [
        ("rank", step("top_k@1", k=3)),
        ("pick", step("best_holder@1", order="min")),
    ],
    ids=["rank-top_k", "pick-best_holder-min"],
)
def test_filter_with_another_select_is_spec_invalid(reducer: str, select: dict[str, Any]) -> None:
    with pytest.raises(SpecInvalid) as caught:
        run(spec_text(_spec(reducer, select)), context_text(_OUTPUTS), registry=BUILTIN_OPERATORS)

    assert caught.value.code == "combine_spec_invalid"
    assert "filter@1" in str(caught.value)


def test_filter_with_kept_still_runs() -> None:
    outcome = run(
        spec_text(_spec("filter", step("kept@1"))),
        context_text(_OUTPUTS),
        registry=BUILTIN_OPERATORS,
    )

    assert outcome.evidence.chosen == ["member_2"]
    assert [(row.status, row.reason) for row in outcome.evidence.members] == [
        ("excluded", "no_signal"),
        ("answered", None),
        ("answered", None),
    ]
