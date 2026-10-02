"""sf.Pick, sf.Merge and sf.FieldRule: validation, repr and the compiled combine spec (OME-1289).

STORY: as a researcher whose members return JSON, I pick the member with the largest field or build
one object by declared rules, and a mistake (a bad field, a member that is not there) fails when I
build the Fusion, before any call is made.
"""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import FLOW_OPERATOR_WIRE, flow_operators, members3
from test_judge_reducer import _calls_by_name, _sources
from url4 import RelExpr, Text

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import decode_combine_spec
from screamingface._evaluation.operators import decode_operator_catalog


def _spec_of(recipe: sf.Recipe) -> dict[str, Any]:
    call = _calls_by_name(compile_candidate(recipe, operators=flow_operators()).url4)["synthesis_1"]
    assert isinstance(call.intent, Text)
    return dict(decode_combine_spec(call.intent.value))


def _step(op: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"op": op, "args": args}


def _spec(
    reducer: str,
    *,
    extract: dict[str, Any] | None,
    normalize: dict[str, Any] | None,
    reduce: dict[str, Any],
    select: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "screamingface.combine-spec.v1",
        "reducer": reducer,
        "members": ["member_1", "member_2", "member_3"],
        "extract": extract,
        "normalize": normalize,
        "reduce": reduce,
        "select": select,
        "weights": None,
    }


def test_field_rule_constructors_validate_and_repr() -> None:
    rules = [
        sf.FieldRule.majority(),
        sf.FieldRule.majority(normalize="text"),
        sf.FieldRule.max(),
        sf.FieldRule.from_member(2),
        sf.FieldRule.union(),
        sf.FieldRule.union(normalize="numeric"),
        sf.FieldRule.model("p/w", prompt="Write \"one\" 'line'.\nTwo."),
        sf.FieldRule.model("p/w", prompt="Write.", params={"temperature": 0}),
    ]
    assert [repr(rule) for rule in rules[:7]] == [
        "FieldRule.majority()",
        "FieldRule.majority(normalize='text')",
        "FieldRule.max()",
        "FieldRule.from_member(2)",
        "FieldRule.union()",
        "FieldRule.union(normalize='numeric')",
        "FieldRule.model('p/w', prompt='Write \"one\" \\'line\\'.\\nTwo.')",
    ]
    assert repr(rules[7]) == "FieldRule.model('p/w', prompt='Write.', params={'temperature': 0})"
    for rule in rules:
        assert eval(repr(rule), {"FieldRule": sf.FieldRule}) == rule  # noqa: S307 - the repr is the contract
    assert sf.FieldRule.majority() != sf.FieldRule.majority(normalize="text")
    assert hash(rules[0]) == hash(sf.FieldRule.majority())
    assert len({*rules, *rules}) == len(rules)


def test_field_rule_constructors_refuse_bad_arguments() -> None:
    with pytest.raises(TypeError, match="build a FieldRule with FieldRule.majority"):
        sf.FieldRule()
    with pytest.raises(TypeError, match="build a FieldRule with FieldRule.majority"):
        sf.FieldRule("max")
    with pytest.raises(ValueError, match="normalize must be 'text' or 'numeric'"):
        sf.FieldRule.majority(normalize="lower")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="normalize must be 'text' or 'numeric'"):
        sf.FieldRule.union(normalize="lower")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="from_member position must be at least 1"):
        sf.FieldRule.from_member(0)
    with pytest.raises(TypeError, match="from_member position must be an integer"):
        sf.FieldRule.from_member(True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="from_member position must be an integer"):
        sf.FieldRule.from_member("2")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="prompt must not be empty"):
        sf.FieldRule.model("p/w", prompt=" ")
    with pytest.raises(TypeError, match="prompt must be a string"):
        sf.FieldRule.model("p/w", prompt=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="model route must not be empty"):
        sf.FieldRule.model("", prompt="Write.")
    with pytest.raises(ValueError, match="'binding' is reserved"):
        sf.FieldRule.model("p/w", prompt="Write.", params={"binding": "x"})


