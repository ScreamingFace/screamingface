"""sf.Consistency: how often a member gives the same answer again (E4b part 7, consistency@N).

FEATURE: ``sf.Fusion(members, signals={"cons": sf.Consistency(n=5)}, ...)`` asks each member n
more times with distinct seeds at the stated temperature (ans:Q3).
STORY: as a benchmark author, I pick the member answer that its model gives most often again.
INVARIANT defended: n is an int from 1 to 32 and the temperature a finite number >= 0, default
1.0 (P2); a sf.Fanout declares at most one sf.Consistency, each member is one sf.Model, at most 1024
extra calls, and no member seed equals a sample seed of the Fusion (P4, P5; erd CN-I1..CN-I5).
"""

from __future__ import annotations

import copy
import dataclasses
import inspect
import json
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from _combine_contract import engine_operators, read_contract, requires_engine_app
from _model_parameter_fixtures import details as model_details
from test_accounting_breakdown import accounting as fixture_accounting
from test_accounting_breakdown import replace as replace_fields
from test_consistency_contract_fixtures import consistency_median_recipe, consistency_pick_recipe
from test_engine_url4_contract_fixtures import samples_vote_url4
from test_gate_contract_fixtures import gate_judge_vote_url4
from test_logprob_entropy_url4_fixtures import logprob_pick_mean
from test_quorum_url4_contract_fixtures import quorum_vote_url4
from test_report_panel import candidate as report_candidate
from test_report_panel import case as report_case
from test_vote_median_contract_fixtures import vote_candidate_url4
from url4 import Expression, RelExpr, Source, Text, build
from url4.core.nodes import walk

import screamingface as sf
from screamingface._engine.model_parameters import _decode_model_details
from screamingface._evaluation.candidate import _CompiledCandidate, compile_candidate
from screamingface._evaluation.model import Candidate, _compiled_candidate
from screamingface._evaluation.model_parameters import preflight_sync
from screamingface._evaluation.runner import _own_seed_calls
from screamingface._evaluation.topology import _operation_shape, _RecipeTopology
from screamingface.case_result import CaseOperation
from screamingface.discovery import ModelDetails
from screamingface.operation import OperationInfo
from screamingface.signal_sources import consistency_seed

_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]
# The F1 match of consistency-api CA-3 (a Pick has no extract: last_line@1 and text@1).
_F1_MATCH: dict[str, object] = {
    "extract": {"args": {}, "op": "last_line@1"},
    "normalize": {"args": {}, "op": "text@1"},
}
_SNAPSHOT = Path(__file__).resolve().parent / "public_surface_snapshot.json"
_DS_I3 = "sf.Fanout signals= needs a reducer: sf.Synthesize reads no signal"


def _pick() -> sf.ArgMax:
    return sf.ArgMax("cons")


# --- CA#2: the source holds n and the temperature (CA-1, CA-E1) --------------------------------


