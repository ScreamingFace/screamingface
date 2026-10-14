"""sf.Vote and sf.Median are the named forms of sf.Reduce rows (OME-1289 gap, BK#1-4).

FEATURE: a named reducer and its block form compile to the same combine call.
INVARIANT: both build a ``_ReducerPlan`` (the seam), so their url4 bytes are equal by construction.
"""

from __future__ import annotations

from typing import Any

import pytest
from _combine_contract import AIME24_RULE_WIRE, GSM8K_RULE_WIRE, rule
from _reducer_fixtures import engine_operators

import screamingface as sf
from screamingface._evaluation.answer_rule import _BenchmarkAnswerRule
from screamingface._evaluation.candidate import compile_candidate
from screamingface.reducer import Reducer

_MEMBERS = ["provider/a", "provider/b", "provider/c"]


def _url4(synthesizer: Reducer, benchmark_rule: _BenchmarkAnswerRule | None = None) -> str:
    recipe = sf.Fusion(_MEMBERS, synthesizer=synthesizer)
    return compile_candidate(
        recipe, operators=engine_operators(), benchmark_rule=benchmark_rule
    ).url4


# WHY cost_usd is here: after the sources commit it also covers the context `sources`.
_ROWS = [
    pytest.param(
        sf.Vote(extract="last_number", normalize="numeric"),
        sf.Reduce("plurality", extract=sf.Extract("last_number", normalize="numeric")),
        id="plurality-last_number-numeric",
    ),
    pytest.param(
        sf.Vote(extract="last_line", normalize=None),
        sf.Reduce("plurality", extract=sf.Extract("last_line", normalize=None)),
        id="plurality-last_line-None",
    ),
    pytest.param(
        sf.Median(extract="last_number", select="nearest"),
        sf.Reduce("median", extract=sf.Extract("last_number")),
        id="median-last_number-nearest",
    ),
    pytest.param(
        sf.Median(extract="last_number", select="value"),
        sf.Reduce("median", mode="compute", extract=sf.Extract("last_number")),
        id="median-last_number-value-compute",
    ),
    *[
        pytest.param(
            sf.Vote(extract="last_number", normalize="numeric", weights=weights),
            sf.Reduce(
                "weighted",
                extract=sf.Extract("last_number", normalize="numeric"),
                weights=weights,
            ),
            id=f"weighted-last_number-numeric-{label}",
        )
        for label, weights in (
            ("list", [1, 2.5, 3]),
            ("field:confidence", sf.signal("field:confidence")),
            ("cost_usd", sf.signal("cost_usd")),
        )
    ],
]


@pytest.mark.parametrize(("named", "block"), _ROWS)
def test_every_op_table_row_matches_its_named_form(named: Reducer, block: Reducer) -> None:
    assert _url4(named) == _url4(block)


@pytest.mark.parametrize(
    ("benchmark_id", "wire"),
    [("inspect-gsm8k", GSM8K_RULE_WIRE), ("inspect-aime24", AIME24_RULE_WIRE)],
)
def test_benchmark_rows_match_their_named_form(benchmark_id: str, wire: dict[str, Any]) -> None:
    # BK#4, benchmark rows: both forms read the benchmark's own rule.
    bound = _BenchmarkAnswerRule(benchmark_id, rule(wire))
    vote = sf.Vote(extract="benchmark")
    block = sf.Reduce("plurality", extract=sf.Extract("benchmark"))

    assert _url4(vote, bound) == _url4(block, bound)


def test_the_benchmark_row_matches_its_named_form() -> None:
    bound = _BenchmarkAnswerRule("inspect-gsm8k", rule(GSM8K_RULE_WIRE))
    vote = sf.Vote(extract="benchmark", weights=[1, 2, 3])
    block = sf.Reduce("weighted", extract=sf.Extract("benchmark"), weights=[1, 2, 3])

    assert _url4(vote, bound) == _url4(block, bound)