def test_from_member_out_of_range_raises_at_build() -> None:
    merge = sf.Merge(fields={"s": sf.FieldRule.from_member(5)})

    with pytest.raises(
        ValueError, match=r"FieldRule.from_member\(5\) for field 's' needs 5 members"
    ):
        sf.Fusion(members3(), synthesizer=merge)
    sf.Fusion(members3() + ["provider/d", "provider/e"], synthesizer=merge)
    sf.Fusion(members3(), synthesizer=sf.Merge(fields={"s": sf.FieldRule.from_member(3)}))


def test_merge_and_pick_validate_arguments() -> None:
    majority = sf.FieldRule.majority()
    with pytest.raises(TypeError, match="Merge fields must be a mapping"):
        sf.Merge(fields=[("a", majority)])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Merge needs at least one field"):
        sf.Merge(fields={})
    with pytest.raises(ValueError, match="Merge takes at most 64 fields"):
        sf.Merge(fields={f"f{index}": majority for index in range(65)})
    assert len(sf.Merge(fields={f"f{index}": majority for index in range(64)}).fields) == 64
    with pytest.raises(TypeError, match="Merge field 'a' must be a FieldRule"):
        sf.Merge(fields={"a": "majority"})  # type: ignore[dict-item]


@pytest.mark.parametrize("name", ["", "1a", "a b", "a.b", "a" * 65, "é"])
def test_merge_refuses_a_bad_field_name(name: str) -> None:
    with pytest.raises(ValueError, match="Merge field name .* must start with a letter"):
        sf.Merge(fields={name: sf.FieldRule.majority()})


@pytest.mark.parametrize("path", ["", "a.", ".a", "a[01]", "a b", "$a", "a" * 257])
def test_pick_refuses_a_bad_field_path(path: str) -> None:
    with pytest.raises(ValueError, match="Pick field .* must be a JSON path"):
        sf.Pick(path, order="max")


def test_pick_refuses_targets_the_engine_would_only_refuse_after_the_member_calls() -> None:
    for blank in ("", "  ", "\n"):
        with pytest.raises(ValueError, match="Pick equals must not be blank"):
            sf.Pick("a", equals=blank)
    with pytest.raises(ValueError, match="Pick equals must not be blank"):
        sf.Pick("a", equals="", normalize="text")
    for flag in (True, False):
        with pytest.raises(ValueError, match="cannot be compared with normalize='numeric'"):
            sf.Pick("a", equals=flag, normalize="numeric")
    # a bool without the numeric normalizer, and a number with it, are fine
    sf.Pick("a", equals=True)
    sf.Pick("a", equals=True, normalize="text")
    sf.Pick("a", equals=7, normalize="numeric")