def test_consistency_holds_n_and_the_temperature() -> None:
    five = sf.Consistency(n=5)

    assert five.n == 5
    assert five.temperature == 1.0
    assert type(five.temperature) is float
    assert repr(five) == "Consistency(n=5, temperature=1.0)"
    assert five.source == "consistency"
    assert isinstance(five, sf.Consistency)
    assert five._spec() == {"source": "consistency", "n": 5, "temperature": 1.0}
    assert list(five._spec()) == ["source", "n", "temperature"]
    entry = five._entry(_F1_MATCH)
    assert entry == {"source": "consistency", "n": 5, "temperature": 1.0, "match": _F1_MATCH}
    assert list(entry) == ["source", "n", "temperature", "match"]
    assert entry["match"] is not _F1_MATCH  # a copy: the caller's mapping is not shared
    assert five._entry(MappingProxyType({"extract": None, "normalize": None}))["match"] == {
        "extract": None,
        "normalize": None,
    }
    assert "match" not in five._spec()  # _entry did not change the source
    zero = sf.Consistency(3, temperature=0)
    assert type(zero.temperature) is float
    assert json.dumps(zero._spec()) == '{"source": "consistency", "n": 3, "temperature": 0.0}'
    assert repr(sf.Consistency(1, temperature=-0.0)) == "Consistency(n=1, temperature=0.0)"
    assert repr(sf.Consistency(32, temperature=0.7)) == "Consistency(n=32, temperature=0.7)"
    assert sf.Consistency(5) == sf.Consistency(n=5, temperature=1)
    assert hash(sf.Consistency(5)) == hash(sf.Consistency(n=5, temperature=1.0))
    assert sf.Consistency(5) != sf.Consistency(5, temperature=0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        five.n = 6  # type: ignore[misc]


_N_TEXT = "sf.Consistency n must be an int from 1 to 32, not {!r}"
_T_TEXT = "sf.Consistency temperature must be a finite number of at least 0, not {!r}"
_HUGE = 10**400  # beyond the float range


@pytest.mark.parametrize(
    ("n", "temperature", "message"),
    [
        pytest.param(0, 1.0, _N_TEXT.format(0), id="n-0"),
        pytest.param(33, 1.0, _N_TEXT.format(33), id="n-33"),
        pytest.param(-1, 1.0, _N_TEXT.format(-1), id="n-negative"),
        pytest.param(True, 1.0, _N_TEXT.format(True), id="n-bool"),
        pytest.param(2.5, 1.0, _N_TEXT.format(2.5), id="n-float"),
        pytest.param(3.0, 1.0, _N_TEXT.format(3.0), id="n-integral-float"),
        pytest.param("3", 1.0, _N_TEXT.format("3"), id="n-text"),
        pytest.param(None, 1.0, _N_TEXT.format(None), id="n-none"),
        pytest.param(3, -0.1, _T_TEXT.format(-0.1), id="t-negative"),
        pytest.param(3, float("nan"), _T_TEXT.format(float("nan")), id="t-nan"),
        pytest.param(3, float("inf"), _T_TEXT.format(float("inf")), id="t-inf"),
        pytest.param(3, True, _T_TEXT.format(True), id="t-bool"),
        pytest.param(3, "1", _T_TEXT.format("1"), id="t-text"),
        pytest.param(3, None, _T_TEXT.format(None), id="t-none"),
        pytest.param(3, _HUGE, _T_TEXT.format(_HUGE), id="t-huge-int"),
        pytest.param(0, -1.0, _N_TEXT.format(0), id="n-checked-first"),
    ],
)
def test_consistency_refuses_bad_values(n: Any, temperature: Any, message: str) -> None:
    with pytest.raises(ValueError) as caught:
        sf.Consistency(n, temperature=temperature)
    assert str(caught.value) == message


def test_consistency_seed_gives_the_erd_seeds() -> None:
    # erd §2 hand-computed oracles: s(k, j) for k, j in 1..3.
    assert [consistency_seed(k, j) for k in (1, 2, 3) for j in (1, 2, 3)] == [
        2063835758,
        10968804,
        1079774124,
        966517312,
        107840383,
        1732381022,
        1073252422,
        137802004,
        992611152,
    ]
    seeds = {consistency_seed(k, j) for k in range(1, 257) for j in range(1, 33)}
    assert len(seeds) == 256 * 32  # all different (P5)
    assert min(seeds) == 134114  # never a default sf.samples() seed 0..255
    assert all(0 <= seed < 2**31 for seed in seeds)


# --- CA#3: a Fusion refuses a bad declaration before any call (CA-E2) ---------------------------

_NESTED = sf.Fanout(["prov/x", "prov/y"], name="inner") >> sf.Vote()
_CHAIN = sf.Pipeline(["prov/x", "prov/y"], name="chain")
_THIRTY_THREE = [f"prov/m{index}" for index in range(1, 34)]


@pytest.mark.parametrize(
    ("members", "signals", "synthesizer", "message"),
    [
        pytest.param(
            _MEMBERS,
            {"cons": sf.Consistency(n=2), "again": sf.Consistency(n=3)},
            _pick(),
            "a sf.Fanout declares at most one sf.Consistency source: every member gets one set "
            "of samples",
            id="two-consistency",
        ),
        pytest.param(
            ["prov/alpha", _NESTED, "prov/gamma"],
            {"cons": sf.Consistency(n=2)},
            _pick(),
            "sf.Consistency needs each sf.Fanout member to be one sf.Model call; member 2 "
            "('inner') is a nested block or Pipeline",
            id="member-2-fusion",
        ),
        pytest.param(
            [_CHAIN, "prov/beta"],
            {"cons": sf.Consistency(n=2)},
            _pick(),
            "sf.Consistency needs each sf.Fanout member to be one sf.Model call; member 1 "
            "('chain') is a nested block or Pipeline",
            id="member-1-pipeline",
        ),
        pytest.param(
            _THIRTY_THREE,
            {"cons": sf.Consistency(n=32)},
            _pick(),
            "sf.Consistency(n=32) on 33 members makes 1056 extra calls; the limit is 1024 per "
            "sf.Fanout",
            id="over-1024-calls",
        ),
        pytest.param(
            [sf.Model("prov/alpha", params={"seed": 2063835758}), "prov/beta", "prov/gamma"],
            {"cons": sf.Consistency(n=1)},
            _pick(),
            "member 1 ('alpha') sets seed=2063835758, which is the seed of consistency sample 1 "
            "of member 1; choose another seed",
            id="member-1-own-sample-seed",
        ),
        pytest.param(
            ["prov/alpha", sf.Model("prov/beta", params={"seed": 2063835758}), "prov/gamma"],
            {"cons": sf.Consistency(n=1)},
            _pick(),
            "member 2 ('beta') sets seed=2063835758, which is the seed of consistency sample 1 "
            "of member 1; choose another seed",
            id="member-2-other-member-seed",
        ),
        pytest.param(
            ["prov/alpha", "prov/beta", sf.Model("prov/gamma", params={"seed": "137802004"})],
            {"cons": sf.Consistency(n=3)},
            _pick(),
            "member 3 ('gamma') sets seed=137802004, which is the seed of consistency sample 2 "
            "of member 3; choose another seed",
            id="member-3-seed-as-text",
        ),
        pytest.param(
            _MEMBERS,
            {"cons": sf.Consistency(n=2)},
            sf.Synthesize("prov/judge"),
            _DS_I3,
            id="model-synthesizer",
        ),
    ],
)
def test_fusion_refuses_a_bad_consistency_declaration_before_any_call(
    members: list[Any], signals: dict[str, Any], synthesizer: Any, message: str
) -> None:
    with pytest.raises(ValueError) as caught:
        _ = sf.Fanout(members, signals=signals) >> synthesizer
    assert str(caught.value) == message


def test_fusion_accepts_a_consistency_declaration_at_the_limits() -> None:
    at_cap = (
        sf.Fanout(
            [f"prov/m{index}" for index in range(1, 33)], signals={"cons": sf.Consistency(n=32)}
        )
        >> _pick()
    )
    fanout = at_cap.steps[0]
    assert isinstance(fanout, sf.Fanout)
    assert fanout.signals == {"cons": sf.Consistency(n=32)}
    assert "signals={'cons': Consistency(n=32, temperature=1.0)}" in repr(at_cap)
    seeded = (
        sf.Fanout(
            [
                *sf.samples("prov/alpha", 3),  # seeds 0, 1, 2 are never sample seeds
                sf.Model("prov/beta", params={"seed": 107840383}),  # s(2, 2), but n=1
                sf.Model("prov/gamma", params={"seed": True}),  # a bool is never a seed
                sf.Model("prov/delta", params={"seed": 2063835758.0}),  # the url4 text differs
            ],
            signals={"cons": sf.Consistency(n=1), "conf": sf.Verbalized(r"Confidence: ([0-9]+)")},
        )
        >> _pick()
    )
    seeded_fanout = seeded.steps[0]
    assert isinstance(seeded_fanout, sf.Fanout)
    assert list(seeded_fanout.signals or {}) == ["conf", "cons"]


# --- CA#14: the public surface has sf.Consistency (PIN) ----------------------------------------


def test_public_surface_has_sf_consistency() -> None:
    assert "Consistency" in sf.__all__
    signature = str(inspect.signature(sf.Consistency.__init__))
    assert signature == "(self, n: 'int', *, temperature: 'float' = 1.0) -> 'None'"
    assert [field.name for field in dataclasses.fields(sf.Consistency)] == ["n", "temperature"]
    snapshot = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))["screamingface"]
    assert "Consistency" in snapshot["__all__"]
    assert snapshot["exports"]["Consistency"] == {
        "kind": "class",
        "members": {
            "__init__": f"method {signature}",
            "n": "field",
            "source": "attribute",
            "temperature": "field",
        },
    }


