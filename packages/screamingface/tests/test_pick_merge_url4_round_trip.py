"""A compiled Pick or Merge survives url4: replay, editable Python, tampering refusal (OME-1289)."""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators, members3
from test_judge_url4_round_trip import (
    _INVALID_REDUCER,
    _MODEL_CALLS,
    _compiled,
    _linked,
    _recovered,
)

import screamingface as sf
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.reducer import _ModelSignal

_MERGE = (
    "sf.Merge(fields={'answer': sf.FieldRule.majority(normalize='text'), "
    "'summary': sf.FieldRule.model('provider/w', prompt='Write one summary.')})"
)


def _merge() -> sf.Merge:
    return sf.Merge(
        fields={
            "answer": sf.FieldRule.majority(normalize="text"),
            "summary": sf.FieldRule.model("provider/w", prompt="Write one summary."),
        }
    )


def _shapes() -> dict[str, sf.Recipe]:
    return {
        "pick max": sf.Fusion(members3(), synthesizer=sf.Pick("confidence", order="max")),
        "pick equals text": sf.Fusion(
            members3(), synthesizer=sf.Pick("answer", equals="Yes.", normalize="text")
        ),
        "pick equals plain": sf.Fusion(members3(), synthesizer=sf.Pick("a.b[0]", equals=7)),
        "pick equals numeric": sf.Fusion(
            members3(), synthesizer=sf.Pick("n", equals="0.70", normalize="numeric")
        ),
        "merge rules only": sf.Fusion(
            members3(),
            synthesizer=sf.Merge(
                fields={
                    "answer": sf.FieldRule.majority(),
                    "score": sf.FieldRule.max(),
                    "source": sf.FieldRule.from_member(2),
                    "synonyms": sf.FieldRule.union(normalize="text"),
                }
            ),
        ),
        "merge with a model field": sf.Fusion(members3(), synthesizer=_merge()),
        "merge with two model fields": sf.Fusion(
            members3(),
            synthesizer=sf.Merge(
                fields={
                    "b": sf.FieldRule.model("provider/w", prompt="Write b.", params={"seed": 7}),
                    "a": sf.FieldRule.model("provider/x", prompt='Write "a" for $5.\nLine two.'),
                    "c": sf.FieldRule.max(),
                }
            ),
        ),
        "merge inside a pipeline": sf.Pipeline(
            [
                sf.Fusion(members3(), synthesizer=_merge()),
                sf.Fusion(
                    ["provider/d", "provider/e"],
                    synthesizer=sf.Merge(
                        fields={"s": sf.FieldRule.model("provider/y", prompt="Again.")}
                    ),
                ),
            ]
        ),
        "merge as a recipe synthesizer": sf.Fusion(
            members3(),
            synthesizer=sf.Pipeline([sf.Fusion(members3(), synthesizer=_merge()), "provider/s"]),
        ),
    }


@pytest.mark.parametrize("shape", sorted(_shapes()))
def test_pick_and_merge_round_trip(shape: str) -> None:
    compiled = _compiled(_shapes()[shape])

    assert _compiled(_recovered(compiled.url4)).url4 == compiled.url4
    replayed = _candidate_from_url4(_linked(compiled.url4))
    assert replayed.operations == compiled.operations
    assert replayed.models == compiled.models
    assert [member.operation_id for member in replayed.members] == [
        member.operation_id for member in compiled.members
    ]
    assert [member.models for member in replayed.members] == [
        member.models for member in compiled.members
    ]


def test_to_python_writes_the_reducers_as_editable_code() -> None:
    merge = sf.Url4(_compiled(sf.Fusion(members3(), synthesizer=_merge())).url4).to_python()
    assert f"synthesizer={_MERGE}," in merge
    pick = sf.Url4(
        _compiled(sf.Fusion(members3(), synthesizer=sf.Pick("confidence", order="max"))).url4
    ).to_python()
    assert "synthesizer=sf.Pick('confidence', order='max')," in pick


def test_the_recovered_reducers_equal_the_originals_field_by_field() -> None:
    originals = [
        sf.Pick("n", equals=7),
        sf.Pick("answer", equals="yes", normalize="text"),
        sf.Pick("n", order="min"),
        sf.Merge(
            fields={
                "z": sf.FieldRule.model(
                    "provider/w", prompt="Write.\n'x' $5", params={"temperature": 0, "seed": 7}
                ),
                "m": sf.FieldRule.from_member(3),
                "a": sf.FieldRule.union(normalize="numeric"),
            }
        ),
    ]
    for original in originals:
        rebuilt = _recovered(_compiled(sf.Fusion(members3(), synthesizer=original)).url4)
        assert isinstance(rebuilt, sf.Fusion)
        assert rebuilt.synthesizer == original
        assert type(rebuilt.synthesizer) is type(original)
        if isinstance(original, sf.Merge):
            assert isinstance(rebuilt.synthesizer, sf.Merge)
            assert list(rebuilt.synthesizer.fields) == list(original.fields)


