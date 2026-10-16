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

import inspect
import re
import warnings
from typing import Any

import pytest
from _combine_contract import engine_operators, read_contract, requires_engine_app
from _vote_run_fixtures import spec_of
from url4 import Expression, RelExpr, Source, build, render, struct

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface._evaluation.operators import _OperatorCatalog
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


def _fusion(vote: sf.Vote, **options: Any) -> sf.Fusion:
    return sf.Fusion(MEMBERS, name="vote", synthesizer=vote, **options)


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
    assert repr(sf.Vote()) == "Vote(extract='last_line', normalize='text')"
    assert sf.Vote()._python() == "sf.Vote(extract='last_line', normalize='text')"
    for name in _L43:
        assert _recompiled(read_contract(name)) == read_contract(name), name


# --- GA#2: an abstain gate compiles to the spec key and adds no call ---


def test_gate_abstain_compiles_the_spec_gate_and_no_extra_call() -> None:
    gate = sf.Gate("agreement", ">=", 0.7)
    assert gate._spec() == {
        "cmp": ">=",
        "observe": "agreement",
        "otherwise": "abstain",
        "threshold": 0.7,
    }
    assert gate._signal_call() is None
    vote = sf.Vote(gate=gate)
    assert vote._plan().gate is gate
    assert vote._plan().signal_calls == ()
    assert combine_spec_text(vote, member_count=3, operators=engine_operators()) == _GATED_SPEC
    url4 = _compiled(_fusion(vote))
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
    assert "signals" not in context
    ungated = _compiled(_fusion(sf.Vote()))
    assert {k: v for k, v in spec_of(url4).items() if k != "gate"} == spec_of(ungated)


# --- GA#5: a gate reads a declared signal, and the spec and url4 carry it ---


def test_gate_reads_a_declared_signal() -> None:
    fusion = sf.Fusion(
        MEMBERS,
        name="vote",
        signals={"conf": sf.Verbalized(CONF_PATTERN)},
        synthesizer=sf.Vote(gate=sf.Gate("chosen:conf", ">=", 80)),
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
    assert sf.Gate("chosen:conf", ">=", 80)._declared_name() == "conf"
    assert sf.Gate("mean:lp", "<=", 0.5)._declared_name() == "lp"
    assert sf.Gate("agreement", ">=", 0.7)._declared_name() is None


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
            sf.Gate(*args)
        assert str(caught.value) == message, args
    assert sf.Gate("agreement", ">", 0).threshold == 0.0
    assert sf.Gate("agreement", ">=", 1).threshold == 1.0
    assert sf.Gate("mean:ent", "<=", -5).threshold == -5.0
    assert sf.Gate("chosen:conf", "<", 1e300).cmp == "<"


# --- GA#7: the fallback is "abstain", a label judge, or a model; nothing else ---


def test_gate_otherwise_refuses_a_scores_judge_a_named_model_and_a_recipe() -> None:
    scores_judge = sf.Judge("prov/j", returns="scores", rubric=SECRET)
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
        (sf.Fusion(["p/a", "p/b"], synthesizer=sf.Vote()), TypeError, _OTHERWISE_RULE),
        (sf.Vote(), TypeError, _OTHERWISE_RULE),
        (None, TypeError, _OTHERWISE_RULE),
    ]
    for otherwise, error, message in bad_otherwise:
        with pytest.raises(error) as caught:
            sf.Gate("agreement", ">=", 0.7, otherwise=otherwise)
        assert str(caught.value) == message
        assert SECRET not in str(caught.value)
    label_judge = sf.Judge(
        "prov/j", returns="label", rubric="Pick the best answer.", params={"temperature": 0}
    )
    model = sf.Model("prov/w", prompt="Write one answer.")
    assert sf.Gate("agreement", ">=", 0.7, otherwise=label_judge).otherwise is label_judge
    assert sf.Gate("agreement", ">=", 0.7, otherwise=model).otherwise is model
    assert sf.Gate("agreement", ">=", 0.7).otherwise == "abstain"


# --- GA#8: a Fusion refuses a gate that reads a name it does not declare, before any call ---


def test_fusion_refuses_a_gate_that_reads_an_undeclared_name() -> None:
    vote = sf.Vote(gate=sf.Gate("mean:lp", ">=", 0.5))
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
        sf.Vote(gate=sf.Gate("mean:conf", ">=", 50)),
        signals={"conf": sf.Verbalized(CONF_PATTERN)},
    )
    _fusion(sf.Vote(gate=sf.Gate("agreement", ">=", 0.7)))


# --- GA#9: sf.Vote refuses a gate= that is not an sf.Gate ---


def test_vote_refuses_a_gate_that_is_not_a_gate() -> None:
    not_gates: list[Any] = [
        "agreement >= 0.7",
        {"observe": "agreement", "cmp": ">=", "threshold": 0.7},
        sf.Judge("prov/j", returns="label", rubric="Pick."),
    ]
    for gate in not_gates:
        with pytest.raises(TypeError) as caught:
            sf.Vote(gate=gate)
        assert str(caught.value) == "Vote gate must be an sf.Gate"


