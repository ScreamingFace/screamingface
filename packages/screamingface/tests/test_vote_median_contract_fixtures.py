"""Drift guard for the engine-side Vote/Median contract data (OME-1289, unit 5).

The Engine's tests read ``vote_candidate.url4``, ``model_synthesizer_candidate.url4`` and
``reducer_specs.json`` from ``apps/screamingface-engine/tests/unit/data/combine_contract/`` and run
them verbatim (they never build a spec by hand, so "the SDK spec runs on the Engine" is proven by
these bytes). This test keeps the files equal to what the SDK compiles today.

Regenerate, from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_vote_median_contract_fixtures as m; m.write_fixtures()"
"""

from __future__ import annotations

import json

from _combine_contract import (
    COMBINE_CONTRACT,
    ENGINE_GOLDEN_DIR,
    ENGINE_OPERATOR_NAMES,
    GSM8K_RULE_WIRE,
    engine_operators,
    read_contract,
    requires_engine_app,
    rule,
)
from _nodes import FusionNode

import screamingface as sf
from screamingface._evaluation.answer_rule import _BenchmarkAnswerRule
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface._surface.chain import Step
from screamingface._surface.lowering import lower
from screamingface.reducer import Reducer

_MEMBERS = ["prov/member-a", "prov/member-b", "prov/member-c"]
_NUMBER_VOTE = sf.Vote(over="last_number", normalize="numeric")

# name -> (reducer, member count, the benchmark rule an over="benchmark" reducer reads)
_SPECS: dict[str, tuple[Step, int, _BenchmarkAnswerRule | None]] = {
    "vote_number_5": (_NUMBER_VOTE, 5, None),
    "vote_number_4": (_NUMBER_VOTE, 4, None),
    "vote_number_1": (_NUMBER_VOTE, 1, None),
    "vote_boxed_3": (sf.Vote(over="boxed", normalize="numeric"), 3, None),
    "vote_default_3": (sf.Vote(), 3, None),
    "vote_benchmark_gsm8k_3": (
        sf.Vote(over="benchmark"),
        3,
        _BenchmarkAnswerRule("inspect-gsm8k", rule(GSM8K_RULE_WIRE)),
    ),
    "median_nearest_3": (sf.Median(over="last_number", select="nearest"), 3, None),
    "median_nearest_1": (sf.Median(over="last_number", select="nearest"), 1, None),
    "median_value_4": (sf.Median(over="last_number", select="value"), 4, None),
    "median_line_value_3": (sf.Median(over="last_line", select="value"), 3, None),
}


def vote_candidate_url4() -> str:
    recipe = sf.Fanout(_MEMBERS) >> _NUMBER_VOTE
    return compile_candidate(recipe, operators=engine_operators()).url4


def model_synthesizer_candidate_url4() -> str:
    return compile_candidate(sf.Fanout(_MEMBERS) >> sf.Synthesize("prov/synth")).url4


def _reducer(step: Step) -> Reducer:
    """The internal reducer that ``step`` lowers to: the spec writer reads that node."""

    lowered = lower(sf.Fanout(_MEMBERS) >> step)
    assert isinstance(lowered, FusionNode)
    reducer = lowered.synthesizer
    assert isinstance(reducer, Reducer)
    return reducer


def reducer_specs() -> dict[str, str]:
    operators = engine_operators()
    return {
        name: combine_spec_text(
            _reducer(step), member_count=count, operators=operators, benchmark_rule=benchmark_rule
        )
        for name, (step, count, benchmark_rule) in _SPECS.items()
    }


def write_fixtures() -> None:
    (COMBINE_CONTRACT / "vote_candidate.url4").write_text(vote_candidate_url4(), encoding="utf-8")
    (COMBINE_CONTRACT / "model_synthesizer_candidate.url4").write_text(
        model_synthesizer_candidate_url4(), encoding="utf-8"
    )
    (COMBINE_CONTRACT / "reducer_specs.json").write_text(
        json.dumps(reducer_specs(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@requires_engine_app
def test_engine_vote_median_fixtures_match_the_sdk_compiler() -> None:
    # WHY the files must exist: a present engine app with a missing fixture FAILS, not skips.
    for name in ("vote_candidate.url4", "model_synthesizer_candidate.url4", "reducer_specs.json"):
        assert (COMBINE_CONTRACT / name).exists(), f"combine_contract/{name} is missing"
    assert read_contract("vote_candidate.url4") == vote_candidate_url4()
    assert read_contract("model_synthesizer_candidate.url4") == model_synthesizer_candidate_url4()
    assert json.loads(read_contract("reducer_specs.json")) == reducer_specs()


@requires_engine_app
def test_engine_operator_names_are_registered_in_the_engine() -> None:
    # WHY a subset: units 8-10 add operators to the Engine without touching this helper.
    named = {f"{name}@1" for names in ENGINE_OPERATOR_NAMES.values() for name in names}
    # WHY rglob: the signal and filter operators' goldens live in fixtures/combine/flow (10E)
    registered = {path.stem for path in ENGINE_GOLDEN_DIR.rglob("*.json")}
    assert named <= registered