# ---- E4b part 7 unit 4 (consistency-api-compile): CA#1, CA#4, CA#5, CA#8–CA#13 ----

_CA_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]
# s(k, j) of erd §2, hand-computed: k is the member position, j the sample index.
_CA_SEEDS: dict[tuple[int, int], int] = {
    (1, 1): 2063835758,
    (1, 2): 10968804,
    (1, 3): 1079774124,
    (2, 1): 966517312,
    (2, 2): 107840383,
    (2, 3): 1732381022,
    (3, 1): 1073252422,
    (3, 2): 137802004,
    (3, 3): 992611152,
}
_CA_SLOT = re.compile(r"(?:member|sample)_\d+")
# CA#1: the fixed list L5 of test-plan §6 (never a glob), each with its existing builder.
_CA_L5: tuple[tuple[str, Callable[[], str]], ...] = (
    ("vote_candidate.url4", vote_candidate_url4),
    ("quorum_vote_candidate.url4", quorum_vote_url4),
    ("logprob_pick_mean_candidate.url4", logprob_pick_mean),
    ("gate_judge_vote_candidate.url4", gate_judge_vote_url4),
    ("samples_vote_candidate.url4", samples_vote_url4),
)
_CA_IN_LOOP = "sf.Consistency is not supported inside a corrective loop in this version"


