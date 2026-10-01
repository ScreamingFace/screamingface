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
    engine_operators,
    read_contract,
    requires_engine_app,
)

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.reducer import Reducer

_MEMBERS = ["prov/member-a", "prov/member-b", "prov/member-c"]
_NUMBER_VOTE = sf.Vote(extract="last_number", normalize="numeric")

# name -> (reducer, member count)
_SPECS: dict[str, tuple[Reducer, int]] = {
    "vote_number_5": (_NUMBER_VOTE, 5),
    "vote_number_4": (_NUMBER_VOTE, 4),
    "vote_number_1": (_NUMBER_VOTE, 1),
    "vote_boxed_3": (sf.Vote(extract="boxed", normalize="numeric"), 3),
    "vote_default_3": (sf.Vote(), 3),
    "median_nearest_3": (sf.Median(extract="last_number", select="nearest"), 3),
    "median_nearest_1": (sf.Median(extract="last_number", select="nearest"), 1),
    "median_value_4": (sf.Median(extract="last_number", select="value"), 4),
    "median_line_value_3": (sf.Median(extract="last_line", select="value"), 3),
}


def vote_candidate_url4() -> str:
    recipe = sf.Fusion(_MEMBERS, synthesizer=_NUMBER_VOTE)
    return compile_candidate(recipe, operators=engine_operators()).url4


def model_synthesizer_candidate_url4() -> str:
    return compile_candidate(sf.Fusion(_MEMBERS, synthesizer="prov/synth")).url4


def reducer_specs() -> dict[str, str]:
    operators = engine_operators()
    return {
        name: combine_spec_text(reducer, member_count=count, operators=operators)
        for name, (reducer, count) in _SPECS.items()
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
    registered = {path.stem for path in ENGINE_GOLDEN_DIR.glob("*.json")}
    assert named <= registered