# --- GA#12a: a gated vote survives to_python, the repr and the recompile ---


def test_gated_votes_round_trip_through_to_python() -> None:
    abstain_gate = sf.Gate("agreement", ">=", 0.7)
    verbalized_gate = sf.Gate("chosen:conf", ">=", 80)
    cases: list[tuple[sf.Fusion, sf.Gate, str, str]] = [
        (
            _fusion(sf.Vote(gate=abstain_gate)),
            abstain_gate,
            "    synthesizer=sf.Vote(extract='last_line@1', normalize='text@1', "
            "gate=sf.Gate('agreement', '>=', 0.7)),",
            "Fusion(['alpha', 'beta', 'gamma'], name='vote', "
            "synthesizer=Vote(extract='last_line@1', normalize='text@1', "
            "gate=Gate('agreement', '>=', 0.7)))",
        ),
        (
            sf.Fusion(
                MEMBERS,
                name="vote",
                signals={"conf": sf.Verbalized(CONF_PATTERN)},
                synthesizer=sf.Vote(gate=verbalized_gate),
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
    writer = sf.Gate("agreement", ">=", 0.7, otherwise=sf.Model("prov/w", prompt="Write."))
    assert repr(writer) == (
        "Gate('agreement', '>=', 0.7, otherwise=Model('prov/w', prompt='Write.'))"
    )
    assert writer._python() == (
        "sf.Gate('agreement', '>=', 0.7, otherwise=sf.Model('prov/w', prompt='Write.'))"
    )
    judge = sf.Gate(
        "agreement",
        ">",
        0.5,
        otherwise=sf.Judge("prov/j", returns="label", rubric="Pick."),
    )
    assert repr(judge) == (
        "Gate('agreement', '>', 0.5, otherwise=Judge('prov/j', returns='label', rubric='Pick.'))"
    )
    assert judge._python() == (
        "sf.Gate('agreement', '>', 0.5, otherwise=sf.Judge('prov/j', returns='label', "
        "rubric='Pick.'))"
    )
    whole = sf.Gate("agreement", ">=", 1)
    assert whole.threshold == 1.0
    assert type(whole.threshold) is float
    assert repr(whole) == "Gate('agreement', '>=', 1.0)"
    assert whole._python() == "sf.Gate('agreement', '>=', 1.0)"
    explicit = sf.Gate("chosen:conf", "<=", 5, otherwise="abstain")
    assert repr(explicit) == "Gate('chosen:conf', '<=', 5.0)"
    assert explicit == sf.Gate("chosen:conf", "<=", 5.0)
    assert [gate._spec()["otherwise"] for gate in (explicit, judge, writer)] == [
        "abstain",
        "judge",
        "writer",
    ]
    assert repr(sf.Vote(gate=sf.Gate("agreement", ">=", 0.7))) == (
        "Vote(extract='last_line', normalize='text', gate=Gate('agreement', '>=', 0.7))"
    )
    assert sf.Vote(gate=sf.Gate("agreement", ">=", 0.7))._python() == (
        "sf.Vote(extract='last_line', normalize='text', gate=sf.Gate('agreement', '>=', 0.7))"
    )
    assert repr(sf.Vote(extract="benchmark", gate=sf.Gate("agreement", ">", 0.5))) == (
        "Vote(extract='benchmark', gate=Gate('agreement', '>', 0.5))"
    )


# --- GA#20: the names, kinds and defaults of the new public parameters (introspection) ---


def test_public_surface_lists_gate_and_the_vote_parameters() -> None:
    vote_parameters = inspect.signature(sf.Vote).parameters
    assert {"gate", "verify"} <= set(vote_parameters)
    assert vote_parameters["gate"].kind is inspect.Parameter.KEYWORD_ONLY
    assert vote_parameters["gate"].default is None
    assert str(vote_parameters["verify"]) == "verify: 'None' = None"
    assert "Gate" in sf.__all__
    gate_parameters = inspect.signature(sf.Gate).parameters
    assert list(gate_parameters) == ["observe", "cmp", "threshold", "otherwise"]
    assert gate_parameters["otherwise"].kind is inspect.Parameter.KEYWORD_ONLY
    assert gate_parameters["otherwise"].default == "abstain"


# --- VS#4: verify=None is accepted and keeps the bytes of a Vote without it ---


def test_vote_accepts_verify_none_and_keeps_its_bytes() -> None:
    plain = sf.Vote()
    slot = sf.Vote(verify=None, gate=None)
    assert slot == plain
    assert slot.verify is None
    assert plain.verify is None
    assert slot.gate is None
    assert plain.gate is None
    assert combine_spec_text(slot, member_count=3, operators=engine_operators()) == _UNGATED_SPEC
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
    assert repr(sf.Vote(verify=None)) == "Vote(extract='last_line', normalize='text')"
    vote = sf.Vote(verify=None, gate=sf.Gate("agreement", ">=", 0.7))
    assert "verify" not in repr(vote)
    assert "verify" not in vote._python()
    url4 = _compiled(_fusion(vote))
    assert "verify" not in url4
    assert "verify" not in sf.Url4(url4).to_python()
    assert _rebuilt(url4).synthesizer.verify is None