def test_pick_validates_its_arguments() -> None:
    with pytest.raises(
        ValueError, match="Pick takes order='max'\\|'min' or equals=<value>, not both"
    ):
        sf.Pick("confidence", order="max", equals="x")
    with pytest.raises(ValueError, match="Pick takes order='max'\\|'min' or equals=<value>"):
        sf.Pick("confidence")
    with pytest.raises(ValueError, match="Pick order must be 'max' or 'min'"):
        sf.Pick("confidence", order="best")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Pick normalize applies to equals only"):
        sf.Pick("confidence", order="max", normalize="numeric")
    with pytest.raises(ValueError, match="Pick normalize must be 'text' or 'numeric'"):
        sf.Pick("confidence", equals="x", normalize="lower")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Pick field must be a string"):
        sf.Pick(3, order="max")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Pick equals must be a string, number or boolean"):
        sf.Pick("a", equals=["x"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Pick equals must be finite"):
        sf.Pick("a", equals=float("nan"))
    sf.Pick("a.b[0].c", order="min")
    sf.Pick("a" * 256, order="max")


def test_pick_and_merge_repr_round_trip_and_compare_by_field() -> None:
    picks = [
        sf.Pick("confidence", order="max"),
        sf.Pick("a.b[0]", order="min"),
        sf.Pick("answer", equals="yes", normalize="text"),
        sf.Pick("n", equals=7),
    ]
    assert [repr(pick) for pick in picks] == [
        "Pick('confidence', order='max')",
        "Pick('a.b[0]', order='min')",
        "Pick('answer', equals='yes', normalize='text')",
        "Pick('n', equals='7')",
    ]
    for pick in picks:
        assert eval(repr(pick), {"Pick": sf.Pick}) == pick  # noqa: S307 - the repr is the contract
        assert pick.name == "pick"
    merge = sf.Merge(
        fields={
            "b": sf.FieldRule.majority(normalize="text"),
            "a": sf.FieldRule.model("p/w", prompt="Write."),
        }
    )
    assert repr(merge) == (
        "Merge(fields={'b': FieldRule.majority(normalize='text'), "
        "'a': FieldRule.model('p/w', prompt='Write.')})"
    )
    assert merge._python() == (
        "sf.Merge(fields={'b': sf.FieldRule.majority(normalize='text'), "
        "'a': sf.FieldRule.model('p/w', prompt='Write.')})"
    )
    assert eval(repr(merge), {"Merge": sf.Merge, "FieldRule": sf.FieldRule}) == merge  # noqa: S307
    assert merge.name == "merge"
    assert list(merge.fields) == ["b", "a"]
    assert merge != sf.Merge(fields=dict(reversed(list(merge.fields.items()))))
    with pytest.raises(TypeError):
        hash(merge)
    with pytest.raises(TypeError):
        hash(picks[0])
    with pytest.raises(TypeError):
        merge.fields["c"] = sf.FieldRule.max()  # type: ignore[index]


def test_pick_specs() -> None:
    fusion = sf.Fusion(members3(), synthesizer=sf.Pick("confidence", order="max"))
    call = _calls_by_name(compile_candidate(fusion, operators=flow_operators()).url4)["synthesis_1"]
    assert isinstance(call.intent, Text)
    # the exact bytes: canonical JSON, sorted keys, every pinned id
    assert call.intent.value == (
        '{"extract":{"args":{"path":"confidence"},"op":"json_field@1"},'
        '"members":["member_1","member_2","member_3"],'
        '"normalize":{"args":{},"op":"numeric@1"},'
        '"reduce":{"args":{"field":"confidence"},"op":"values@1"},"reducer":"pick",'
        '"schema":"screamingface.combine-spec.v1",'
        '"select":{"args":{"order":"max"},"op":"by_field@1"},"weights":null}'
    )
    assert call.params == (("binding", "synthesis_1"),)

    def spec(pick: sf.Pick) -> dict[str, Any]:
        return _spec_of(sf.Fusion(members3(), synthesizer=pick))

    assert spec(sf.Pick("a.b[0]", order="min")) == _spec(
        "pick",
        extract=_step("json_field@1", {"path": "a.b[0]"}),
        normalize=_step("numeric@1", {}),
        reduce=_step("values@1", {"field": "a.b[0]"}),
        select=_step("by_field@1", {"order": "min"}),
    )
    assert spec(sf.Pick("answer", equals="yes", normalize="text")) == _spec(
        "pick",
        extract=_step("json_field@1", {"path": "answer"}),
        normalize=_step("text@1", {}),
        reduce=_step("values@1", {"field": "answer"}),
        select=_step("by_field@1", {"order": "equals", "value": "yes", "normalize": "text"}),
    )
    assert spec(sf.Pick("n", equals="0.70", normalize="numeric")) == _spec(
        "pick",
        extract=_step("json_field@1", {"path": "n"}),
        normalize=_step("numeric@1", {}),
        reduce=_step("values@1", {"field": "n"}),
        select=_step("by_field@1", {"order": "equals", "value": "0.70", "normalize": "numeric"}),
    )
    # no normalizer: the target and the values are compared as written
    assert spec(sf.Pick("answer", equals="Yes.")) == _spec(
        "pick",
        extract=_step("json_field@1", {"path": "answer"}),
        normalize=None,
        reduce=_step("values@1", {"field": "answer"}),
        select=_step("by_field@1", {"order": "equals", "value": "Yes.", "normalize": None}),
    )
    # a non-text target is compared in its JSON spelling
    for given, written in ((7, "7"), (1.5, "1.5"), (True, "true"), (False, "false")):
        selected = spec(sf.Pick("n", equals=given))["select"]
        assert selected["args"]["value"] == written
    assert spec(sf.Pick("n", equals=1e20))["select"]["args"]["value"] == "1e+20"


def test_pick_pins_its_normalizer_even_when_the_catalog_has_a_newer_version() -> None:
    data = list(FLOW_OPERATOR_WIRE["data"])  # type: ignore[call-overload]
    newer = {**next(item for item in data if item["id"] == "numeric@1")}
    newer.update(id="numeric@2", version=2)
    catalog = decode_operator_catalog({"object": "list", "data": [*data, newer]})

    compiled = compile_candidate(
        sf.Fusion(members3(), synthesizer=sf.Pick("n", order="max")), operators=catalog
    )

    call = _calls_by_name(compiled.url4)["synthesis_1"]
    assert isinstance(call.intent, Text)
    assert decode_combine_spec(call.intent.value)["normalize"] == _step("numeric@1", {})


def test_merge_without_model_fields_is_one_combine_call() -> None:
    merge = sf.Merge(
        fields={
            "answer": sf.FieldRule.majority(normalize="text"),
            "score": sf.FieldRule.max(),
            "source": sf.FieldRule.from_member(2),
            "synonyms": sf.FieldRule.union(normalize="text"),
            "plain": sf.FieldRule.majority(),
        }
    )
    compiled = compile_candidate(
        sf.Fusion(members3(), synthesizer=merge), operators=flow_operators()
    )

    sources = _sources(compiled.url4)
    assert [source.name for source in sources] == [
        "model_1",
        "model_2",
        "model_3",
        "synthesis_1",
        "_sf_recipe",
    ]
    assert [operation.kind for operation in compiled.operations] == ["model"] * 3 + ["combine"]
    call = sources[3].value
    assert isinstance(call, RelExpr)
    assert "signals" not in (call.context or "")
    assert call.params == (("binding", "synthesis_1"),)
    assert compiled.models == ("provider/a", "provider/b", "provider/c")
    # "fields" keep the declared order (not the sorted order of the keys)
    assert _spec_of(sf.Fusion(members3(), synthesizer=merge)) == _spec(
        "merge",
        extract=_step("json_object@1", {}),
        normalize=None,
        reduce=_step(
            "field_rules@1",
            {
                "fields": [
                    {"field": "answer", "rule": "majority", "normalize": "text"},
                    {"field": "score", "rule": "max"},
                    {"field": "source", "rule": "from_member", "member": "member_2"},
                    {"field": "synonyms", "rule": "union", "normalize": "text"},
                    {"field": "plain", "rule": "majority", "normalize": None},
                ]
            },
        ),
        select=_step("built@1", {}),
    )


def test_a_catalog_without_the_field_operators_fails_before_any_call() -> None:
    empty = decode_operator_catalog({"object": "list", "data": []})

    with pytest.raises(ValueError, match="unknown extract operator 'json_field'"):
        compile_candidate(
            sf.Fusion(members3(), synthesizer=sf.Pick("n", order="max")), operators=empty
        )
    with pytest.raises(ValueError, match="unknown extract operator 'json_object'"):
        compile_candidate(
            sf.Fusion(members3(), synthesizer=sf.Merge(fields={"a": sf.FieldRule.max()})),
            operators=empty,
        )
