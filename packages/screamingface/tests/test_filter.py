"""sf.Filter and the signal comparisons (OME-1289 gap, FL#6-9, BK#4).

FEATURE: ``sf.Filter(where=sf.signal("field:confidence") >= 0.6)`` (or ``where=sf.matches(...)``)
keeps the members that pass; the next stage gets only those members' original texts.
INVARIANT: a comparison is a value with a typed key: ``True``, ``1`` and ``1.0`` are never mixed up,
and equal values compile to equal bytes (GE21).
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

import httpx
import pytest
from _combine_flow_fixtures import flow_operators, members3
from _nodes import FilterNode, FusionNode, fusion_node, lowered
from _reducer_fixtures import evidence_wire
from _vote_run_fixtures import (
    ScriptedTransport,
    benchmark_resource,
    case_wire,
    engine_handler,
    operation_wire,
)

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface._signals import _Comparison
from screamingface._surface.chain import Step
from screamingface.reducer import Reducer

_SURFACE = _CheckSurface(
    check_route="/benchmarks/ifeval/revision-1/check-surface",
    feedback_intent="feedback",
    expected_check_cost="free",
)
_CONFIDENCE = sf.signal("field:confidence")
_CMPS = ["gt", "ge", "lt", "le", "eq"]
_OPEN_BLOCK = "the chain ends inside a sf.Fanout block: add a reducer or sf.Synthesize"


def _chain(step: Step) -> sf.Pipeline:
    """A selection step in a block, then the writer that reads the selected members."""
    return sf.Fanout(members3()) >> step >> sf.Synthesize("provider/next")


def _chain_url4(step: Step) -> str:
    return compile_candidate(_chain(step), operators=flow_operators()).url4


def _spec(reducer: Reducer, members: int = 3) -> dict[str, Any]:
    text_ = combine_spec_text(reducer, member_count=members, operators=flow_operators())
    return json.loads(text_)


def _recovered(url4: str) -> sf.Recipe:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    candidate = namespace["candidate"]
    assert isinstance(candidate, sf.Recipe)
    return candidate


# --- FL#7 / unit 4 F13: the comparisons --------------------------------------------------------


def test_signal_comparisons_keep_signal_equality_and_hash() -> None:
    same, other = sf.signal("field:a"), sf.signal("field:a")

    # Signal == Signal stays a bool (BK-D4): equal keys are equal, hash equal and one set member
    assert (same == other) is True
    assert (same != sf.signal("field:b")) is True
    assert (same != other) is False
    assert hash(same) == hash(other)
    assert len({same, other}) == 1
    assert (same == "x") is False
    assert (same == None) is False  # noqa: E711
    assert (same != "x") is True


def test_signal_comparisons_build_predicates() -> None:
    same, other = sf.signal("field:a"), sf.signal("field:a")
    predicate = same >= 0.6
    assert isinstance(predicate, _Comparison)
    assert predicate == _Comparison(same, "ge", 0.6)
    assert (0.6 <= same) == predicate  # a reflected comparison builds the same predicate
    assert (same > 1) == _Comparison(same, "gt", 1.0)
    assert (same < 2) == _Comparison(same, "lt", 2.0)
    assert (same <= -1) == _Comparison(same, "le", -1.0)
    assert (same == 0.5) == _Comparison(same, "eq", 0.5)
    equal_true = same == True  # noqa: E712
    assert isinstance(equal_true, _Comparison)
    assert equal_true.value is True  # a bool value stays a bool
    assert (same == 1).value == 1.0  # type: ignore[union-attr]
    assert (same == True) != (same == 1)  # noqa: E712

    with pytest.raises(TypeError, match="an sf.Filter predicate, not a bool"):
        bool(predicate)
    with pytest.raises(TypeError, match=r"sf\.Filter has no != predicate"):
        _ = same != 1
    with pytest.raises(TypeError, match=r"sf\.Filter has no != predicate"):
        _ = same != True  # noqa: E712
    with pytest.raises(TypeError):
        _ = same < other
    with pytest.raises(TypeError):
        _ = same >= "0.6"  # type: ignore[operator]
    for built in (predicate, equal_true, same <= -1, same == 0.5):
        assert eval(built._python(), {"sf": sf}) == built  # noqa: S307


def test_comparison_repr_python_and_args() -> None:
    assert repr(_CONFIDENCE >= 0.6) == "signal('field:confidence') >= 0.6"
    assert (_CONFIDENCE >= 0.6)._python() == "sf.signal('field:confidence') >= 0.6"
    assert (_CONFIDENCE > 3)._python() == "sf.signal('field:confidence') > 3.0"
    assert (_CONFIDENCE < 3)._python() == "sf.signal('field:confidence') < 3.0"
    assert (_CONFIDENCE <= 3)._python() == "sf.signal('field:confidence') <= 3.0"
    assert (_CONFIDENCE == 3)._python() == "sf.signal('field:confidence') == 3.0"  # type: ignore[union-attr]
    assert (_CONFIDENCE == True)._python() == "sf.signal('field:confidence') == True"  # noqa: E712  # type: ignore[union-attr]
    assert (_CONFIDENCE >= 0.6)._args() == {"key": "field:confidence", "cmp": "ge", "value": 0.6}


def test_comparisons_compare_and_hash_by_a_typed_key() -> None:
    """GE21: True, 1 and 1.0 stay distinct; equal values are equal and hash equal."""

    as_true, as_one, as_float = (_CONFIDENCE == True), (_CONFIDENCE == 1), (_CONFIDENCE == 1.0)  # noqa: E712
    assert as_true != as_one
    assert hash(as_true) != hash(as_one) or len({as_true, as_one}) == 2
    assert len({as_true, as_one}) == 2
    # 1 and 1.0 are the same number, so they are one predicate with one set of bytes
    assert as_one == as_float
    assert hash(as_one) == hash(as_float)
    assert len({as_one, as_float}) == 1
    assert (_CONFIDENCE >= 0.6) != (_CONFIDENCE > 0.6)
    assert (_CONFIDENCE >= 0.6) != (sf.signal("cost_usd") >= 0.6)
    assert (_CONFIDENCE >= 0.6) == (sf.signal("field:confidence") >= 0.6)

    # a Filter that holds the comparisons keeps them apart too
    assert sf.Filter(where=as_true) != sf.Filter(where=as_one)  # type: ignore[arg-type]
    assert sf.Filter(where=as_one) == sf.Filter(where=as_float)  # type: ignore[arg-type]
    filters = [sf.Filter(where=value) for value in (as_true, as_one, as_float)]  # type: ignore[arg-type]
    nodes = [FilterNode(where=value) for value in (as_true, as_one, as_float)]  # type: ignore[arg-type]
    # equal values compile to equal bytes, and different values to different bytes
    assert _chain_url4(filters[1]) == _chain_url4(filters[2])
    assert _chain_url4(filters[0]) != _chain_url4(filters[1])
    assert '"value":true' in combine_spec_text(nodes[0], member_count=3, operators=flow_operators())
    assert '"value":1.0' in combine_spec_text(nodes[1], member_count=3, operators=flow_operators())


def test_non_finite_threshold_is_rejected() -> None:
    for bad in (math.nan, math.inf, -math.inf, 10**400, -(10**400)):
        for compare in (
            lambda v: _CONFIDENCE > v,
            lambda v: _CONFIDENCE >= v,
            lambda v: _CONFIDENCE < v,
            lambda v: _CONFIDENCE <= v,
            lambda v: _CONFIDENCE == v,
            lambda v: v <= _CONFIDENCE,
        ):
            with pytest.raises(ValueError, match="sf.signal comparison value must be finite"):
                compare(bad)
    for compare in (
        lambda: _CONFIDENCE > True,
        lambda: _CONFIDENCE >= False,
        lambda: _CONFIDENCE < True,
        lambda: _CONFIDENCE <= True,
    ):
        with pytest.raises(ValueError, match="a boolean threshold compares with == only"):
            compare()
    assert (_CONFIDENCE == False).value is False  # type: ignore[union-attr]  # noqa: E712
    assert (_CONFIDENCE > 10**300).value == 1e300  # type: ignore[union-attr]


# --- FL#7: the filter plan ---------------------------------------------------------------------


def test_filter_compiles_filter_and_kept() -> None:
    reducer = FilterNode(where=_CONFIDENCE >= 0.6)  # type: ignore[arg-type]
    spec = _spec(reducer)

    assert spec["reducer"] == "filter"
    assert (spec["extract"], spec["normalize"], spec["weights"]) == (None, None, None)
    assert spec["reduce"] == {
        "args": {"cmp": "ge", "key": "field:confidence", "value": 0.6},
        "op": "filter@1",
    }
    assert spec["select"] == {"args": {}, "op": "kept@1"}
    assert reducer._plan().kind == "selection"

    pattern = _spec(FilterNode(where=sf.matches(r"ANSWER: \d+", ignore_case=True)))
    assert pattern["reduce"] == {
        "args": {"ignore_case": True, "pattern": r"ANSWER: \d+"},
        "op": "filter@1",
    }
    plain = _spec(FilterNode(where=sf.matches(r"ANSWER: \d+")))
    assert plain["reduce"]["args"] == {"pattern": r"ANSWER: \d+"}

    field = _spec(FilterNode(where=sf.matches("yes"), extract=sf.Extract("field", path="answer")))
    assert field["extract"] == {"args": {"path": "answer"}, "op": "json_field@1"}
    assert field["normalize"] is None
    normalized = _spec(
        FilterNode(where=sf.matches("yes"), extract=sf.Extract("field", "text", path="answer"))
    )
    assert normalized["normalize"] == {"args": {}, "op": "text@1"}


@pytest.mark.parametrize("cmp_op", _CMPS)
def test_every_comparison_writes_its_cmp(cmp_op: str) -> None:
    built = {
        "gt": _CONFIDENCE > 0.5,
        "ge": _CONFIDENCE >= 0.5,
        "lt": _CONFIDENCE < 0.5,
        "le": _CONFIDENCE <= 0.5,
        "eq": _CONFIDENCE == 0.5,
    }[cmp_op]
    spec = _spec(FilterNode(where=built))  # type: ignore[arg-type]

    assert spec["reduce"]["args"] == {"cmp": cmp_op, "key": "field:confidence", "value": 0.5}


def test_filter_benchmark_extract_resolves_from_the_benchmark_rule() -> None:
    from _fusion_doc_examples import _GSM8K_RULE

    reducer = sf.Filter(where=sf.matches("42"), over=sf.Extract("benchmark"))
    compiled = compile_candidate(
        _chain(reducer), operators=flow_operators(), benchmark_rule=_GSM8K_RULE
    )

    assert '"op":"inspect_number@1"' in compiled.url4.replace("\\u0022", '"') or (
        "inspect_number@1" in compiled.url4
    )
    assert "inspect_numeric@1" in compiled.url4


# --- FL#6: the last-stage rule -----------------------------------------------------------------


def test_filter_as_last_stage_is_rejected() -> None:
    reducer = sf.Filter(where=_CONFIDENCE >= 0.6)  # type: ignore[arg-type]
    fusion = sf.Fanout(members3()) >> reducer

    with pytest.raises(ValueError, match=re.escape(_OPEN_BLOCK)):
        compile_candidate(fusion, operators=flow_operators())
    # a Fanout member and a corrective-loop judge are refused too
    with pytest.raises(ValueError, match=re.escape(_OPEN_BLOCK)):
        compile_candidate(
            sf.Fanout([fusion, "provider/d"]) >> sf.Synthesize("provider/s"),
            operators=flow_operators(),
        )
    with pytest.raises(ValueError, match=re.escape(_OPEN_BLOCK)):
        compile_candidate(
            sf.CorrectiveLoop(["provider/a", "provider/b"], judge=fusion),
            check_surface=_SURFACE,
            operators=flow_operators(),
        )
    # the compiler's own guard on the internal node, which only a hand-built url4 reaches: alone,
    # as a member and as a loop judge
    node = fusion_node(members3(), FilterNode(where=_CONFIDENCE >= 0.6))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="a sf.Filter must be followed by sf.Synthesize"):
        compile_candidate(node, operators=flow_operators())
    with pytest.raises(ValueError, match="a sf.Filter block cannot be a sf.Fanout member"):
        compile_candidate(
            fusion_node([node, "provider/d"], "provider/s"), operators=flow_operators()
        )
    with pytest.raises(ValueError, match="a sf.Filter block cannot feed a corrective loop"):
        compile_candidate(
            sf.CorrectiveLoop(["provider/a", "provider/b"], judge=node),
            check_surface=_SURFACE,
            operators=flow_operators(),
        )
    followed = fusion >> sf.Synthesize("provider/next")
    assert compile_candidate(followed, operators=flow_operators()).operations


# --- validation, round trip, decode ------------------------------------------------------------


def test_filter_validation() -> None:
    where_rule = re.escape(
        "sf.Filter where= takes sf.matches(...) or a signal comparison such as "
        "sf.signal(key) >= 0.6"
    )
    with pytest.raises(TypeError, match=where_rule):
        sf.Filter(where="x")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=where_rule):
        sf.Filter(where=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Filter extract must be an sf.Extract"):
        FilterNode(where=sf.matches("a"), extract="last_number")  # type: ignore[arg-type]
    with pytest.raises(
        ValueError, match=re.escape("score:judge needs sf.Judge(...) after sf.Fanout")
    ):
        _chain(sf.Filter(where=sf.signal("score:judge") >= 0.5))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sf.matches"):
        sf.matches("(")


def test_filter_fields_repr_and_equality() -> None:
    named = FilterNode(where=_CONFIDENCE >= 0.6)  # type: ignore[arg-type]
    pattern = FilterNode(where=sf.matches("a", ignore_case=True), extract=sf.Extract("boxed"))

    assert (named.name, named.where, named.extract) == ("filter", _CONFIDENCE >= 0.6, None)
    assert repr(named) == "Filter(where=sf.signal('field:confidence') >= 0.6)"
    assert repr(pattern) == (
        "Filter(where=sf.matches('a', ignore_case=True), extract=sf.Extract('boxed'))"
    )
    assert named != pattern
    assert named == FilterNode(where=sf.signal("field:confidence") >= 0.6)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        hash(named)
    assert repr(fusion_node(members3(), named)).endswith(f"synthesizer={named!r})")


def _shapes() -> dict[str, sf.Recipe]:
    judge_free: dict[str, Step] = {
        "threshold": sf.Filter(where=_CONFIDENCE >= 0.6),  # type: ignore[arg-type]
        "equal true": sf.Filter(where=_CONFIDENCE == True),  # noqa: E712  # type: ignore[arg-type]
        "accounting": sf.Filter(where=sf.signal("cost_usd") <= 0.01),  # type: ignore[arg-type]
        "pattern": sf.Filter(where=sf.matches("ANSWER: [0-9]+")),
        "pattern ignoring case": sf.Filter(where=sf.matches("yes", ignore_case=True)),
        "pattern with extract": sf.Filter(
            where=sf.matches("^y"), over=sf.Extract("field", "text", path="answer")
        ),
    }
    return {name: _chain(step) for name, step in judge_free.items()}


@pytest.mark.parametrize(
    "shape",
    ["threshold", "equal true", "accounting", "pattern ignoring case", "pattern with extract"],
)
def test_filter_round_trips_and_is_recovered_as_sf_filter(shape: str) -> None:
    recipe = _shapes()[shape]
    url4 = compile_candidate(recipe, operators=flow_operators()).url4

    recovered = _recovered(url4)
    assert isinstance(recovered, sf.Pipeline)
    assert type(recovered.steps[1]) is sf.Filter
    fusion = lowered(recovered)._stage_values()[0]
    assert isinstance(fusion, FusionNode)
    assert type(fusion.synthesizer) is FilterNode
    assert compile_candidate(recovered, operators=flow_operators()).url4 == url4


def test_to_python_writes_the_filter() -> None:
    url4 = compile_candidate(_shapes()["threshold"], operators=flow_operators()).url4
    source = sf.Url4(url4).to_python()

    assert "    >> sf.Filter(where=sf.signal('field:confidence') >= 0.6)" in source.splitlines()
    pattern = compile_candidate(_shapes()["pattern ignoring case"], operators=flow_operators())
    assert (
        "    >> sf.Filter(where=sf.matches('yes', ignore_case=True))"
        in sf.Url4(pattern.url4).to_python().splitlines()
    )


def _tamperings() -> dict[str, tuple[str, str, str]]:
    """name -> (shape, text to replace, replacement); every one is 'cannot rebuild'."""

    return {
        "cmp unknown": ("threshold", '"cmp":"ge"', '"cmp":"ne"'),
        "cmp missing": ("threshold", '"cmp":"ge",', ""),
        "value is null": ("threshold", '"value":0.6', '"value":null'),
        "bool value with ge": ("threshold", '"value":0.6', '"value":true'),
        "pattern does not compile": ("pattern", '"pattern":"ANSWER: [0-9]+"', '"pattern":"("'),
        "extract on a rule that needs a path": (
            "pattern with extract",
            '"args":{"path":"answer"}',
            '"args":{}',
        ),
    }


@pytest.mark.parametrize("case", sorted(_tamperings()))
def test_filter_tampering_is_refused_as_cannot_rebuild(case: str) -> None:
    shape, old, new = _tamperings()[case]
    url4 = compile_candidate(_shapes()[shape], operators=flow_operators()).url4
    assert old in url4, old

    with pytest.raises(ValueError, match="cannot rebuild") as caught:
        sf.Url4(url4.replace(old, new, 1)).to_python()
    # a url4 decode never shows constructor text
    assert "Filter where" not in str(caught.value)
    assert "sf.signal comparison" not in str(caught.value)


def _scripted_filter_run(evidence: dict[str, Any]) -> sf.Report:
    recipe = (
        sf.Fanout(members3())
        >> sf.Filter(where=_CONFIDENCE >= 0.6)  # type: ignore[arg-type]
        >> sf.Synthesize("provider/writer")
    )
    operations = [
        operation_wire("op_model_1", '{"answer":"A","confidence":0.9}'),
        operation_wire("op_model_2", '{"answer":"B","confidence":0.2}'),
        operation_wire("op_model_3", "not json"),
        operation_wire("op_synthesis_1", '{"selected":[]}', combine=evidence),
        operation_wire("op_model_4", "final"),
    ]
    transport = ScriptedTransport(
        "draco", "fixture-revision", lambda _: [case_wire("final", operations)]
    )
    resources = {"draco": benchmark_resource("draco")}
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(engine_handler([], resources=resources)),
        run_transport=transport,
    ) as client:
        return client.evaluate(recipe, benchmark="draco", progress=False)


def _filter_evidence() -> dict[str, Any]:
    """Filter evidence the way the Engine writes it: 1.0 / 0.0 for voters, None for a failure."""

    def member(
        index: int, status: str, score: float | None, confidence: float | None
    ) -> dict[str, Any]:
        failed = status == "fail"
        return {
            "member_id": f"member_{index}",
            "raw": None,
            "value": None,
            "status": status,
            "reason": "not_json" if failed else None,
            "signals": {"field:confidence": confidence},
            "weight": None,
            "score": score,
        }

    return evidence_wire(
        3,
        kind="selection",
        reducer="filter",
        operators=["filter@1", "kept@1"],
        members=[
            member(1, "answered", 1.0, 0.9),
            member(2, "answered", 0.0, 0.2),
            member(3, "fail", None, None),
        ],
        tally=None,
        chosen=["member_1"],
        agreement=None,
        signal={"key": "field:confidence", "order": None},
        result={"member_id": None, "value": None, "status": "answered", "reason": None},
        dropped=1,
    )


def test_a_filter_evidence_case_decodes_with_answers_and_a_select_trace() -> None:
    report = _scripted_filter_run(_filter_evidence())
    case = report.candidates[0].cases.by_id(1)
    assert case.operations is not None

    evidence = case.operations[3].combine
    assert evidence is not None
    assert (evidence.kind, evidence.reducer, evidence.chosen) == (
        "selection",
        "filter",
        ("member_1",),
    )
    # 10E F6: 1.0 kept, 0.0 dropped, None for a member that failed to answer
    assert [row.score for row in evidence.members] == [1.0, 0.0, None]
    answers = case.answers()
    assert [answer.status for answer in answers[:3]] == ["answered", "answered", "fail"]
    trace = [entry for entry in case.trace() if entry.kind == "reduce"]
    assert len(trace) == 1
    assert trace[0].data["op"] == "filter"
    assert trace[0].data["mode"] == "select"
    assert trace[0].to_dict()["chosen"] == ["member_1"]
    assert trace[0].to_dict()["signal"] == {
        "key": "field:confidence",
        "order": None,
        "values": {"member_1": 0.9, "member_2": 0.2, "member_3": None},
    }


def test_equal_comparisons_compile_to_equal_bytes_for_a_negative_zero() -> None:
    """GE21: -0.0 == 0.0 in Python, so they must be one predicate with one set of bytes."""

    negative, positive = _CONFIDENCE >= -0.0, _CONFIDENCE >= 0.0

    assert negative == positive
    assert hash(negative) == hash(positive)
    assert _chain_url4(sf.Filter(where=negative)) == _chain_url4(sf.Filter(where=positive))  # type: ignore[arg-type]
    assert '"value":0.0' in combine_spec_text(
        FilterNode(where=negative),  # type: ignore[arg-type]
        member_count=3,
        operators=flow_operators(),
    )
    assert negative.value == 0.0 and str(negative.value) == "0.0"  # type: ignore[union-attr]
