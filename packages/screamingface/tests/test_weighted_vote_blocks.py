"""sf.Vote(weights=...) is the named form of sf.Reduce("weighted", ...) (OME-1289, BK#4).

FEATURE: a weighted vote and its block form compile to the same combine call.
INVARIANT: both build their plan through one ``_vote_plan``, so the url4 bytes are equal by
construction; these are guards, and they pass at once.
"""

from __future__ import annotations

from typing import Any

import pytest
from _combine_contract import GSM8K_RULE_WIRE, rule
from _reducer_fixtures import engine_operators

import screamingface as sf
from screamingface._evaluation.answer_rule import _BenchmarkAnswerRule
from screamingface._evaluation.candidate import compile_candidate
from screamingface.reducer import Reducer

_MEMBERS = ["provider/a", "provider/b", "provider/c"]
_RULES = ("boxed", "last_number", "last_line", "whole", "inspect_number", "inspect_aime")
_NORMALIZERS = (None, "numeric", "text", "set", "inspect_numeric", "identity")
# WHY cost_usd is here: after the sources commit it also covers the context `sources`.
_WEIGHTS: list[Any] = [[1, 2.5, 3], sf.signal("field:confidence"), sf.signal("cost_usd")]


def _url4(synthesizer: Reducer, benchmark_rule: _BenchmarkAnswerRule | None = None) -> str:
    recipe = sf.Fusion(_MEMBERS, synthesizer=synthesizer)
    return compile_candidate(
        recipe, operators=engine_operators(), benchmark_rule=benchmark_rule
    ).url4


@pytest.mark.parametrize("weights", _WEIGHTS, ids=repr)
@pytest.mark.parametrize("normalize", _NORMALIZERS)
@pytest.mark.parametrize("extract", _RULES)
def test_every_op_table_row_matches_its_named_form(
    extract: str, normalize: str | None, weights: Any
) -> None:
    vote = sf.Vote(extract=extract, normalize=normalize, weights=weights)
    block = sf.Reduce(
        "weighted",
        extract=sf.Extract(extract, normalize=normalize),  # type: ignore[arg-type]
        weights=weights,
    )

    assert _url4(vote) == _url4(block)


def test_the_benchmark_row_matches_its_named_form() -> None:
    bound = _BenchmarkAnswerRule("inspect-gsm8k", rule(GSM8K_RULE_WIRE))
    vote = sf.Vote(extract="benchmark", weights=[1, 2, 3])
    block = sf.Reduce("weighted", extract=sf.Extract("benchmark"), weights=[1, 2, 3])

    assert _url4(vote, bound) == _url4(block, bound)
