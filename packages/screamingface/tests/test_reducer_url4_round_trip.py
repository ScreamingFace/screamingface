"""A compiled reducer survives url4: topology, spec, replay and editable Python (OME-1289)."""

from __future__ import annotations

import json

import pytest
from _nodes import fusion_node
from _reducer_fixtures import FixtureJudgeish, FixtureVote, fixture_operators, reducer_fusion
from url4 import Expression, build, expr, render, src, text

import screamingface as sf
import screamingface.reducer as reducer_module
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface._evaluation.topology import _topology_from_expression
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.url4 import _calls

_SURFACE = _CheckSurface(
    check_route="/benchmarks/ifeval/revision-1/check-surface",
    feedback_intent="feedback",
    expected_check_cost="free",
)


def _compiled(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, check_surface=_SURFACE, operators=fixture_operators()).url4


def _expression(url4: str) -> Expression:
    root = build(url4)
    assert isinstance(root, Expression)
    return root


def _linked(candidate: str) -> str:
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("/benchmarks/ifeval/revision-1/cases", name="rows", weight=0.0),
            intent=text("$rows"),
        )
    )


def test_url4_round_trip_recovers_reducer_topology() -> None:
    fusion = reducer_fusion()
    compiled = compile_candidate(fusion, operators=fixture_operators())
    root = _expression(compiled.url4)

    synthesizer = _topology_from_expression(root).synthesizer
    assert synthesizer is not None
    assert (synthesizer.kind, synthesizer.binding, synthesizer.name) == (
        "reducer",
        "synthesis_1",
        "vote",
    )
    call = _calls(root)["synthesis_1"]
    compiled_spec = json.loads(
        combine_spec_text(FixtureVote(), member_count=3, operators=fixture_operators())
    )
    assert decode_combine_spec(call.raw_intent) == compiled_spec
    assert compiled_spec["reducer"] == "vote"

    replayed = _candidate_from_url4(_linked(compiled.url4))
    assert replayed.operations == compiled.operations
    assert replayed.models == compiled.models == ("provider/a", "provider/b", "provider/c")
    assert [member.operation_id for member in replayed.members] == [
        member.operation_id for member in compiled.members
    ]
    assert [member.models for member in replayed.members] == [
        member.models for member in compiled.members
    ]


_REDUCER_NODE = '{"binding":"synthesis_1","kind":"reducer","name":"vote"}'
_MODEL_CALLS = "does not match its model calls"


def _tamperings() -> dict[str, tuple[str, str, str, str]]:
    """name -> (recipe key, text to replace, replacement, expected error)."""

    return {
        "combine path swapped": ("reducer", "/ensemble/combine/v1", "/provider/x", _MODEL_CALLS),
        "model node on a combine call": (
            "model",
            "/provider/x",
            "/ensemble/combine/v1",
            _MODEL_CALLS,
        ),
        "reducer as a pipeline stage": (
            "pipeline",
            '{"binding":"model_2","kind":"model","name":"b","named":false,"role":"model"}',
            '{"binding":"model_2","kind":"reducer","name":"vote"}',
            "invalid Recipe topology metadata",
        ),
        "reducer with an extra key": (
            "reducer",
            _REDUCER_NODE,
            '{"binding":"synthesis_1","extra":1,"kind":"reducer","name":"vote"}',
            "invalid Reducer topology metadata",
        ),
        "reducer with a model binding": (
            "reducer",
            _REDUCER_NODE,
            '{"binding":"model_1","kind":"reducer","name":"vote"}',
            "invalid Reducer topology metadata",
        ),
        "reducer name that is not the spec's reducer": (
            "reducer",
            _REDUCER_NODE,
            '{"binding":"synthesis_1","kind":"reducer","name":"median"}',
            _MODEL_CALLS,
        ),
        "binding param of another call": (
            "pipeline_of_reducers",
            "?binding=synthesis_2&",
            "?binding=synthesis_1&",
            _MODEL_CALLS,
        ),
        "binding param removed": ("reducer", "?binding=synthesis_1&", "?", _MODEL_CALLS),
    }


def _recipes() -> dict[str, sf.Recipe]:
    return {
        "reducer": reducer_fusion(),
        "model": sf.Model("provider/x"),
        "pipeline": sf.Pipeline(["provider/a", "provider/b"]),
        "pipeline_of_reducers": sf.Pipeline(
            [reducer_fusion(), fusion_node(["provider/d", "provider/e"], FixtureVote())]
        ),
    }


@pytest.mark.parametrize("case", sorted(_tamperings()))
def test_reducer_topology_tampering_is_refused(case: str) -> None:
    key, old, new, message = _tamperings()[case]
    url4 = _compiled(_recipes()[key])
    assert old in url4
    tampered = url4.replace(old, new, 1)

    with pytest.raises(ValueError, match=message):
        sf.Url4(tampered).to_python()


def test_a_corrective_rider_naming_a_missing_reducer_call_is_refused() -> None:
    loop = sf.CorrectiveLoop([reducer_fusion(), "provider/d"], judge="provider/j", max_rounds=2)
    url4 = _compiled(loop)
    head, marker, rider = url4.partition("_sf_recipe:")
    assert '"binding":"synthesis_1"' in rider
    tampered = head + marker + rider.replace('"binding":"synthesis_1"', '"binding":"synthesis_99"')

    with pytest.raises(ValueError, match=_MODEL_CALLS):
        sf.Url4(tampered).to_python()
    with pytest.raises(ValueError, match=_MODEL_CALLS):
        _candidate_from_url4(_linked(tampered))


def test_to_python_and_corrective_replay_use_the_reducer_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url4 = _compiled(reducer_fusion())

    monkeypatch.setattr(reducer_module, "_REDUCER_CLASSES", {})
    # no named class registered: the block form rebuilds it (BK-D2), as a Vote over the extract
    source = sf.Url4(url4).to_python()
    assert ">> sf.Vote(over=sf.Extract('last_number'), normalize='numeric')" in source
    judgeish = _compiled(fusion_node(["provider/a", "provider/b"], FixtureJudgeish()))
    with pytest.raises(ValueError, match="cannot rebuild"):
        sf.Url4(judgeish).to_python()

    # a custom reducer from the registry has no step, so its url4 has no Python (7e)
    monkeypatch.setitem(reducer_module._REDUCER_CLASSES, "vote", FixtureVote)
    with pytest.raises(ValueError, match="vote spec this SDK version cannot rebuild"):
        sf.Url4(url4).to_python()

    loop = sf.CorrectiveLoop([reducer_fusion(), "provider/d"], judge="provider/j", max_rounds=2)
    linked = _linked(_compiled(loop))
    replayed = _candidate_from_url4(linked)
    assert replayed.kind == "corrective_loop"
    assert "ensemble/combine/v1" not in replayed.models