def _ca_compiled(recipe: sf.Recipe) -> _CompiledCandidate:
    return compile_candidate(recipe, operators=engine_operators())


def _ca_root_names(url4_text: str) -> list[str | None]:
    expression = build(url4_text)
    assert isinstance(expression, Expression)
    return [source.name for source in expression.sources if isinstance(source, Source)]


def _ca_sources(url4_text: str) -> dict[str, Source]:
    """Every named source of a compiled url4, at any depth, by name. The slot names are left out:
    they repeat in each panel."""
    found: dict[str, Source] = {}
    for node in walk(build(url4_text)):
        if isinstance(node, Source) and node.name is not None and not _CA_SLOT.fullmatch(node.name):
            assert node.name not in found
            found[node.name] = node
    return found


def _ca_call(sources: dict[str, Source], binding: str) -> RelExpr:
    value = sources[binding].value
    assert isinstance(value, RelExpr)
    return value


def _ca_spec(sources: dict[str, Source]) -> dict[str, Any]:
    intent = _ca_call(sources, "synthesis_1").intent
    assert isinstance(intent, Text)
    spec: dict[str, Any] = json.loads(intent.value)
    return spec


def _ca_rider(url4_text: str) -> dict[str, Any]:
    value = _ca_sources(url4_text)["_sf_recipe"].value
    assert isinstance(value, Text)
    recipe: dict[str, Any] = json.loads(value.value)["recipe"]
    return recipe


def _ca_candidate(compiled: _CompiledCandidate) -> Candidate:
    return _compiled_candidate(
        name="consistency",
        kind=compiled.kind,
        models=compiled.models,
        url4=compiled.url4,
        operations=compiled.operations,
        members=compiled.members,
        parameter_assignments=compiled.parameter_assignments,
    )


def _ca_sample_node(binding: str, name: str) -> dict[str, Any]:
    return {"binding": binding, "kind": "model", "name": name, "named": False, "role": "sample"}


def _ca_assert_panel(sources: dict[str, Source], name: str, bindings: list[int]) -> None:
    """One member's sample panel (erd §3): broadcast, quorum 0, optional slots sample_1..n."""
    panel = sources[name]
    assert panel.weight == 0.0
    value = panel.value
    assert isinstance(value, Expression)
    assert (value.broadcast, value.params, value.intent) == (True, (("quorum", "0"),), Text(""))
    slots = [slot for slot in value.sources if isinstance(slot, Source)]
    assert [slot.name for slot in slots] == [f"sample_{j}" for j in range(1, len(bindings) + 1)]
    assert {(slot.weight, slot.annotations) for slot in slots} == {(1.0, (("optional", None),))}
    for slot, binding in zip(slots, bindings, strict=True):
        assert isinstance(slot.value, Expression)
        assert slot.value.intent == Text(f"$model_{binding}")
        inner = [node.name for node in slot.value.sources if isinstance(node, Source)]
        assert inner == [f"model_{binding}"]


@requires_engine_app
@pytest.mark.parametrize(("name", "builder"), _CA_L5, ids=[name for name, _ in _CA_L5])
def test_recipes_without_consistency_compile_to_the_same_url4(
    name: str, builder: Callable[[], str]
) -> None:
    """CA-D1 CHAR: a Fusion without sf.Consistency compiles to the same bytes as before."""
    assert read_contract(name) == builder()