def test_corrective_replay_recompiles_a_merge_member() -> None:
    loop = sf.CorrectiveLoop(
        [sf.Fusion(members3(), synthesizer=_merge()), "provider/d"],
        judge="provider/x",
        max_rounds=2,
    )
    from test_judge_url4_round_trip import _SURFACE

    from screamingface._evaluation.candidate import compile_candidate

    compiled = compile_candidate(loop, check_surface=_SURFACE, operators=flow_operators())

    assert "synthesizer=" + _MERGE in sf.Url4(compiled.url4).to_python()
    replayed = _candidate_from_url4(_linked(compiled.url4))
    assert replayed.kind == "corrective_loop"
    assert "provider/w" in replayed.models
    assert "ensemble/combine/v1" not in replayed.models
    operations = {operation.id: operation for operation in compiled.operations}
    for round_number in (1, 2):
        writer = operations[f"op_writer_{round_number}"]
        assert writer.kind == "writer"
        assert writer.label == "a+b+c write summary"
        (projection,) = writer.depends_on
        assert operations[projection].label == "a+b+c project summary"
    assert operations["op_writer_1"].depends_on != operations["op_writer_2"].depends_on


def _tamperings() -> dict[str, tuple[str, str, str]]:
    """name -> (text to replace, replacement, expected error)."""

    source = '{"binding":"writer_1","kind":"model","name":"w","named":false,"role":"writer"}'
    projection = '{"binding":"synthesis_2","kind":"reducer","name":"project"}'
    entry = f'{{"key":"writer_summary","projection":{projection},"source":{source}}}'
    return {
        "projection named vote": (
            '"kind":"reducer","name":"project"',
            '"kind":"reducer","name":"vote"',
            _INVALID_REDUCER,
        ),
        "projection reducer in the spec": (
            '"reducer":"project"',
            '"reducer":"merge"',
            _MODEL_CALLS,
        ),
        "projection field is not the key": (
            '"reduce":{"args":{"field":"summary"},"op":"project_field@1"}',
            '"reduce":{"args":{"field":"answer"},"op":"project_field@1"}',
            _MODEL_CALLS,
        ),
        "projection operator swapped": (
            '"op":"project_field@1"',
            '"op":"values@1"',
            _MODEL_CALLS,
        ),
        "writer without binding param": (
            "/provider/w?binding=writer_1&q=",
            "/provider/w?q=",
            _MODEL_CALLS,
        ),
        "writer binding param of another call": (
            "/provider/w?binding=writer_1&q=",
            "/provider/w?binding=writer_2&q=",
            _MODEL_CALLS,
        ),
        "writer context wraps the projection": (
            "/provider/w?binding=writer_1&q=($synthesis_2)",
            "/provider/w?binding=writer_1&q=({question: '$synthesis_2'})",
            _MODEL_CALLS,
        ),
        "writer reads a member too": (
            "/provider/w?binding=writer_1&q=($synthesis_2)",
            "/provider/w?binding=writer_1&q=($synthesis_2 $model_1)",
            _MODEL_CALLS,
        ),
        "writer on the combine route": (
            "/provider/w?binding=writer_1",
            "/ensemble/combine/v1?binding=writer_1",
            _MODEL_CALLS,
        ),
        "signal key with a dot": (
            '"key":"writer_summary"',
            '"key":"writer.summary"',
            _INVALID_REDUCER,
        ),
        "signal key renamed in the combine context": (
            "signals: {writer_summary: '$writer_1'}",
            "signals: {writer_other: '$writer_1'}",
            _MODEL_CALLS,
        ),
        "writer signal without projection": (
            f'"projection":{projection},',
            "",
            _INVALID_REDUCER,
        ),
        "judge key with projection": (
            '"key":"writer_summary"',
            '"key":"judge"',
            _INVALID_REDUCER,
        ),
        "projection with an extra key": (
            '"kind":"reducer","name":"project"',
            '"extra":1,"kind":"reducer","name":"project"',
            _INVALID_REDUCER,
        ),
        "projection binding is not a synthesis": (
            '"projection":{"binding":"synthesis_2"',
            '"projection":{"binding":"model_2"',
            _INVALID_REDUCER,
        ),
        "source role is judge": (
            '"named":false,"role":"writer"',
            '"named":false,"role":"judge"',
            _INVALID_REDUCER,
        ),
        "source binding is a judge": (
            '"binding":"writer_1","kind":"model"',
            '"binding":"judge_1","kind":"model"',
            _INVALID_REDUCER,
        ),
        "writer role on a member": (
            '{"binding":"model_1","kind":"model","name":"a","named":false,"role":"model"}',
            '{"binding":"model_1","kind":"model","name":"a","named":false,"role":"writer"}',
            "invalid Model topology metadata",
        ),
        "duplicate signal": (
            entry,
            f"{entry},{entry}",
            _INVALID_REDUCER,
        ),
        "spec of another reducer": (
            '"reduce":{"args":{"fields"',
            '"reduce":{"args":{"fieldz"',
            "cannot rebuild|invalid combine spec|does not match",
        ),
    }


