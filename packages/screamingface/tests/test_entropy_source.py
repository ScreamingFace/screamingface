"""sf.Entropy: the declared token entropy source of a Fusion (E4b part 3, unit 4).

FEATURE: ``sf.Fusion(members, signals={"ent": sf.Entropy()}, ...)`` asks every member call for
``logprobs`` and ``top_logprobs=k`` and lets Pick or Rank with ``order="min"`` read the entropy.
STORY: as a researcher, I keep the member answer whose tokens were the least uncertain.
INVARIANT defended: k is an int from 1 to 20, default 5 (Q8); entropy is never a vote weight (P9);
members must be OpenRouter sf.Model calls (Q2, P3); the rebuild drops the injected params (P16).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

import pytest
from _combine_contract import engine_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._signals import Signal
from screamingface._surface.chain import Step

_ALPHA = "openrouter/acme/alpha"
_BETA = "openrouter/acme/beta"
_GAMMA = "openrouter/acme/gamma"
_MEMBERS = [_ALPHA, _BETA, _GAMMA]
_WEIGHTED: list[Any] = [
    pytest.param(lambda s: sf.Vote(weights=s), id="vote"),
    pytest.param(lambda s: sf.Median(weights=s), id="median"),
    pytest.param(lambda s: sf.Mean(weights=s), id="mean"),
]


def _pick(name: str, order: Literal["max", "min"] = "max") -> sf.ArgMax | sf.ArgMin:
    return sf.ArgMin(name) if order == "min" else sf.ArgMax(name)


def _compiled(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4


def _recovered(url4: str) -> sf.Recipe:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    candidate = namespace["candidate"]
    assert isinstance(candidate, sf.Recipe)
    return candidate


# --- EN#7: entropy is refused as a vote weight -------------------------------------------------


@pytest.mark.parametrize("reducer", _WEIGHTED)
def test_vote_weight_refuses_entropy_with_an_order_min_hint(
    reducer: Callable[[Signal], Step],
) -> None:
    with pytest.raises(ValueError, match="order='min'"):
        _ = sf.Fanout(_MEMBERS, signals={"ent": sf.Entropy()}) >> reducer(sf.signal("ent"))
    # Control: ArgMin builds.
    fusion = sf.Fanout(_MEMBERS, signals={"ent": sf.Entropy()}) >> _pick("ent", "min")
    assert isinstance(fusion, sf.Pipeline)


# --- EN#8: top_logprobs=k on each member call; OpenRouter sf.Model members only ---------------


def test_entropy_compiles_top_logprobs_on_each_member_call() -> None:
    compiled = compile_candidate(
        sf.Fanout(_MEMBERS, signals={"ent": sf.Entropy()}) >> _pick("ent", "min"),
        operators=engine_operators(),
    )
    url4 = compiled.url4

    for name in ("alpha", "beta", "gamma"):
        assert f"/openrouter/acme/{name}?logprobs=true&top_logprobs=5&q=(" in url4
    assert url4.count("params: 'logprobs=true&top_logprobs=5'") == 3
    assert [(a.operation_id, a.model, dict(a.params)) for a in compiled.parameter_assignments] == [
        ("op_model_1", _ALPHA, {"logprobs": True, "top_logprobs": 5}),
        ("op_model_2", _BETA, {"logprobs": True, "top_logprobs": 5}),
        ("op_model_3", _GAMMA, {"logprobs": True, "top_logprobs": 5}),
    ]
    assert '"signals":{"ent":{"source":"entropy","top_logprobs":5}}' in url4
    three = _compiled(
        sf.Fanout(_MEMBERS, signals={"ent": sf.Entropy(top_logprobs=3)}) >> _pick("ent", "min")
    )
    assert "top_logprobs=3&q=(" in three


def test_entropy_refuses_non_openrouter_and_recipe_members() -> None:
    with pytest.raises(ValueError, match=re.escape("sf.Entropy supports OpenRouter models in v1")):
        _ = sf.Fanout([_ALPHA, "prov/beta"], signals={"ent": sf.Entropy()}) >> _pick("ent", "min")
    nested: list[sf.Recipe] = [
        sf.Fanout([_ALPHA, _BETA]) >> sf.Vote(),
        sf.Pipeline([_ALPHA, _BETA]),
    ]
    for member in nested:
        with pytest.raises(ValueError, match="one sf.Model call"):
            _ = sf.Fanout([member, _GAMMA], signals={"ent": sf.Entropy()}) >> _pick("ent", "min")


# --- EN#6: k is an int from 1 to 20, default 5 ------------------------------------------------


def test_entropy_refuses_bad_k() -> None:
    for bad in (0, 21, -1, True, False, 5.0, "5", None):
        with pytest.raises(ValueError, match="top_logprobs must be an int from 1 to 20"):
            sf.Entropy(top_logprobs=bad)  # type: ignore[arg-type]
    assert sf.Entropy().top_logprobs == 5
    assert sf.Entropy(top_logprobs=1).top_logprobs == 1
    assert sf.Entropy(top_logprobs=20).top_logprobs == 20
    assert repr(sf.Entropy()) == "Entropy(top_logprobs=5)"


# --- EN#13: the url4 rebuild keeps sf.Entropy(top_logprobs=k) and drops the injected params ----


@pytest.mark.parametrize("quorum", ["all", 1])
def test_entropy_fusion_rebuilds_from_url4_without_injected_params(
    quorum: int | Literal["all"],
) -> None:
    fusion = sf.Fanout(
        [_ALPHA, _BETA], signals={"ent": sf.Entropy(top_logprobs=3)}, quorum=quorum
    ) >> _pick("ent", "min")
    url4 = _compiled(fusion)
    code = sf.Url4(url4).to_python()

    assert "sf.Entropy(top_logprobs=3)" in code
    assert code.count("top_logprobs") == 1
    assert "params=" not in code
    recovered = _recovered(url4)
    assert recovered == fusion
    assert repr(recovered) == repr(fusion)
    assert _compiled(recovered) == url4


# --- support (DS#7 with the real class; no PRD row): one sf.Entropy per Fusion (Q8) ------------


def test_fusion_refuses_two_entropy_sources() -> None:
    with pytest.raises(ValueError, match="at most one sf.Entropy"):
        _ = sf.Fanout(
            _MEMBERS, signals={"ea": sf.Entropy(), "eb": sf.Entropy(top_logprobs=3)}
        ) >> _pick("ea", "min")