def test_the_sample_calls_have_distinct_seeds_and_the_stated_temperature() -> None:
    """CA-2 (ans:Q3): n sample calls per member, distinct seeds, the stated temperature."""
    url4 = _ca_compiled(consistency_pick_recipe()).url4
    sources = _ca_sources(url4)
    assert _ca_root_names(url4) == [
        "model_1",
        "model_2",
        "model_3",
        "panel_1",
        "panel_2",
        "panel_3",
        "synthesis_1",
        "_sf_recipe",
    ]
    for position, route in enumerate(_CA_MEMBERS, 1):
        member = _ca_call(sources, f"model_{position}")
        assert (member.path, member.params) == (f"/{route}", ())
        _ca_assert_panel(sources, f"panel_{position}", [3 * position + j for j in (1, 2, 3)])
        for j in (1, 2, 3):
            binding = f"model_{3 * position + j}"
            sample = _ca_call(sources, binding)
            assert (sample.path, sample.context, sample.intent) == (
                member.path,
                "$input",
                member.intent,
            )
            seed = str(_CA_SEEDS[(position, j)])
            assert sample.params == (("binding", binding), ("temperature", "1.0"), ("seed", seed))
    assert "model_13" not in sources


def test_the_member_keeps_its_params_and_the_sample_takes_the_stated_temperature() -> None:
    """CA-7 (ans:Q3 "the member's other params unchanged")."""
    alpha = sf.Model("prov/alpha", params={"temperature": 0.2, "seed": 7, "max_tokens": 64})
    compiled = _ca_compiled(
        sf.Fanout(
            [alpha, "prov/beta", "prov/gamma"],
            signals={"cons": sf.Consistency(n=1, temperature=0.9)},
            name="pick",
        )
        >> sf.ArgMax("cons")
    )
    sources = _ca_sources(compiled.url4)
    assert _ca_call(sources, "model_1").params == (
        ("temperature", "0.2"),
        ("seed", "7"),
        ("max_tokens", "64"),
    )
    assert _ca_call(sources, "model_4").params == (
        ("binding", "model_4"),
        ("max_tokens", "64"),
        ("temperature", "0.9"),
        ("seed", "2063835758"),
    )
    assert [(a.operation_id, list(a.params.items())) for a in compiled.parameter_assignments] == [
        ("op_model_1", [("temperature", 0.2), ("seed", 7), ("max_tokens", 64)]),
        ("op_model_4", [("max_tokens", 64), ("temperature", 0.9), ("seed", 2063835758)]),
        ("op_model_5", [("temperature", 0.9), ("seed", 966517312)]),
        ("op_model_6", [("temperature", 0.9), ("seed", 1073252422)]),
    ]


def test_the_context_and_the_spec_carry_samples_and_the_match() -> None:
    """CA-3 (P3, P9): the context key `samples`; the entry holds the step's match operators."""
    pick = _ca_sources(_ca_compiled(consistency_pick_recipe()).url4)
    assert _ca_call(pick, "synthesis_1").context == (
        "{input: '$input', outputs: {member_1: '$model_1', member_2: '$model_2', "
        "member_3: '$model_3'}, samples: {member_1: '$panel_1', member_2: '$panel_2', "
        "member_3: '$panel_3'}}"
    )
    intent = _ca_call(pick, "synthesis_1").intent
    assert isinstance(intent, Text)
    assert (
        '"signals":{"cons":{"match":{"extract":{"args":{},"op":"last_line@1"},'
        '"normalize":{"args":{},"op":"text@1"}},"n":3,"source":"consistency",'
        '"temperature":1.0}}'
    ) in intent.value
    median = _ca_sources(_ca_compiled(consistency_median_recipe()).url4)
    assert _ca_call(median, "synthesis_1").context == (
        "{input: '$input', outputs: {member_1: '$model_1', member_2: '$model_2', "
        "member_3: '$model_3'}, samples: {member_1: '$panel_1', member_2: '$panel_2', "
        "member_3: '$panel_3'}}"
    )
    spec = _ca_spec(median)
    assert spec["signals"] == {
        "cons": {
            "match": {
                "extract": {"args": {}, "op": "last_number@1"},
                "normalize": {"args": {}, "op": "numeric@1"},
            },
            "n": 2,
            "source": "consistency",
            "temperature": 0.7,
        }
    }
    assert spec["signals"]["cons"]["match"] == {
        "extract": spec["extract"],
        "normalize": spec["normalize"],
    }
    assert _ca_call(median, "model_4").params == (
        ("binding", "model_4"),
        ("temperature", "0.7"),
        ("seed", "2063835758"),
    )
    assert "model_10" not in median


