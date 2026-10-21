"""The member label of a sample call in a nested Fusion (E4b part 7, review P7 #1).

FEATURE: the Case trace labels each model call with the member it belongs to (F8); a sample
call is one step row with no member (overview N8).
STORY: as a researcher who reads the trace of a nested Fusion with ``sf.Consistency``, I never
see a sample of one member under the label of another member.
INVARIANT defended: a sample call never takes a member label, also when an outer combine reads
the inner combine that owns the sample.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from _combine_contract import engine_operators

import screamingface as sf
from screamingface._case_views import _member_ids
from screamingface._evaluation.candidate import compile_candidate


def _nested_graph() -> dict[str, Any]:
    inner_a = sf.Fanout(
        ["prov/alpha", "prov/beta"], signals={"cons": sf.Consistency(n=2)}, name="ia"
    ) >> sf.ArgMax("cons")
    inner_b = sf.Fanout(["prov/gamma", "prov/delta"], name="ib") >> sf.Vote()
    outer = sf.Fanout([inner_a, inner_b], name="outer") >> sf.Vote()
    compiled = compile_candidate(outer, operators=engine_operators())
    return {operation.id: operation for operation in compiled.operations}


def _combine_operation(operation_id: str) -> Any:
    # _member_ids reads only the operation id and the member count of the combine evidence
    members = SimpleNamespace(members=(object(), object()))
    return SimpleNamespace(operation_id=operation_id, combine=members)


def test_nested_fusion_sample_calls_take_no_member_label() -> None:
    graph = _nested_graph()
    samples = sorted(key for key, node in graph.items() if node.kind == "sample")
    combines = [key for key, node in graph.items() if node.kind == "combine"]
    assert len(samples) == 4  # alpha and beta, n=2 each
    operations = [_combine_operation(key) for key in combines]

    member_of = _member_ids(cast(Any, operations), graph)

    assert {key: member_of.get(key) for key in samples} == dict.fromkeys(samples)
    # control: the member calls and the inner combines keep their labels
    assert member_of["op_model_1"] == "member_1"
    assert member_of["op_model_2"] == "member_2"
    assert member_of["op_synthesis_1"] == "member_1"
    assert member_of["op_synthesis_2"] == "member_2"
