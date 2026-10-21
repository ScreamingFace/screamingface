"""The reducer slot of Fusion: guards, compile, pinning, canonical bytes (OME-1289, SL-3..SL-13)."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import httpx
import pytest
from _nodes import fusion_node
from _reducer_fixtures import (
    FixtureJudgeish,
    FixtureVote,
    compiled_vote_url4,
    fixture_operators,
    reducer_fusion,
)
from test_client_run import _engine
from url4 import Expression, Node, RelExpr, Source, Text, build, expr, render, src, struct

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface._evaluation.operators import _OperatorCatalog
from screamingface.operation import OperationInfo
from screamingface.reducer import _ReducerPlan, _Step
from screamingface.url4 import _calls

_TESTS = Path(__file__).parent
_COMBINE_PATH = "/ensemble/combine/v1"
_VOTE_SPEC = (
    '{"extract":{"args":{},"op":"last_number@2"},'
    '"members":["member_1","member_2","member_3"],'
    '"normalize":{"args":{},"op":"numeric@1"},'
    '"reduce":{"args":{},"op":"mode@1"},'
    '"reducer":"vote",'
    '"schema":"screamingface.combine-spec.v1",'
    '"select":{"args":{},"op":"first_holder@1"},'
    '"weights":null}'
)


class _NeverRuns:
    called = False

    def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("a reducer outside a Fusion slot must fail before execution")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


def _client() -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=_NeverRuns(),
    )


def _misplaced() -> dict[str, Callable[[sf.Client], object]]:
    reducer: Any = FixtureVote()
    return {
        "pipeline stage": lambda client: sf.Pipeline([reducer]),
        "fusion member": lambda client: sf.Fanout([reducer, "p/a"]) >> sf.Synthesize("p/s"),
        "then": lambda client: sf.Model("p/a") >> reducer,
        "corrective member": lambda client: sf.CorrectiveLoop([reducer, "p/a"], judge="p/j"),
        "corrective judge": lambda client: sf.CorrectiveLoop(["p/a", "p/b"], judge=reducer),
        "self corrective": lambda client: sf.SelfCorrective(reducer),
        "evaluate one": lambda client: client.evaluate(reducer, benchmark="draco"),
        "evaluate list": lambda client: client.evaluate([reducer], benchmark="draco"),
    }


def _sources(url4: str) -> dict[str, RelExpr]:
    root = build(url4)
    assert isinstance(root, Expression)
    return {
        node.name: node.value
        for node in root.sources
        if isinstance(node, Source) and node.name is not None and isinstance(node.value, RelExpr)
    }


def _wrapped(source: Node) -> str:
    return render(expr(source, intent=Text("$synthesis_1")))


def _combine_intent(url4: str, binding: str = "synthesis_1") -> str:
    intent = _sources(url4)[binding].intent
    assert isinstance(intent, Text)
    return intent.value


@pytest.mark.parametrize("position", sorted(_misplaced()))
def test_reducer_outside_a_fusion_slot_raises_type_error(position: str) -> None:
    with (
        _client() as client,
        pytest.raises(TypeError, match="reducer must be a Fusion synthesizer"),
    ):
        _misplaced()[position](client)


def test_fusion_accepts_a_reducer_in_the_synthesizer_slot() -> None:
    reducer = FixtureVote()
    fusion = fusion_node(["provider/a", "provider/b"], reducer)

    assert fusion.synthesizer is reducer
    assert repr(fusion).endswith(
        "synthesizer=FixtureVote(extract='last_number', normalize='numeric'))"
    )
    assert "reducer" in fusion._repr_html_()
    assert "vote" in fusion._repr_html_()

    with pytest.raises(ValueError, match="1 weights for 2 members"):
        fusion_node(["provider/a", "provider/b"], FixtureVote(weights=(1.0,)))
    with pytest.raises(ValueError, match="at most 256"):
        fusion_node([f"provider/m{index}" for index in range(257)], reducer)
    # the base-class defaults accept any member count
    fusion_node(["provider/a", "provider/b"], FixtureJudgeish())
    # a non-reducer synthesizer keeps its exact message
    with pytest.raises(TypeError, match="Fusion synthesizer must be a model route"):
        fusion_node(["provider/a"], 3)  # type: ignore[arg-type]


def test_short_operator_names_pin_to_newest_catalog_version() -> None:
    operators = fixture_operators()

    assert operators.pin("extract", "last_number") == "last_number@2"
    assert operators.pin("extract", "last_number@1") == "last_number@1"
    assert operators.pin("reduce", "mode") == "mode@1"


def test_unknown_operator_name_raises_before_submit() -> None:
    operators = fixture_operators()

    with pytest.raises(ValueError, match=r"'last_numbr'.*boxed, last_line, last_number"):
        compile_candidate(reducer_fusion(extract="last_numbr"), operators=operators)
    with pytest.raises(ValueError, match="'last_number@9'.*known extract operator ids"):
        compile_candidate(reducer_fusion(extract="last_number@9"), operators=operators)
    with pytest.raises(ValueError, match="is a reduce operator, not a extract operator"):
        compile_candidate(reducer_fusion(extract="mode@1"), operators=operators)
    with pytest.raises(ValueError, match="must be a name like 'last_number'"):
        compile_candidate(reducer_fusion(extract="Last Number"), operators=operators)
    with pytest.raises(ValueError, match="this SF Engine has no select operators"):
        _OperatorCatalog(entries=()).pin("select", "first_holder")


def test_reducer_compiles_to_one_combine_call_with_binding_param() -> None:
    compiled = compile_candidate(reducer_fusion(), operators=fixture_operators())
    root = build(compiled.url4)
    assert isinstance(root, Expression)

    context = render(
        struct(
            {
                "input": "$input",
                "outputs": {"member_1": "$model_1", "member_2": "$model_2", "member_3": "$model_3"},
            }
        )
    )
    expected = src(
        RelExpr(
            path=_COMBINE_PATH,
            context=context,
            intent=Text(_VOTE_SPEC),
            params=(("binding", "synthesis_1"),),
        ),
        name="synthesis_1",
        weight=0.0,
    )
    assert _wrapped(root.sources[3]) == _wrapped(expected)
    assert isinstance(root.intent, Text)
    assert root.intent.value == "$synthesis_1"
    assert compiled.models == ("provider/a", "provider/b", "provider/c")
    assert compiled.operations[-1] == OperationInfo(
        id="op_synthesis_1",
        kind="combine",
        label="a+b+c combine",
        depends_on=("op_model_1", "op_model_2", "op_model_3"),
    )
    recipe_source = root.sources[4]
    assert isinstance(recipe_source, Source)
    assert isinstance(recipe_source.value, Text)
    synthesizer = json.loads(recipe_source.value.value)["recipe"]["synthesizer"]
    assert synthesizer == {"binding": "synthesis_1", "kind": "reducer", "name": "vote"}


def test_reducer_without_catalog_fails_and_bad_specs_are_refused() -> None:
    with pytest.raises(ValueError, match="operator catalog"):
        compile_candidate(reducer_fusion())

    class Bogus(FixtureVote):
        def _plan(self) -> _ReducerPlan:
            return dataclasses.replace(super()._plan(), reducer="bogus")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="'bogus' is not a known reducer"):
        compile_candidate(
            fusion_node(["provider/a", "provider/b"], Bogus()),
            operators=fixture_operators(),
        )
    huge = {"pad": "x" * (64 * 1024)}
    with pytest.raises(ValueError, match="limit is 65536"):
        compile_candidate(reducer_fusion(extract_args=huge), operators=fixture_operators())

    judge = compile_candidate(
        fusion_node(["provider/a", "provider/b"], FixtureJudgeish()),
        operators=fixture_operators(),
    )
    assert '"extract":null,"members":["member_1","member_2"],"normalize":null' in _combine_intent(
        judge.url4
    )
    assert '"weights":null' in _combine_intent(judge.url4)
    weighted = compile_candidate(reducer_fusion(weights=(1, 2.5, 3)), operators=fixture_operators())
    assert '"weights":{"member_1":1.0,"member_2":2.5,"member_3":3.0}' in _combine_intent(
        weighted.url4
    )


def test_spec_builder_refuses_a_weight_count_that_does_not_match_the_members() -> None:
    with pytest.raises(ValueError, match="vote has 1 weights for 3 members"):
        combine_spec_text(
            FixtureVote(weights=(1.0,)), member_count=3, operators=fixture_operators()
        )


def test_spec_is_canonical_and_url4_is_byte_stable_across_processes() -> None:
    first, second = compiled_vote_url4(), compiled_vote_url4()
    assert first == second

    command = [
        sys.executable,
        "-c",
        "import _reducer_fixtures as f; print(f.compiled_vote_url4(), end='')",
    ]
    for seed in range(5):
        env = {**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONPATH": str(_TESTS)}
        completed = subprocess.run(
            command, env=env, capture_output=True, text=True, check=True, encoding="utf-8"
        )
        assert completed.stdout == first

    args = {"z": 1, "a": "it's $5\u007f \u00e9\u2028"}
    compiled = compile_candidate(reducer_fusion(extract_args=args), operators=fixture_operators())
    intent = _combine_intent(compiled.url4)
    assert "$" not in intent
    assert "\u007f" not in intent
    assert "\\u0024" in intent
    assert "\\u007f" in intent
    assert "\u00e9" in intent
    assert "\u2028" in intent
    assert "$$5" not in intent
    assert intent.index('"a":') < intent.index('"z":')
    assert decode_combine_spec(intent)["extract"] == {"args": args, "op": "last_number@2"}


def test_reducer_fusion_compiles_inside_pipeline_fusion_and_corrective_loop() -> None:
    operators = fixture_operators()

    # (a) two reducer Fusions in one Pipeline
    pipeline = sf.Pipeline(
        [reducer_fusion(), fusion_node(["provider/d", "provider/e"], FixtureVote())]
    )
    sources = _sources(compile_candidate(pipeline, operators=operators).url4)
    for name in ("synthesis_1", "synthesis_2"):
        assert sources[name].path == _COMBINE_PATH
        assert sources[name].params == (("binding", name),)
    assert sources["model_4"].context == "$synthesis_1"
    assert sources["model_5"].context == "$synthesis_1"

    # (b) a reducer Fusion as a member of a Model-synthesized Fusion
    nested = sf.Fanout([reducer_fusion(), "provider/d"]) >> sf.Synthesize("provider/s")
    sources = _sources(compile_candidate(nested, operators=operators).url4)
    assert sources["synthesis_1"].path == _COMBINE_PATH
    assert sources["synthesis_2"].path == "/provider/s"
    outer_context = sources["synthesis_2"].context
    assert outer_context is not None
    assert "$synthesis_1" in outer_context
    assert "$model_4" in outer_context

    # (c) a reducer Fusion member of a CorrectiveLoop, over several rounds
    loop = sf.CorrectiveLoop([reducer_fusion(), "provider/d"], judge="provider/j", max_rounds=2)
    surface = _CheckSurface(
        check_route="/benchmarks/ifeval/revision-1/check-surface",
        feedback_intent="feedback",
        expected_check_cost="free",
    )
    url4 = compile_candidate(loop, check_surface=surface, operators=operators).url4
    root = build(url4)
    assert isinstance(root, Expression)
    combines = {
        name: call for name, call in _calls(root).items() if call.model == "ensemble/combine/v1"
    }
    assert len(combines) >= 2
    for name, call in combines.items():
        assert call.params == (("binding", name),)


def test_from_pinned_builds_the_catalog_a_url4_describes() -> None:
    catalog = _OperatorCatalog.from_pinned(
        [("extract", "last_number@3"), ("reduce", "mode@1"), ("extract", "last_number@3")]
    )

    assert [entry.id for entry in catalog.entries] == ["last_number@3", "mode@1"]
    assert catalog.pin("extract", "last_number") == "last_number@3"
    with pytest.raises(ValueError, match="not a pinned id"):
        _OperatorCatalog.from_pinned([("extract", "last_number")])


def test_a_blank_operator_name_is_refused_when_the_step_is_built() -> None:
    with pytest.raises(TypeError, match="non-empty string"):
        _Step("  ")
    with pytest.raises(TypeError, match="non-empty string"):
        _Step(3)  # type: ignore[arg-type]


def _spec_with(**changes: object) -> str:
    spec = json.loads(_VOTE_SPEC)
    spec.update(changes)
    return json.dumps(spec)


@pytest.mark.parametrize(
    "raw",
    [
        _spec_with(extra=1),
        _spec_with(schema="screamingface.combine-spec.v2"),
        _spec_with(members=[]),
        _spec_with(members=["member_2"]),
        _spec_with(reduce=None),
        _spec_with(extract={"op": "last_number@2"}),
        _spec_with(weights=[1.0]),
        _spec_with(reducer=3),
        _VOTE_SPEC.replace('"weights":null', '"weights":null,"weights":null'),
        _VOTE_SPEC.replace('"args":{}', '"args":{"x":NaN}', 1),
        _VOTE_SPEC.replace('"args":{}', '"args":{"x":-Infinity}', 1),
        "[]",
        "not json",
    ],
)
def test_decode_combine_spec_refuses_anything_off_contract(raw: str) -> None:
    with pytest.raises(ValueError, match="invalid combine spec"):
        decode_combine_spec(raw)