def test_the_operations_and_the_preflight_assignments_list_every_sample() -> None:
    """CA-4 (P7, P17): one `sample` operation and one assignment per sample call."""
    compiled = _ca_compiled(consistency_pick_recipe())
    names = ("alpha", "beta", "gamma")
    members = [
        OperationInfo(id=f"op_model_{k}", kind="model", label=f"{name} answer", depends_on=())
        for k, name in enumerate(names, 1)
    ]
    samples = [
        OperationInfo(id=f"op_model_{3 * k + j}", kind="sample", label=f"{name} sample")
        for k, name in enumerate(names, 1)
        for j in (1, 2, 3)
    ]
    combine = OperationInfo(
        id="op_synthesis_1",
        kind="combine",
        label="pick combine",
        depends_on=tuple(f"op_model_{index}" for index in range(1, 13)),
    )
    assert list(compiled.operations) == [*members, *samples, combine]
    # P7 WHY: S/_case_views.py takes depends_on[:len(members)] as the member producers.
    assert compiled.operations[-1].depends_on[:3] == ("op_model_1", "op_model_2", "op_model_3")
    assert [m.operation_id for m in compiled.members] == ["op_model_1", "op_model_2", "op_model_3"]
    assert [(a.operation_id, a.model, dict(a.params)) for a in compiled.parameter_assignments] == [
        (f"op_model_{3 * k + j}", route, {"temperature": 1.0, "seed": _CA_SEEDS[(k, j)]})
        for k, route in enumerate(_CA_MEMBERS, 1)
        for j in (1, 2, 3)
    ]
    assert compiled.models == tuple(_CA_MEMBERS)


def test_the_reducer_topology_lists_the_samples() -> None:
    """CA-5 (P8): the reducer node holds `samples`; other reducers keep their bytes."""
    rider = _ca_rider(_ca_compiled(consistency_pick_recipe()).url4)
    assert rider["synthesizer"] == {
        "binding": "synthesis_1",
        "kind": "reducer",
        "name": "pick",
        "samples": [
            {
                "member": f"member_{k}",
                "sources": [_ca_sample_node(f"model_{3 * k + j}", name) for j in (1, 2, 3)],
            }
            for k, name in enumerate(("alpha", "beta", "gamma"), 1)
        ],
    }
    assert [member["binding"] for member in rider["members"]] == ["model_1", "model_2", "model_3"]
    plain = _ca_rider(
        _ca_compiled(
            sf.Fanout(_CA_MEMBERS, signals={"conf": sf.Verbalized("C: ([0-9]+)")}, name="pick")
            >> sf.ArgMax("conf")
        ).url4
    )
    assert plain["synthesizer"] == {"binding": "synthesis_1", "kind": "reducer", "name": "pick"}
    node = _RecipeTopology(kind="model", name="alpha", binding="model_4", role="sample")
    assert _operation_shape(node) == ("sample", "sample")


def _ca_details(model: str, refused: str | None) -> dict[str, Any]:
    """The fixture contract of ``model`` with a supported ``seed`` row; ``refused`` marks one row
    of ``prov/alpha`` as not supported by the provider."""
    value: dict[str, Any] = model_details(model)
    parameters: dict[str, Any] = value["parameters"]
    seed = copy.deepcopy(parameters["max_tokens"])
    seed["request_path"] = "seed"
    seed["schema"] = {"type": "integer"}
    parameters["seed"] = seed
    if refused is not None and model == "prov/alpha":
        parameters[refused]["provider"]["support"] = "unsupported"
    return value


@pytest.mark.parametrize("refused", ["seed", "temperature"])
def test_the_preflight_refuses_a_model_without_seed_or_temperature_before_any_call(
    refused: str,
) -> None:
    """CA-E3 (P17): the sample params reach the free preflight, before any model call."""
    candidate = _ca_candidate(_ca_compiled(consistency_pick_recipe()))
    loaded: list[str] = []

    def load(refusing: str | None) -> Callable[[str], ModelDetails]:
        def details(model: str) -> ModelDetails:
            loaded.append(model)
            return _decode_model_details(_ca_details(model, refusing), model)

        return details

    with pytest.raises(sf.PlanningError) as caught:
        preflight_sync([candidate], load(refused))
    assert caught.value.code == "unsupported_model_parameter"
    assert str(caught.value).startswith(
        f"Parameter {refused!r} is not supported by the provider for Model 'prov/alpha'"
    )
    loaded.clear()
    preflight_sync([candidate], load(None))  # control: every row supported
    assert loaded == ["prov/alpha", "prov/beta", "prov/gamma"]


