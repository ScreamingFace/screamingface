"""A compiled Pick or Merge survives url4: replay, editable Python, tampering refusal (OME-1289)."""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators, members3
from test_judge_url4_round_trip import (
    _INVALID_REDUCER,
    _MODEL_CALLS,
    _SURFACE,
    _compiled,
    _linked,
    _recovered,
)

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.reducer import _ModelSignal

_CANNOT_REBUILD_PROJECT = "project spec this SDK version cannot rebuild"
_CANNOT_REBUILD_MERGE = "merge spec this SDK version cannot rebuild"
_CANNOT_REBUILD_PICK = "pick spec this SDK version cannot rebuild"
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


def _originals() -> dict[str, sf.Pick | sf.Merge]:
    return {
        "pick equals number": sf.Pick("n", equals=7),
        "pick equals text": sf.Pick("answer", equals="yes", normalize="text"),
        "pick min": sf.Pick("n", order="min"),
        "merge": sf.Merge(
            fields={
                "z": sf.FieldRule.model(
                    "provider/w", prompt="Write.\n'x' $5", params={"temperature": 0, "seed": 7}
                ),
                "m": sf.FieldRule.from_member(3),
                "a": sf.FieldRule.union(normalize="numeric"),
            }
        ),
    }


@pytest.mark.parametrize("name", sorted(_originals()))
def test_the_recovered_reducers_equal_the_originals_field_by_field(name: str) -> None:
    original = _originals()[name]

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
            _CANNOT_REBUILD_PROJECT,
        ),
        "projection extract is whole": (
            '"extract":{"args":{},"op":"json_object@1"},"members":["member_1","member_2","member_3"],'
            '"normalize":null,"reduce":{"args":{"field":"summary"}',
            '"extract":{"args":{},"op":"whole@1"},"members":["member_1","member_2","member_3"],'
            '"normalize":null,"reduce":{"args":{"field":"summary"}',
            _CANNOT_REBUILD_PROJECT,
        ),
        "projection extract is null": (
            '"extract":{"args":{},"op":"json_object@1"},"members":["member_1","member_2","member_3"],'
            '"normalize":null,"reduce":{"args":{"field":"summary"}',
            '"extract":null,"members":["member_1","member_2","member_3"],'
            '"normalize":null,"reduce":{"args":{"field":"summary"}',
            _CANNOT_REBUILD_PROJECT,
        ),
        "projection reduce has an extra arg": (
            '"reduce":{"args":{"field":"summary"},"op":"project_field@1"}',
            '"reduce":{"args":{"field":"summary","x":1},"op":"project_field@1"}',
            _CANNOT_REBUILD_PROJECT,
        ),
        "projection has a normalizer": (
            '"normalize":null,"reduce":{"args":{"field":"summary"}',
            '"normalize":{"args":{},"op":"text@1"},"reduce":{"args":{"field":"summary"}',
            _CANNOT_REBUILD_PROJECT,
        ),
        "projection select is first_holder": (
            '"select":{"args":{},"op":"built@1"},"weights":null}\', writer_1',
            '"select":{"args":{},"op":"first_holder@1"},"weights":null}\', writer_1',
            _CANNOT_REBUILD_PROJECT,
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
            _CANNOT_REBUILD_MERGE,
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


def _spec_of(reducer: sf.Pick | sf.Merge) -> dict[str, Any]:
    return dict(
        decode_combine_spec(combine_spec_text(reducer, member_count=3, operators=flow_operators()))
    )


def _pick_edits() -> dict[str, dict[str, Any]]:
    return {
        "values field": {"reduce": {"op": "values@1", "args": {"field": "other"}}},
        "no extract": {"extract": None},
        "other normalizer": {"normalize": {"op": "text@1", "args": {}}},
        "weights": {"weights": {"member_1": 1.0, "member_2": 1.0, "member_3": 1.0}},
        "other select": {"select": {"op": "first_holder@1", "args": {}}},
        "bad order": {"select": {"op": "by_field@1", "args": {"order": "best"}}},
        "equals without value": {"select": {"op": "by_field@1", "args": {"order": "equals"}}},
    }


@pytest.mark.parametrize("name", sorted(_pick_edits()))
def test_a_pick_spec_edited_by_hand_is_refused(name: str) -> None:
    pick = sf.Pick("confidence", order="max")
    spec = _spec_of(pick)
    assert sf.Pick._from_spec(spec) == pick
    assert pick._kind == "answer"

    with pytest.raises(ValueError, match=_CANNOT_REBUILD_PICK):
        sf.Pick._from_spec({**spec, **_pick_edits()[name]})


def _rules(*rules: Any) -> dict[str, Any]:
    return {"reduce": {"op": "field_rules@1", "args": {"fields": list(rules)}}}


_FROM_MEMBER = {"field": "a", "rule": "from_member", "member": "member_2"}
_MAJORITY = {"field": "b", "rule": "majority", "normalize": "text"}


def _merge_edits() -> dict[str, tuple[dict[str, Any], str]]:
    return {
        "weights": (
            {"weights": {"member_1": 1.0, "member_2": 1.0, "member_3": 1.0}},
            _CANNOT_REBUILD_MERGE,
        ),
        "no extract": ({"extract": None}, _CANNOT_REBUILD_MERGE),
        "other extract": ({"extract": {"op": "whole@1", "args": {}}}, _CANNOT_REBUILD_MERGE),
        "normalizer": ({"normalize": {"op": "text@1", "args": {}}}, _CANNOT_REBUILD_MERGE),
        "other select": ({"select": {"op": "first_holder@1", "args": {}}}, _CANNOT_REBUILD_MERGE),
        "other reducer": ({"reduce": {"op": "mode@1", "args": {}}}, _CANNOT_REBUILD_MERGE),
        "extra reduce arg": (
            {"reduce": {"op": "field_rules@1", "args": {"fields": [], "x": 1}}},
            _CANNOT_REBUILD_MERGE,
        ),
        "fields not a list": (
            {"reduce": {"op": "field_rules@1", "args": {"fields": {}}}},
            _CANNOT_REBUILD_MERGE,
        ),
        "rule not an object": (_rules("majority"), _CANNOT_REBUILD_MERGE),
        "unknown rule": (_rules({"field": "a", "rule": "median"}), _CANNOT_REBUILD_MERGE),
        "rule with a stray key": (
            _rules({"field": "a", "rule": "max", "normalize": None}),
            _CANNOT_REBUILD_MERGE,
        ),
        "member not an id": (_rules({**_FROM_MEMBER, "member": "2"}), _CANNOT_REBUILD_MERGE),
        "member zero": (_rules({**_FROM_MEMBER, "member": "member_0"}), _CANNOT_REBUILD_MERGE),
        "duplicate field": (_rules(_FROM_MEMBER, _MAJORITY, _FROM_MEMBER), _CANNOT_REBUILD_MERGE),
        "bad normalize": (
            _rules({"field": "a", "rule": "majority", "normalize": "lower"}),
            "FieldRule normalize must be 'text' or 'numeric', not 'lower'",
        ),
        "bad field name": (
            _rules({"field": "1a", "rule": "max"}),
            "Merge field name '1a' must start with a letter",
        ),
        "no fields": (_rules(), "Merge needs at least one field"),
    }


@pytest.mark.parametrize("name", sorted(_merge_edits()))
def test_a_merge_spec_edited_by_hand_is_refused(name: str) -> None:
    merge = sf.Merge(
        fields={"a": sf.FieldRule.from_member(2), "b": sf.FieldRule.majority(normalize="text")}
    )
    spec = _spec_of(merge)
    assert sf.Merge._from_spec(spec) == merge
    assert merge._kind == "answer"
    edit, message = _merge_edits()[name]

    with pytest.raises(ValueError, match=message):
        sf.Merge._from_spec({**spec, **edit})


def test_a_writer_for_another_field_is_refused() -> None:
    merge = _merge()
    spec = decode_combine_spec(combine_spec_text(merge, member_count=3, operators=flow_operators()))
    other = _ModelSignal("writer_summary", "provider/w", "Write.", {}, "answer")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=_INVALID_REDUCER):
        sf.Merge._rebuild(spec, (other,))
