"""Review fixes of E4b part 6 on the Engine side (review P6 #6; spec P13, erratum E12).

FEATURE: a spec whose ``weights`` reads a declared sum is refused when the sum adds a ``logprob``
source in the form ``mean`` or ``sum``, or an ``entropy`` source, as the ``sf.Fusion`` constructor
refuses it (P13, part 3 ans:Q11).
STORY: as an Engine operator, I get ``combine_spec_invalid`` for a hand-written spec whose vote
weight could never be greater than 0, before any member call is paid.
INVARIANT defended: the SDK and the Engine accept the same sum weights; the refusal names the rule
and never echoes a declared name.
"""

from __future__ import annotations

from typing import Any

import pytest
from combine_support import spec_text, vote_spec

from screamingface_engine.combine.ports import SpecInvalid
from screamingface_engine.combine.spec import parse_spec

_SURE = {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}


def _weighted_by_sum(part: dict[str, Any], weights: str = "risk") -> dict[str, Any]:
    return vote_spec(
        3,
        reduce={"op": "weighted_mode@1", "args": {}},
        select={"op": "max_weight_holder@1", "args": {}},
        weights={"signal": weights},
        signals={
            "risk": {"source": "sum", "coefficients": {"part": 0.5, "sure": 1.0}},
            "part": part,
            "sure": _SURE,
        },
    )


def test_engine_accepts_a_sum_vote_weight_with_no_raw_logprob_or_entropy() -> None:
    """P13: a sum of a ``logprob`` in the form ``prob`` and a verbalized number is a weight."""
    spec = parse_spec(spec_text(_weighted_by_sum({"source": "logprob", "form": "prob"})))
    assert spec.signals is not None and set(spec.signals) == {"risk", "part", "sure"}


@pytest.mark.parametrize(
    "part",
    [
        {"source": "logprob", "form": "mean"},
        {"source": "logprob", "form": "sum"},
        {"source": "entropy", "top_logprobs": 5},
    ],
)
def test_engine_accepts_such_a_sum_when_no_weight_reads_it(part: dict[str, Any]) -> None:
    """P13 limits only a vote weight: the same sum read by no weight stays valid."""
    spec = parse_spec(spec_text(_weighted_by_sum(part, weights="sure")))
    assert spec.signals is not None and "risk" in spec.signals


@pytest.mark.parametrize(
    "part",
    [
        {"source": "logprob", "form": "mean"},
        {"source": "logprob", "form": "sum"},
        {"source": "entropy", "top_logprobs": 5},
    ],
)
def test_engine_refuses_a_sum_vote_weight_that_adds_a_raw_logprob_or_entropy(
    part: dict[str, Any],
) -> None:
    """P13 (SA-E4): the sum adds a number that is at most 0 or that means LESS confidence, so it
    is not a vote weight; the Engine refuses it as the SDK does, with no declared name."""
    with pytest.raises(SpecInvalid) as caught:
        parse_spec(spec_text(_weighted_by_sum(part)))
    assert caught.value.code == "combine_spec_invalid"
    message = str(caught.value)
    assert "weights.signal must not be a sum that adds" in message
    assert all(name not in message for name in ("risk", "part", "sure"))
