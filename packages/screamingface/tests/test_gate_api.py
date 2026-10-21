"""The public gate: sf.Gate, the vote's gate= and the reserved verify= slot (E4b part 5, unit 3).

FEATURE: a vote keeps its majority only when one recorded number passes a threshold; the gate is
data in the combine spec (``gate``), and its fallback is named here (E4b part 5, GA#1-9, GA#12a,
GA#19, GA#20, VS#4-6).
STORY: as a benchmark author, I write sf.Vote(gate=sf.Gate("agreement", ">=", 0.7)) and the spec
keeps the majority at 0.7 agreement or more; a typo in the gate fails before any member call.
INVARIANT defended: a Vote without a gate compiles to the same bytes (GA-D1); a gate is a checked
frozen value, never code; verify= takes only None (ans:Q4); the Url4 rebuild keeps the gate and
writes no verify key.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import warnings
from collections.abc import Callable
from types import MappingProxyType
from typing import Any

import pytest
from _combine_contract import ENGINE_APP, engine_operators, read_contract, requires_engine_app
from _nodes import FusionNode, GateNode, JudgeNode, VoteNode, fusion_node
from _vote_run_fixtures import spec_of
from url4 import Expression, RelExpr, Source, Text, build, expr, render, src, struct, text

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface._evaluation.operators import _OperatorCatalog
from screamingface._evaluation.policy import DEFAULT_SYNTHESIS_PROMPT
from screamingface._evaluation.reducer_signals import _signal_call_role
from screamingface._evaluation.topology import _signal_role
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface._surface.chain import Step
from screamingface._surface.lowering import lower
from screamingface.judge import judge_intent
from screamingface.operation import OperationInfo
from screamingface.reducer import _ModelSignal
from screamingface.url4 import _calls, _candidate_expression, _combine_operator_pairs

MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]
CONF_PATTERN = "Confidence: ([0-9]+)"
SECRET = "SECRET-PROMPT-TEXT"
_OUTPUTS = {"member_1": "$model_1", "member_2": "$model_2", "member_3": "$model_3"}
_UNGATED_SPEC = (
    '{"extract":{"args":{},"op":"last_line@1"},"members":["member_1","member_2","member_3"],'
    '"normalize":{"args":{},"op":"text@1"},"reduce":{"args":{},"op":"mode@1"},'
    '"reducer":"vote","schema":"screamingface.combine-spec.v1",'
    '"select":{"args":{},"op":"first_holder@1"},"weights":null}'
)
_GATED_SPEC = (
    '{"extract":{"args":{},"op":"last_line@1"},'
    '"gate":{"cmp":">=","observe":"agreement","otherwise":"abstain","threshold":0.7},'
    '"members":["member_1","member_2","member_3"],'
    '"normalize":{"args":{},"op":"text@1"},"reduce":{"args":{},"op":"mode@1"},'
    '"reducer":"vote","schema":"screamingface.combine-spec.v1",'
    '"select":{"args":{},"op":"first_holder@1"},"weights":null}'
)
_OBSERVE_RULE = (
    "Gate observe must be 'agreement', 'chosen:<name>' or 'mean:<name>', where <name> is a "
    "declared signal name"
)
_E4A_HINT = "; an E4a key such as cost_usd is not a gate input"
_OTHERWISE_RULE = "Gate otherwise must be 'abstain', an sf.Judge or an sf.Model"
_VERIFY_RULE = "sf.Vote verify= is reserved for a later part; pass None or leave it out"
_CHECK_ROUTE = re.compile(r"/benchmarks/ifeval/[A-Za-z0-9]+/check-surface")
# Test-plan §6 list L43, taken on 4e622af75. A FIXED tuple, never a glob: units 3 and 4 add
# url4 files to the same folder (test-plan §6).
_L43: tuple[str, ...] = (
    "argmax_cost_candidate.url4",
    "corrective_vote_candidate.url4",
    "entropy_pick_min_candidate.url4",
    "filter_judge_candidate.url4",
    "filter_pipeline_candidate.url4",
    "judge_order_min_candidate.url4",
    "judge_vote_candidate.url4",
    "logprob_entropy_shared_candidate.url4",
    "logprob_filter_mean_candidate.url4",
    "logprob_filter_prob_candidate.url4",
    "logprob_pick_mean_candidate.url4",
    "logprob_pick_sum_candidate.url4",
    "logprob_rank_mean_candidate.url4",
    "logprob_samples_pick_candidate.url4",
    "logprob_steer_filter_candidate.url4",
    "logprob_vote_prob_candidate.url4",
    "model_synthesizer_candidate.url4",
    "quorum_judge_vote_candidate.url4",
    "quorum_vote_candidate.url4",
    "recipe_s1.url4",
    "recipe_s10.url4",
    "recipe_s11_max.url4",
    "recipe_s12.url4",
    "recipe_s13.url4",
    "recipe_s14.url4",
    "recipe_s15.url4",
    "recipe_s16.url4",
    "recipe_s2.url4",
    "recipe_s3.url4",
    "recipe_s4.url4",
    "recipe_s4_median.url4",
    "recipe_s5.url4",
    "recipe_s5_pick_output.url4",
    "recipe_s7.url4",
    "recipe_s8.url4",
    "recipe_s8_pick_output.url4",
    "recipe_s9.url4",
    "samples_vote_candidate.url4",
    "signal_vote_candidate.url4",
    "two_reducers_candidate.url4",
    "verbalized_vote_candidate.url4",
    "vote_candidate.url4",
    "weighted_median_confidence_candidate.url4",
)


def _compiled(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4


def _fusion(step: Step, **options: Any) -> sf.Pipeline:
    return sf.Fanout(MEMBERS, name="vote", **options) >> step


def _sources(url4: str) -> list[Any]:
    root = build(url4)
    assert isinstance(root, Expression)
    return list(root.sources)


def _by_name(url4: str) -> dict[str, RelExpr]:
    return {
        source.name: source.value
        for source in _sources(url4)
        if isinstance(source, Source)
        and source.name is not None
        and isinstance(source.value, RelExpr)
    }


def _rebuilt(url4: str) -> Any:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    return namespace["candidate"]


def _recompiled(url4: str) -> str:
    """Rebuild ``url4`` as Python, then compile it with the operator ids the url4 pins.

    WHY the check surface: the corrective fixture links the IFEval check route that it holds
    (the same surface as ST/test_engine_url4_contract_fixtures.py:88-104).
    """
    candidate, _ = _candidate_expression(build(url4))
    operators = _OperatorCatalog.from_pinned(_combine_operator_pairs(_calls(candidate)))
    route = _CHECK_ROUTE.search(url4)
    surface = (
        None
        if route is None
        else _CheckSurface(
            check_route=route.group(0), feedback_intent="feedback", expected_check_cost="free"
        )
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate-member and judge-writer warnings: not tested
        return compile_candidate(_rebuilt(url4), operators=operators, check_surface=surface).url4


# --- GA#1: a Vote without a gate keeps its bytes, repr and rebuild ---


@requires_engine_app
def test_vote_without_gate_keeps_its_bytes_repr_and_rebuild() -> None:
    assert repr(sf.Vote()) == "Vote()"
    assert VoteNode()._python() == "sf.Vote(extract='last_line', normalize='text')"
    for name in _L43:
        assert _recompiled(read_contract(name)) == read_contract(name), name


# --- GA#2: an abstain gate compiles to the spec key and adds no call ---


def test_gate_abstain_compiles_the_spec_gate_and_no_extra_call() -> None:
    gate = GateNode("agreement", ">=", 0.7)
    assert gate._spec() == {
        "cmp": ">=",
        "observe": "agreement",
        "otherwise": "abstain",
        "threshold": 0.7,
    }
    assert gate._signal_call() is None
    vote = VoteNode(gate=gate)
    assert vote._plan().gate is gate
    assert vote._plan().signal_calls == ()
    assert combine_spec_text(vote, member_count=3, operators=engine_operators()) == _GATED_SPEC
    url4 = _compiled(_fusion(sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote())))
    sources = _sources(url4)
    assert len(sources) == 5
    assert [source.name for source in sources] == [
        "model_1",
        "model_2",
        "model_3",
        "synthesis_1",
        "_sf_recipe",
    ]
    context = _by_name(url4)["synthesis_1"].context
    assert context == render(struct({"input": "$input", "outputs": _OUTPUTS}))
    assert context is not None and "signals" not in context
    ungated = _compiled(_fusion(sf.Vote()))
    assert {k: v for k, v in spec_of(url4).items() if k != "gate"} == spec_of(ungated)


# --- GA#5: a gate reads a declared signal, and the spec and url4 carry it ---


def test_gate_reads_a_declared_signal() -> None:
    fusion = _fusion(
        sf.Gate(when=sf.signal("conf").chosen() >= 80, then=sf.Vote()),
        signals={"conf": sf.Verbalized(CONF_PATTERN)},
    )
    url4 = _compiled(fusion)
    assert spec_of(url4)["signals"] == {"conf": {"pattern": CONF_PATTERN, "source": "verbalized"}}
    assert spec_of(url4)["gate"] == {
        "cmp": ">=",
        "observe": "chosen:conf",
        "otherwise": "abstain",
        "threshold": 80.0,
    }
    assert (
        '"gate":{"cmp":">=","observe":"chosen:conf","otherwise":"abstain","threshold":80.0}' in url4
    )
    assert GateNode("chosen:conf", ">=", 80)._declared_name() == "conf"
    assert GateNode("mean:lp", "<=", 0.5)._declared_name() == "lp"
    assert GateNode("agreement", ">=", 0.7)._declared_name() is None


# --- GA#6: the constructor refuses a bad observe, cmp or threshold, with fixed messages ---

_BAD_GATE_ARGS: list[tuple[tuple[Any, ...], type[Exception], str]] = [
    ((1, ">=", 0.5), TypeError, "Gate observe must be text"),
    (("agreements", ">=", 0.5), ValueError, _OBSERVE_RULE),
    (("chosen:", ">=", 0.5), ValueError, _OBSERVE_RULE),
    (("chosen:Conf", ">=", 0.5), ValueError, _OBSERVE_RULE),
    (("median:conf", ">=", 0.5), ValueError, _OBSERVE_RULE),
    (("mean:logprob_p", ">=", 0.5), ValueError, _OBSERVE_RULE),
    (("chosen:cost_usd", ">=", 0.5), ValueError, _OBSERVE_RULE + _E4A_HINT),
    (("mean:score:judge", ">=", 0.5), ValueError, _OBSERVE_RULE + _E4A_HINT),
    (("chosen:field:confidence", ">=", 0.5), ValueError, _OBSERVE_RULE + _E4A_HINT),
    (("agreement", "==", 0.5), ValueError, "Gate cmp must be '>=', '>', '<=' or '<'"),
    (("agreement", "=>", 0.5), ValueError, "Gate cmp must be '>=', '>', '<=' or '<'"),
    (("agreement", None, 0.5), ValueError, "Gate cmp must be '>=', '>', '<=' or '<'"),
    (("agreement", ">=", True), TypeError, "Gate threshold must be a number"),
    (("agreement", ">=", "0.7"), TypeError, "Gate threshold must be a number"),
    (("agreement", ">=", None), TypeError, "Gate threshold must be a number"),
    (("chosen:conf", ">=", float("nan")), ValueError, "Gate threshold must be finite"),
    (("chosen:conf", "<", float("-inf")), ValueError, "Gate threshold must be finite"),
    (("chosen:conf", ">=", 10**400), ValueError, "Gate threshold must be finite"),
    (
        ("agreement", "<=", 0.5),
        ValueError,
        "an agreement gate keeps the majority when the agreement is high; use '>=' or '>'",
    ),
    (
        ("agreement", "<", 0.5),
        ValueError,
        "an agreement gate keeps the majority when the agreement is high; use '>=' or '>'",
    ),
    (
        ("agreement", ">=", -0.1),
        ValueError,
        "an agreement gate threshold must be between 0 and 1",
    ),
    (
        ("agreement", ">", 1.5),
        ValueError,
        "an agreement gate threshold must be between 0 and 1",
    ),
]


def test_gate_constructor_refuses_bad_observe_cmp_and_threshold() -> None:
    for args, error, message in _BAD_GATE_ARGS:
        with pytest.raises(error) as caught:
            GateNode(*args)
        assert str(caught.value) == message, args
    assert GateNode("agreement", ">", 0).threshold == 0.0
    assert GateNode("agreement", ">=", 1).threshold == 1.0
    assert GateNode("mean:ent", "<=", -5).threshold == -5.0
    assert GateNode("chosen:conf", "<", 1e300).cmp == "<"


# --- GA#7: the fallback is "abstain", a label judge, or a model; nothing else ---


def test_gate_otherwise_refuses_a_scores_judge_a_named_model_and_a_recipe() -> None:
    scores_judge = JudgeNode("prov/j", returns="scores", rubric=SECRET)
    named_model = sf.Model("prov/w", name="writer", prompt=SECRET)
    optional_model = sf.Model("prov/w", optional=True, prompt=SECRET)
    bad_otherwise: list[tuple[Any, type[Exception], str]] = [
        ("judge", ValueError, _OTHERWISE_RULE),
        ("prov/judge", ValueError, _OTHERWISE_RULE),
        (
            scores_judge,
            ValueError,
            "a gate fallback judge needs sf.Judge(..., returns='label'): it names one member",
        ),
        (
            named_model,
            ValueError,
            "a gate fallback sf.Model takes no name= and is never optional",
        ),
        (
            optional_model,
            ValueError,
            "a gate fallback sf.Model takes no name= and is never optional",
        ),
        (fusion_node(["p/a", "p/b"], VoteNode()), TypeError, _OTHERWISE_RULE),
        (VoteNode(), TypeError, _OTHERWISE_RULE),
        (None, TypeError, _OTHERWISE_RULE),
    ]
    for otherwise, error, message in bad_otherwise:
        with pytest.raises(error) as caught:
            GateNode("agreement", ">=", 0.7, otherwise=otherwise)
        assert str(caught.value) == message
        assert SECRET not in str(caught.value)
    label_judge = JudgeNode(
        "prov/j", returns="label", rubric="Pick the best answer.", params={"temperature": 0}
    )
    model = sf.Model("prov/w", prompt="Write one answer.")
    assert GateNode("agreement", ">=", 0.7, otherwise=label_judge).otherwise is label_judge
    assert GateNode("agreement", ">=", 0.7, otherwise=model).otherwise is model
    assert GateNode("agreement", ">=", 0.7).otherwise == "abstain"


# --- GA#8: a Fusion refuses a gate that reads a name it does not declare, before any call ---


def test_fusion_refuses_a_gate_that_reads_an_undeclared_name() -> None:
    vote = sf.Gate(when=sf.signal("lp").mean() >= 0.5, then=sf.Vote())
    with pytest.raises(ValueError) as caught:
        _fusion(vote)
    assert str(caught.value) == (
        "the gate reads 'mean:lp', but this Fusion does not declare 'lp' (declared: none)"
    )
    with pytest.raises(ValueError) as caught:
        _fusion(vote, signals={"conf": sf.Verbalized(CONF_PATTERN)})
    assert str(caught.value) == (
        "the gate reads 'mean:lp', but this Fusion does not declare 'lp' (declared: conf)"
    )
    _fusion(
        sf.Gate(when=sf.signal("conf").mean() >= 50, then=sf.Vote()),
        signals={"conf": sf.Verbalized(CONF_PATTERN)},
    )
    _fusion(sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote()))


# --- GA#9: sf.Vote refuses a gate= that is not an sf.Gate ---


def test_vote_refuses_a_gate_that_is_not_a_gate() -> None:
    not_gates: list[Any] = [
        "agreement >= 0.7",
        {"observe": "agreement", "cmp": ">=", "threshold": 0.7},
        JudgeNode("prov/j", returns="label", rubric="Pick."),
    ]
    for gate in not_gates:
        with pytest.raises(TypeError) as caught:
            VoteNode(gate=gate)
        assert str(caught.value) == "Vote gate must be an sf.Gate"


# --- GA#12a: a gated vote survives to_python, the repr and the recompile ---


def test_gated_votes_round_trip_through_to_python() -> None:
    abstain_gate = GateNode("agreement", ">=", 0.7)
    verbalized_gate = GateNode("chosen:conf", ">=", 80)
    cases: list[tuple[sf.Recipe, GateNode, str, str]] = [
        (
            _fusion(sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote())),
            abstain_gate,
            "    synthesizer=sf.Vote(extract='last_line@1', normalize='text@1', "
            "gate=sf.Gate('agreement', '>=', 0.7)),",
            "Fusion(['alpha', 'beta', 'gamma'], name='vote', "
            "synthesizer=Vote(extract='last_line@1', normalize='text@1', "
            "gate=Gate('agreement', '>=', 0.7)))",
        ),
        (
            _fusion(
                sf.Gate(when=sf.signal("conf").chosen() >= 80, then=sf.Vote()),
                signals={"conf": sf.Verbalized(CONF_PATTERN)},
            ),
            verbalized_gate,
            "    synthesizer=sf.Vote(extract='last_line@1', normalize='text@1', "
            "gate=sf.Gate('chosen:conf', '>=', 80.0)),",
            "Fusion(['alpha', 'beta', 'gamma'], name='vote', signals={'conf': "
            "Verbalized('Confidence: ([0-9]+)')}, synthesizer=Vote(extract='last_line@1', "
            "normalize='text@1', gate=Gate('chosen:conf', '>=', 80.0)))",
        ),
    ]
    for fusion, gate, line, literal in cases:
        url4 = _compiled(fusion)
        assert line in sf.Url4(url4).to_python().splitlines()
        assert repr(_rebuilt(url4)) == literal
        assert _rebuilt(url4).synthesizer.gate == gate
        assert _compiled(_rebuilt(url4)) == url4


# --- GA#19: the repr and the Python form of a gate and of a gated vote ---


def test_gate_repr_and_python_form() -> None:
    writer = GateNode("agreement", ">=", 0.7, otherwise=sf.Model("prov/w", prompt="Write."))
    assert repr(writer) == (
        "Gate('agreement', '>=', 0.7, otherwise=Model('prov/w', prompt='Write.'))"
    )
    assert writer._python() == (
        "sf.Gate('agreement', '>=', 0.7, otherwise=sf.Model('prov/w', prompt='Write.'))"
    )
    judge = GateNode(
        "agreement",
        ">",
        0.5,
        otherwise=JudgeNode("prov/j", returns="label", rubric="Pick."),
    )
    assert repr(judge) == (
        "Gate('agreement', '>', 0.5, otherwise=Judge('prov/j', returns='label', rubric='Pick.'))"
    )
    assert judge._python() == (
        "sf.Gate('agreement', '>', 0.5, otherwise=sf.Judge('prov/j', returns='label', "
        "rubric='Pick.'))"
    )
    whole = GateNode("agreement", ">=", 1)
    assert whole.threshold == 1.0
    assert type(whole.threshold) is float
    assert repr(whole) == "Gate('agreement', '>=', 1.0)"
    assert whole._python() == "sf.Gate('agreement', '>=', 1.0)"
    explicit = GateNode("chosen:conf", "<=", 5, otherwise="abstain")
    assert repr(explicit) == "Gate('chosen:conf', '<=', 5.0)"
    assert explicit == GateNode("chosen:conf", "<=", 5.0)
    assert [gate._spec()["otherwise"] for gate in (explicit, judge, writer)] == [
        "abstain",
        "judge",
        "writer",
    ]
    assert repr(VoteNode(gate=GateNode("agreement", ">=", 0.7))) == (
        "Vote(extract='last_line', normalize='text', gate=Gate('agreement', '>=', 0.7))"
    )
    assert VoteNode(gate=GateNode("agreement", ">=", 0.7))._python() == (
        "sf.Vote(extract='last_line', normalize='text', gate=sf.Gate('agreement', '>=', 0.7))"
    )
    assert repr(VoteNode(extract="benchmark", gate=GateNode("agreement", ">", 0.5))) == (
        "Vote(extract='benchmark', gate=Gate('agreement', '>', 0.5))"
    )


# --- GA#20: the names, kinds and defaults of the new public parameters (introspection) ---


def test_public_surface_lists_gate_and_the_vote_parameters() -> None:
    vote_parameters = inspect.signature(VoteNode).parameters
    assert {"gate", "verify"} <= set(vote_parameters)
    assert vote_parameters["gate"].kind is inspect.Parameter.KEYWORD_ONLY
    assert vote_parameters["gate"].default is None
    assert str(vote_parameters["verify"]) == "verify: 'None' = None"
    assert "Gate" in sf.__all__
    gate_parameters = inspect.signature(GateNode).parameters
    assert list(gate_parameters) == ["observe", "cmp", "threshold", "otherwise", "abstain_band"]
    assert gate_parameters["otherwise"].kind is inspect.Parameter.KEYWORD_ONLY
    assert gate_parameters["otherwise"].default == "abstain"


# --- VS#4: verify=None is accepted and keeps the bytes of a Vote without it ---


def test_vote_accepts_verify_none_and_keeps_its_bytes() -> None:
    plain = sf.Vote()
    slot = sf.Vote(verify=None)
    plain_node = VoteNode()
    slot_node = VoteNode(verify=None, gate=None)
    assert slot == plain
    assert slot.verify is None
    assert plain.verify is None
    assert slot_node.gate is None
    assert plain_node.gate is None
    assert (
        combine_spec_text(slot_node, member_count=3, operators=engine_operators()) == _UNGATED_SPEC
    )
    assert _compiled(_fusion(slot)) == _compiled(_fusion(plain))


# --- VS#5: verify takes only None; any other value is refused with a fixed message ---


def test_vote_refuses_any_verify_value_but_none() -> None:
    values: list[Any] = [lambda answer: True, "model", False, 0, {}]
    for value in values:
        with pytest.raises(ValueError) as caught:
            sf.Vote(verify=value)
        assert str(caught.value) == _VERIFY_RULE


# --- VS#6: verify is never shown in the repr, the Python form or the url4 ---


def test_vote_repr_and_rebuild_leave_verify_out() -> None:
    assert repr(sf.Vote(verify=None)) == "Vote()"
    vote = sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote(verify=None))
    assert "verify" not in repr(vote)
    assert "verify" not in VoteNode(verify=None, gate=GateNode("agreement", ">=", 0.7))._python()
    url4 = _compiled(_fusion(vote))
    assert "verify" not in url4
    assert "verify" not in sf.Url4(url4).to_python()
    assert _rebuilt(url4).synthesizer.verify is None


# ---- E4b part 5 unit 4 (gate-api-fallback): GA#3, 4, 10, 11, 12b, 13, 14, 15, 16 ----

_FB_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]
_FB_RUBRIC = "Pick the best answer."
_FB_WRITE = "Write one answer."
_FB_OUTPUTS = (
    "{input: '$input', outputs: {member_1: '$model_1', member_2: '$model_2', member_3: '$model_3'}}"
)
_FB_PANEL = "{input: '$input', panel: '$panel_1'}"
_FB_MEMBER_OPS = ("op_model_1", "op_model_2", "op_model_3")
_FB_ENGINE_SPEC = ENGINE_APP / "src" / "screamingface_engine" / "combine" / "spec.py"


def _fb_judge(params: dict[str, Any] | None = None) -> sf.JudgePick:
    return sf.JudgePick("prov/judge", rubric=_FB_RUBRIC, params=params)


def _fb_writer(params: dict[str, Any] | None = None) -> sf.Synthesize:
    return sf.Synthesize(sf.Model("prov/writer", prompt=_FB_WRITE, params=params))


def _fb_fusion(
    otherwise: Any,
    *,
    judge: sf.Judge | None = None,
    weights: Any = None,
    members: list[Any] | None = None,
    quorum: Any = "all",
) -> sf.Pipeline:
    fanout = sf.Fanout(_FB_MEMBERS if members is None else members, name="vote", quorum=quorum)
    gate = sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote(weights=weights), otherwise=otherwise)
    return fanout >> gate if judge is None else fanout >> judge >> gate


def _fb_compiled(recipe: sf.Recipe) -> Any:
    return compile_candidate(recipe, operators=engine_operators())


def _fb_root(url4: str) -> Expression:
    root = build(url4)
    assert isinstance(root, Expression)
    return root


def _fb_calls(url4: str) -> dict[str, Any]:
    return _calls(_fb_root(url4))


def _fb_source_names(url4: str) -> list[str | None]:
    return [source.name for source in _fb_root(url4).sources if isinstance(source, Source)]


def _fb_rider_synthesizer(url4: str) -> Any:
    riders = [
        source
        for source in _fb_root(url4).sources
        if isinstance(source, Source) and source.name == "_sf_recipe"
    ]
    assert len(riders) == 1
    rider = riders[0].value
    assert isinstance(rider, Text)
    return json.loads(rider.value)["recipe"]["synthesizer"]


def _fb_recovered(url4: str) -> FusionNode:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    candidate = namespace["candidate"]
    assert isinstance(candidate, FusionNode)
    return candidate


def _fb_linked(candidate: str) -> str:
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("/benchmarks/ifeval/revision-1/cases", name="rows", weight=0.0),
            intent=text("$rows"),
        )
    )


def test_judge_fallback_compiles_one_label_judge_call() -> None:
    compiled = _fb_compiled(_fb_fusion(_fb_judge()))
    url4 = compiled.url4
    calls = _fb_calls(url4)

    assert _fb_source_names(url4) == [
        "model_1",
        "model_2",
        "model_3",
        "judge_1",
        "synthesis_1",
        "_sf_recipe",
    ]
    judge = calls["judge_1"]
    assert judge.model == "prov/judge"
    assert judge.context == _FB_OUTPUTS
    assert judge.prompt.startswith("judge-template@1 returns=label\n")
    assert judge.prompt.endswith("Rubric:\nPick the best answer.")
    assert judge.prompt == judge_intent("label", _FB_RUBRIC)
    assert judge.params == (("binding", "judge_1"),)
    assert calls["synthesis_1"].context == (
        "{input: '$input', outputs: {member_1: '$model_1', member_2: '$model_2', "
        "member_3: '$model_3'}, signals: {fallback_judge: '$judge_1'}}"
    )
    assert decode_combine_spec(calls["synthesis_1"].raw_intent)["gate"] == {
        "cmp": ">=",
        "observe": "agreement",
        "otherwise": "judge",
        "threshold": 0.7,
    }
    assert compiled.operations[3:] == (
        OperationInfo(
            id="op_judge_1", kind="judge", label="vote fallback judge", depends_on=_FB_MEMBER_OPS
        ),
        OperationInfo(
            id="op_synthesis_1",
            kind="combine",
            label="vote combine",
            depends_on=(*_FB_MEMBER_OPS, "op_judge_1"),
        ),
    )
    assert compiled.models == ("prov/alpha", "prov/beta", "prov/gamma", "prov/judge")
    assert _fb_rider_synthesizer(url4) == {
        "binding": "synthesis_1",
        "kind": "reducer",
        "name": "vote",
        "signals": [
            {
                "key": "fallback_judge",
                "source": {
                    "binding": "judge_1",
                    "kind": "model",
                    "name": "judge",
                    "named": False,
                    "role": "judge",
                },
            }
        ],
    }


def test_writer_fallback_compiles_one_writer_call_without_projection() -> None:
    compiled = _fb_compiled(_fb_fusion(_fb_writer()))
    url4 = compiled.url4
    calls = _fb_calls(url4)

    assert _fb_source_names(url4) == [
        "model_1",
        "model_2",
        "model_3",
        "writer_1",
        "synthesis_1",
        "_sf_recipe",
    ]
    writer = calls["writer_1"]
    assert writer.model == "prov/writer"
    assert writer.context == _FB_OUTPUTS
    assert writer.prompt == _FB_WRITE
    assert writer.params == (("binding", "writer_1"),)
    assert calls["synthesis_1"].context == (
        "{input: '$input', outputs: {member_1: '$model_1', member_2: '$model_2', "
        "member_3: '$model_3'}, signals: {fallback_writer: '$writer_1'}}"
    )
    assert decode_combine_spec(calls["synthesis_1"].raw_intent)["gate"] == {
        "cmp": ">=",
        "observe": "agreement",
        "otherwise": "writer",
        "threshold": 0.7,
    }
    assert compiled.operations[3:] == (
        OperationInfo(
            id="op_writer_1", kind="writer", label="vote fallback write", depends_on=_FB_MEMBER_OPS
        ),
        OperationInfo(
            id="op_synthesis_1",
            kind="combine",
            label="vote combine",
            depends_on=(*_FB_MEMBER_OPS, "op_writer_1"),
        ),
    )
    assert compiled.models == ("prov/alpha", "prov/beta", "prov/gamma", "prov/writer")
    assert _fb_rider_synthesizer(url4)["signals"] == [
        {
            "key": "fallback_writer",
            "source": {
                "binding": "writer_1",
                "kind": "model",
                "name": "writer",
                "named": False,
                "role": "writer",
            },
        }
    ]
    # FC-I3: a fallback writer never names a projection field
    with pytest.raises(ValueError, match="reducer signal key does not match its field"):
        _signal_call_role(
            _ModelSignal("fallback_writer", "prov/w", "W.", MappingProxyType({}), "x")
        )


@pytest.mark.parametrize("fallback", ["judge", "writer"])
def test_quorum_panel_gives_the_fallback_the_panel(fallback: str) -> None:
    otherwise = _fb_judge() if fallback == "judge" else _fb_writer()
    members = ["prov/alpha", "prov/beta", sf.Model("prov/gamma", optional=True)]
    url4 = _fb_compiled(_fb_fusion(otherwise, members=members, quorum=2)).url4
    call = _fb_calls(url4)[f"{fallback}_1"]

    assert call.context == _FB_PANEL
    if fallback == "judge":
        assert call.prompt.startswith("judge-template@1 returns=label input=panel\n")
        assert call.prompt == judge_intent("label", _FB_RUBRIC, "panel")
    else:
        assert call.prompt == _FB_WRITE
    assert _fb_compiled(_fb_recovered(url4)).url4 == url4


@pytest.mark.parametrize("fallback", ["judge", "writer"])
def test_fallback_params_go_to_the_preflight(fallback: str) -> None:
    params = {"temperature": 0}
    otherwise = _fb_judge(params) if fallback == "judge" else _fb_writer(params)
    compiled = _fb_compiled(_fb_fusion(otherwise))
    route = f"prov/{fallback}"

    assert [(a.operation_id, a.model, dict(a.params)) for a in compiled.parameter_assignments] == [
        (f"op_{fallback}_1", route, {"temperature": 0})
    ]
    assert _fb_calls(compiled.url4)[f"{fallback}_1"].params == (
        ("binding", f"{fallback}_1"),
        ("temperature", "0"),
    )


def _fb_round_trip_recipes() -> dict[str, sf.Pipeline]:
    return {
        "judge": _fb_fusion(_fb_judge()),
        "judge_weighted": _fb_fusion(
            _fb_judge(),
            judge=sf.Judge("prov/scorer", rubric="Score."),
            weights=sf.signal("score:judge"),
        ),
        "writer": _fb_fusion(_fb_writer()),
    }


@pytest.mark.parametrize("name", ["judge", "judge_weighted", "writer"])
def test_gated_votes_with_a_fallback_call_round_trip_through_to_python(name: str) -> None:
    recipe = _fb_round_trip_recipes()[name]
    compiled = _fb_compiled(recipe)
    source = sf.Url4(compiled.url4).to_python()
    rebuilt = _fb_recovered(compiled.url4)
    # WHY lower: the rebuild gives the internal node that the chain lowers to (until 7e).
    lowered = lower(recipe)
    assert isinstance(lowered, FusionNode)
    original_vote, rebuilt_vote = lowered.synthesizer, rebuilt.synthesizer
    assert isinstance(original_vote, VoteNode)
    assert isinstance(rebuilt_vote, VoteNode)
    assert original_vote.gate is not None

    assert _fb_compiled(rebuilt).url4 == compiled.url4
    assert rebuilt_vote.gate == original_vote.gate
    assert repr(rebuilt_vote.gate) == repr(original_vote.gate)
    assert rebuilt_vote.judge == original_vote.judge
    assert original_vote.gate._python() in source
    assert _candidate_from_url4(_fb_linked(compiled.url4)).operations == compiled.operations


_FB_GATE_ABSTAIN = (
    '"gate":{"cmp":">=","observe":"agreement","otherwise":"abstain","threshold":0.7},'
)
_FB_GATE_JUDGE = '"gate":{"cmp":">=","observe":"agreement","otherwise":"judge","threshold":0.7},'
_FB_SPEC_MEMBERS = '"members":["member_1","member_2","member_3"],'


def _fb_hand_edits() -> dict[str, tuple[Callable[[], sf.Recipe], str, str]]:
    """case -> (recipe builder, text to replace (exactly once in the url4), replacement).

    WHY builders: each case compiles only its own recipe, so a case that fails at compile does
    not hide the result of the other cases.
    """

    return {
        "gate_on_a_median": (
            lambda: sf.Fanout(_FB_MEMBERS, name="vote") >> sf.Median(),
            _FB_SPEC_MEMBERS,
            _FB_GATE_ABSTAIN + _FB_SPEC_MEMBERS,
        ),
        "fallback_call_without_a_gate": (
            lambda: _fb_fusion(_fb_judge()),
            _FB_GATE_JUDGE,
            "",
        ),
        "judge_gate_without_its_call": (
            lambda: (
                sf.Fanout(_FB_MEMBERS, name="vote")
                >> sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote())
            ),
            '"otherwise":"abstain"',
            '"otherwise":"judge"',
        ),
        "writer_gate_with_a_judge_call": (
            lambda: _fb_fusion(_fb_judge()),
            '"otherwise":"judge"',
            '"otherwise":"writer"',
        ),
    }


@pytest.mark.parametrize(
    "case",
    [
        "fallback_call_without_a_gate",
        "gate_on_a_median",
        "judge_gate_without_its_call",
        "writer_gate_with_a_judge_call",
    ],
)
def test_hand_edited_gate_urls_cannot_rebuild(case: str) -> None:
    build_recipe, old, new = _fb_hand_edits()[case]
    url4 = _fb_compiled(build_recipe()).url4
    assert url4.count(old) == 1
    tampered = url4.replace(old, new)

    with pytest.raises(ValueError, match="cannot rebuild|invalid Reducer topology metadata"):
        sf.Url4(tampered).to_python()


def test_hand_edited_gate_vote_with_two_fallback_calls_cannot_rebuild() -> None:
    fallback = JudgeNode("prov/judge", returns="label", rubric=_FB_RUBRIC)
    vote = VoteNode(gate=GateNode("agreement", ">=", 0.7, otherwise=fallback))
    spec = decode_combine_spec(
        combine_spec_text(vote, member_count=3, operators=engine_operators())
    )
    judge = _ModelSignal(
        "fallback_judge", "prov/judge", judge_intent("label", _FB_RUBRIC), MappingProxyType({})
    )
    writer = _ModelSignal("fallback_writer", "prov/writer", _FB_WRITE, MappingProxyType({}))

    with pytest.raises(ValueError, match="cannot rebuild"):
        VoteNode._rebuild(spec, (judge, writer))


def test_writer_default_prompt_rebuilds_without_prompt() -> None:
    recipe = _fb_fusion(sf.Synthesize("prov/writer"))
    url4 = _fb_compiled(recipe).url4

    assert _fb_calls(url4)["writer_1"].prompt == DEFAULT_SYNTHESIS_PROMPT
    assert "gate=sf.Gate('agreement', '>=', 0.7, otherwise=sf.Model('prov/writer'))" in (
        sf.Url4(url4).to_python()
    )
    rebuilt = _fb_recovered(url4)
    vote = rebuilt.synthesizer
    assert isinstance(vote, VoteNode)
    assert vote.gate is not None
    assert isinstance(vote.gate.otherwise, sf.Model)
    assert vote.gate.otherwise.prompt is None
    assert _fb_compiled(rebuilt).url4 == url4


def test_judge_weighted_vote_with_a_judge_fallback_has_two_judge_calls() -> None:
    compiled = _fb_compiled(_fb_round_trip_recipes()["judge_weighted"])
    url4 = compiled.url4
    calls = _fb_calls(url4)

    assert _fb_source_names(url4) == [
        "model_1",
        "model_2",
        "model_3",
        "judge_1",
        "judge_2",
        "synthesis_1",
        "_sf_recipe",
    ]
    assert (calls["judge_1"].model, calls["judge_1"].prompt) == (
        "prov/scorer",
        judge_intent("scores", "Score."),
    )
    assert (calls["judge_2"].model, calls["judge_2"].prompt) == (
        "prov/judge",
        judge_intent("label", _FB_RUBRIC),
    )
    assert calls["synthesis_1"].context.endswith(
        "signals: {judge: '$judge_1', fallback_judge: '$judge_2'}}"
    )
    assert compiled.operations[3:] == (
        OperationInfo(id="op_judge_1", kind="judge", label="vote judge", depends_on=_FB_MEMBER_OPS),
        OperationInfo(
            id="op_judge_2", kind="judge", label="vote fallback judge", depends_on=_FB_MEMBER_OPS
        ),
        OperationInfo(
            id="op_synthesis_1",
            kind="combine",
            label="vote combine",
            depends_on=(*_FB_MEMBER_OPS, "op_judge_1", "op_judge_2"),
        ),
    )
    assert [signal["key"] for signal in _fb_rider_synthesizer(url4)["signals"]] == [
        "judge",
        "fallback_judge",
    ]


def _fb_engine_signal_pattern() -> re.Pattern[str]:
    tree = ast.parse(_FB_ENGINE_SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_SIGNAL" for target in node.targets
        ):
            call = node.value
            assert isinstance(call, ast.Call)
            first = call.args[0]
            assert isinstance(first, ast.Constant)
            assert isinstance(first.value, str)
            return re.compile(first.value)
    raise AssertionError("the engine `_SIGNAL` pattern moved - update the bind")


@requires_engine_app
def test_signal_key_bind_accepts_the_fallback_keys() -> None:
    assert _FB_ENGINE_SPEC.exists(), "engine combine/spec.py moved - update the bind"
    pattern = _fb_engine_signal_pattern()

    assert {key: _signal_role(key) for key in ("fallback_judge", "fallback_writer")} == {
        "fallback_judge": "judge",
        "fallback_writer": "writer",
    }
    for key in ("fallback_judge", "fallback_writer"):
        assert pattern.fullmatch(key), key
    for refused in ("fallback_", "fallback_x", "Fallback_judge"):
        assert pattern.fullmatch(refused) is None, refused
        assert _signal_role(refused) is None, refused