def test_sample_fingerprints_never_meet_member_fingerprints() -> None:
    """CA-D2 (SC-I1): the binding param keeps every sample apart from the members."""
    sources = _ca_sources(_ca_compiled(consistency_pick_recipe()).url4)

    def fingerprint(binding: str) -> tuple[str, tuple[tuple[str, str | None], ...]]:
        call = _ca_call(sources, binding)
        return call.path, tuple(sorted(call.params))

    members = {fingerprint(f"model_{index}") for index in (1, 2, 3)}
    samples = [fingerprint(f"model_{index}") for index in range(4, 13)]
    assert len(set(samples)) == 9
    assert members.isdisjoint(samples)


def test_the_logprob_params_stay_on_the_members() -> None:
    """CA-D8 (P5): the logprobs param of sf.Logprob is on the member calls only."""
    compiled = _ca_compiled(
        sf.Fanout(
            ["openrouter/acme/alpha", "openrouter/acme/beta"],
            signals={"cons": sf.Consistency(n=1), "lp": sf.Logprob("mean")},
            name="pick",
        )
        >> sf.ArgMax("cons")
    )
    sources = _ca_sources(compiled.url4)
    assert _ca_call(sources, "model_1").params == (("logprobs", "true"),)
    assert _ca_call(sources, "model_2").params == (("logprobs", "true"),)
    assert _ca_call(sources, "model_3").params == (
        ("binding", "model_3"),
        ("temperature", "1.0"),
        ("seed", "2063835758"),
    )
    assert _ca_call(sources, "model_4").params == (
        ("binding", "model_4"),
        ("temperature", "1.0"),
        ("seed", "966517312"),
    )
    assert [(a.operation_id, dict(a.params)) for a in compiled.parameter_assignments] == [
        ("op_model_1", {"logprobs": True}),
        ("op_model_2", {"logprobs": True}),
        ("op_model_3", {"temperature": 1.0, "seed": 2063835758}),
        ("op_model_4", {"temperature": 1.0, "seed": 966517312}),
    ]
    assert _ca_call(sources, "synthesis_1").context == (
        "{input: '$input', outputs: {member_1: '$model_1', member_2: '$model_2'}, "
        "samples: {member_1: '$panel_1', member_2: '$panel_2'}, "
        "sources: {member_1: {model_1: {path: '/openrouter/acme/alpha', params: 'logprobs=true'}}, "
        "member_2: {model_2: {path: '/openrouter/acme/beta', params: 'logprobs=true'}}}}"
    )


def test_samples_are_not_fixed_seed_calls() -> None:
    """CA-D3 (P18): the sample seeds are part of the method; the warning leaves them out."""
    compiled = _ca_compiled(consistency_pick_recipe())
    assert sum(operation.kind == "sample" for operation in compiled.operations) == 9
    assert all("seed" in a.params for a in compiled.parameter_assignments)
    assert _own_seed_calls(_ca_candidate(compiled)) == ()
    seeded = sf.Fanout(
        [sf.Model("prov/alpha", params={"seed": 7}), "prov/beta", "prov/gamma"],
        signals={"cons": sf.Consistency(n=1)},
        name="pick",
    ) >> sf.ArgMax("cons")
    assert _own_seed_calls(_ca_candidate(_ca_compiled(seeded))) == ("op_model_1 (alpha answer)",)