@pytest.mark.parametrize("case", sorted(_tamperings()))
def test_writer_topology_tampering_is_refused(case: str) -> None:
    old, new, message = _tamperings()[case]
    url4 = _compiled(sf.Fusion(members3(), synthesizer=_merge())).url4
    assert old in url4, case
    tampered = url4.replace(old, new, 1)

    with pytest.raises(ValueError, match=message):
        sf.Url4(tampered).to_python()


def test_rebuild_refuses_signals_that_do_not_match_the_model_fields() -> None:
    merge = _merge()
    spec = decode_combine_spec(combine_spec_text(merge, member_count=3, operators=flow_operators()))
    writer = _ModelSignal("writer_summary", "provider/w", "Write one summary.", {}, "summary")  # type: ignore[arg-type]

    assert sf.Merge._rebuild(spec, (writer,)) == merge
    with pytest.raises(ValueError, match=_INVALID_REDUCER):
        sf.Merge._rebuild(spec, ())
    stray = _ModelSignal("writer_answer", "provider/w", "x", {}, "answer")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=_INVALID_REDUCER):
        sf.Merge._rebuild(spec, (writer, stray))
    with pytest.raises(ValueError, match=_INVALID_REDUCER):
        sf.Merge._rebuild(spec, (writer, writer))
    judge = _ModelSignal("judge", "provider/j", "x", {})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=_INVALID_REDUCER):
        sf.Merge._rebuild(spec, (judge,))


def test_a_pick_spec_edited_by_hand_is_refused() -> None:
    pick = sf.Pick("confidence", order="max")
    spec: dict[str, Any] = dict(
        decode_combine_spec(combine_spec_text(pick, member_count=3, operators=flow_operators()))
    )
    assert sf.Pick._from_spec(spec) == pick
    edits = {
        "values field": {"reduce": {"op": "values@1", "args": {"field": "other"}}},
        "no extract": {"extract": None},
        "other normalizer": {"normalize": {"op": "text@1", "args": {}}},
        "weights": {"weights": {"member_1": 1.0, "member_2": 1.0, "member_3": 1.0}},
        "other select": {"select": {"op": "first_holder@1", "args": {}}},
        "bad order": {"select": {"op": "by_field@1", "args": {"order": "best"}}},
        "equals without value": {"select": {"op": "by_field@1", "args": {"order": "equals"}}},
    }
    for name, edit in edits.items():
        with pytest.raises(ValueError, match="cannot rebuild"):
            sf.Pick._from_spec({**spec, **edit})
        assert name


def test_a_merge_spec_edited_by_hand_is_refused() -> None:
    merge = sf.Merge(
        fields={"a": sf.FieldRule.from_member(2), "b": sf.FieldRule.majority(normalize="text")}
    )
    spec: dict[str, Any] = dict(
        decode_combine_spec(combine_spec_text(merge, member_count=3, operators=flow_operators()))
    )
    assert sf.Merge._from_spec(spec) == merge
    assert (merge._kind, sf.Pick("a", order="max")._kind) == ("answer", "answer")

    def fields(*rules: Any) -> dict[str, Any]:
        return {"reduce": {"op": "field_rules@1", "args": {"fields": list(rules)}}}

    from_member = {"field": "a", "rule": "from_member", "member": "member_2"}
    edits = {
        "weights": {"weights": {"member_1": 1.0, "member_2": 1.0, "member_3": 1.0}},
        "no extract": {"extract": None},
        "other extract": {"extract": {"op": "whole@1", "args": {}}},
        "normalizer": {"normalize": {"op": "text@1", "args": {}}},
        "other select": {"select": {"op": "first_holder@1", "args": {}}},
        "extra reduce arg": {"reduce": {"op": "field_rules@1", "args": {"fields": [], "x": 1}}},
        "fields not a list": {"reduce": {"op": "field_rules@1", "args": {"fields": {}}}},
        "rule not an object": fields("majority"),
        "unknown rule": fields({"field": "a", "rule": "median"}),
        "rule with a stray key": fields({"field": "a", "rule": "max", "normalize": None}),
        "member not an id": fields({**from_member, "member": "2"}),
        "member zero": fields({**from_member, "member": "member_0"}),
        "bad normalize": fields({"field": "a", "rule": "majority", "normalize": "lower"}),
        "bad field name": fields({"field": "1a", "rule": "max"}),
        "other reducer": {"reduce": {"op": "mode@1", "args": {}}},
    }
    for name, edit in edits.items():
        with pytest.raises(ValueError, match="cannot rebuild|must be|Merge field name"):
            sf.Merge._from_spec({**spec, **edit})
        assert name


def test_a_writer_for_another_field_is_refused() -> None:
    merge = _merge()
    spec = decode_combine_spec(combine_spec_text(merge, member_count=3, operators=flow_operators()))
    other = _ModelSignal("writer_summary", "provider/w", "Write.", {}, "answer")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=_INVALID_REDUCER):
        sf.Merge._rebuild(spec, (other,))
