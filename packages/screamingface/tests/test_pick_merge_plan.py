"""sf.Pick, sf.Merge and the projection reducer compile through the reducer plan (9S, F3)."""

from __future__ import annotations

import screamingface as sf
from screamingface._evaluation.reducer_signals import _ProjectionReducer
from screamingface.reducer import Reducer, _Step, _Steps


def test_pick_merge_and_projection_build_a_reducer_plan() -> None:
    for cls in (sf.Pick, sf.Merge, _ProjectionReducer):
        assert not hasattr(cls, "_steps")
        assert not hasattr(cls, "_kind")
        assert not hasattr(cls, "_reducer")
    assert not hasattr(Reducer, "_signals")

    merge = sf.Merge({"s": sf.FieldRule.model("p/w", prompt="W.")})._plan()
    assert len(merge.signal_calls) == 1
    writer = merge.signal_calls[0]
    assert writer.field == "s"
    assert writer.key == "writer_s"
    assert (merge.reducer, merge.kind) == ("merge", "answer")

    pick = sf.Pick("c", order="max")._plan()
    assert pick.steps.normalize == _Step("numeric@1")
    assert (pick.reducer, pick.kind, pick.signal_calls) == ("pick", "answer", ())

    projection = _ProjectionReducer("s")._plan()
    assert (projection.reducer, projection.kind) == ("project", "projection")
    assert projection.steps == _Steps(
        extract=_Step("json_object"),
        reduce=_Step("project_field", {"field": "s"}),
        select=_Step("built"),
    )