def test_sample_operations_are_generation_accounting_rows() -> None:
    """CA-D4 (P7): a sample call is a generation row with no member."""
    operations = [
        OperationInfo(id="op_model_1", kind="model", label="alpha answer"),
        OperationInfo(id="op_model_4", kind="sample", label="alpha sample"),
        OperationInfo(
            id="op_synthesis_1",
            kind="combine",
            label="pick combine",
            depends_on=("op_model_1", "op_model_4"),
        ),
    ]
    case = replace_fields(
        report_case(),
        operations=[
            CaseOperation("op_model_1", "B", "stop", fixture_accounting()),
            CaseOperation("op_model_4", "A", "stop", fixture_accounting()),
        ],
    )
    result = replace_fields(
        report_candidate("cons", 0.0),
        operations=operations,
        cases=[case],
        usage=sf.Usage(cost_usd="0.2"),
        run_cost_status=None,
    )
    view = result.accounting
    assert [(r.stage, r.operation_id, r.label, r.member_id) for r in view.rows] == [
        ("generation", "op_model_1", "alpha answer", None),
        ("generation", "op_model_4", "alpha sample", None),
    ]
    assert view.unattributed_cost_usd == Decimal("0")


def test_quorum_pipeline_and_samples_members_compile_samples() -> None:
    """CA-D5, CA-D6, CA-D7: the panel counter, the stage input, sf.samples() members."""
    quorum = _ca_compiled(
        sf.Fanout(_CA_MEMBERS, signals={"cons": sf.Consistency(n=1)}, quorum=2, name="vote")
        >> sf.Vote()
    )
    assert _ca_root_names(quorum.url4) == [
        "panel_1",
        "panel_2",
        "panel_3",
        "panel_4",
        "synthesis_1",
        "_sf_recipe",
    ]
    sources = _ca_sources(quorum.url4)
    assert _ca_call(sources, "synthesis_1").context == (
        "{input: '$input', panel: '$panel_1', samples: {member_1: '$panel_2', "
        "member_2: '$panel_3', member_3: '$panel_4'}}"
    )
    assert [dict(_ca_call(sources, f"model_{i}").params)["seed"] for i in (4, 5, 6)] == [
        "2063835758",
        "966517312",
        "1073252422",
    ]
    pipeline = _ca_compiled(sf.Pipeline([sf.Model("prov/delta"), consistency_pick_recipe()]))
    sources = _ca_sources(pipeline.url4)
    assert {_ca_call(sources, f"model_{i}").context for i in range(5, 14)} == {"$model_1"}
    assert _ca_call(sources, "model_5").params[2] == ("seed", "2063835758")
    samples = [operation for operation in pipeline.operations if operation.kind == "sample"]
    assert [operation.id for operation in samples] == [f"op_model_{i}" for i in range(5, 14)]
    assert {operation.depends_on for operation in samples} == {("op_model_1",)}
    assert pipeline.operations[-1].depends_on == tuple(f"op_model_{i}" for i in range(2, 14))
    assert _ca_call(sources, "synthesis_1").context == (
        "{input: '$model_1', outputs: {member_1: '$model_2', member_2: '$model_3', "
        "member_3: '$model_4'}, samples: {member_1: '$panel_1', member_2: '$panel_2', "
        "member_3: '$panel_3'}}"
    )
    sampled = _ca_compiled(
        sf.Fanout(sf.samples("prov/alpha", 3), signals={"cons": sf.Consistency(n=2)}, name="pick")
        >> sf.ArgMax("cons")
    )
    sources = _ca_sources(sampled.url4)
    assert [_ca_call(sources, f"model_{k}").params for k in (1, 2, 3)] == [
        (("seed", "0"),),
        (("seed", "1"),),
        (("seed", "2"),),
    ]
    assert [_ca_call(sources, f"model_{i}").params[1:] for i in range(4, 10)] == [
        (("temperature", "1.0"), ("seed", str(_CA_SEEDS[(k, j)])))
        for k in (1, 2, 3)
        for j in (1, 2)
    ]


@pytest.mark.parametrize("shape", ["fusion_member", "pipeline_member", "self_corrective"])
def test_a_corrective_loop_refuses_consistency(shape: str) -> None:
    """CA-E4 (P19): refused at compile, before the check-surface check."""
    fusion = consistency_pick_recipe()
    loop: sf.Recipe
    if shape == "fusion_member":
        loop = sf.CorrectiveLoop([fusion, "prov/member-d"], judge="prov/judge", max_rounds=2)
    elif shape == "pipeline_member":
        staged = sf.Pipeline([sf.Model("prov/delta"), fusion])
        loop = sf.CorrectiveLoop([staged, "prov/member-d"], judge="prov/judge", max_rounds=2)
    else:
        loop = sf.SelfCorrective(fusion)
    with pytest.raises(ValueError) as caught:
        compile_candidate(loop, operators=engine_operators())
    assert str(caught.value) == _CA_IN_LOOP
