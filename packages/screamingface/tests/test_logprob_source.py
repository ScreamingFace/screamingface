"""sf.Logprob: the declared token log-probability source of a Fusion (E4b part 3, unit 4).

FEATURE: ``sf.Fusion(members, signals={"lp": sf.Logprob("mean")}, ...)`` asks every member call
for ``logprobs`` and lets Pick, Rank, Filter and a ``"prob"`` vote weight read the value.
STORY: as a researcher, I keep the member answer the model was surest of, with no extra call.
INVARIANT defended: a vote weight must be > 0, so ``"mean"`` and ``"sum"`` are refused as a weight
at construction (Q11, P14); members must be OpenRouter sf.Model calls (Q2, P3); the injected params
reach the preflight (P12) and leave the url4 rebuild (P16).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any, Literal, NoReturn

import httpx
import pytest
from _combine_contract import engine_operators
from _combine_flow_fixtures import flow_operators_response
from _model_parameter_fixtures import DETAILS as _DETAILS
from _model_parameter_fixtures import SUMMARY as _SUMMARY
from url4 import RelExpr, expr, render, src, text

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._signals import Signal
from screamingface.reducer import Reducer
from screamingface.signal_sources import declared_from_spec

_ALPHA = "openrouter/acme/alpha"
_BETA = "openrouter/acme/beta"
_GAMMA = "openrouter/acme/gamma"
_MEMBERS = [_ALPHA, _BETA, _GAMMA]
_WRITER = "openrouter/acme/writer"
_WEIGHTED: list[Any] = [
    pytest.param(lambda s: sf.Vote(weights=s), id="vote"),
    pytest.param(lambda s: sf.Median(weights=s), id="median"),
    pytest.param(lambda s: sf.Mean(weights=s), id="mean"),
]


def _pick(name: str, order: Literal["max", "min"] = "max") -> sf.Pick:
    return sf.Pick(by_signal=sf.signal(name), order=order)


def _compiled(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4


def _recovered(url4: str) -> sf.Recipe:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    candidate = namespace["candidate"]
    assert isinstance(candidate, sf.Recipe)
    return candidate


# --- preflight fakes (copied from test_samples_preflight.py, as its docstring asks) -------------

_BENCHMARK_URL4 = render(
    expr(
        src(
            RelExpr(path="/candidate", context="question", intent=text("$candidate")),
            name="answer",
            weight=0.0,
        ),
        intent=text("$answer"),
    )
)
_BENCHMARK = {
    "schema": "screamingface.benchmark.v1",
    "id": "fixture",
    "title": "Fixture",
    "description": "Fixture Benchmark.",
    "revision": "fixture-revision",
    "case_count": 1,
    "url4": _BENCHMARK_URL4,
}


def _summary(model: str) -> dict[str, object]:
    return {
        **_SUMMARY,
        "id": model,
        "owned_by": model.split("/", 1)[0],
        "parameter_contract_url": f"/v1/model-parameters?model={model}",
    }


def _logprobs_row(support: str) -> dict[str, object]:
    return {
        "request_path": "logprobs",
        "schema": {"type": "boolean"},
        "provider": {
            "support": support,
            "source": "openrouter:models",
            "stale": False,
            "deprecated": False,
        },
        "gateway": {
            "status": "enabled",
            "projection": "direct",
            "cache_behavior": "keyed",
            "applicable_auth_modes": ["api_key"],
        },
    }


def _details(model: str, support: str | None) -> dict[str, object]:
    value: dict[str, Any] = copy.deepcopy(_DETAILS)
    provider, upstream = model.split("/", 1)
    value["model"] = {"id": model, "gateway_provider": provider, "upstream_id": upstream}
    if support is not None:
        value["parameters"]["logprobs"] = _logprobs_row(support)
    return value


def _engine(support: str | None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(404)
        if request.url.path == "/v1/benchmarks/fixture":
            response = httpx.Response(200, json=_BENCHMARK)
        elif request.url.path == "/v1/operators":
            response = flow_operators_response()
        elif request.url.path == "/v1/models":
            response = httpx.Response(200, json={"object": "list", "data": [_summary(_ALPHA)]})
        elif request.url.path == "/v1/model-parameters":
            response = httpx.Response(200, json=_details(_ALPHA, support))
        return response

    return httpx.MockTransport(handler)


class _ForbiddenTransport:
    called = False

    def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("the logprobs preflight must refuse before any spend")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


# --- LP#4: mean and sum are refused as a vote weight; prob is accepted -----------------------


@pytest.mark.parametrize("form", ["mean", "sum"])
@pytest.mark.parametrize("reducer", _WEIGHTED)
def test_vote_weight_refuses_logprob_mean_and_sum_with_a_prob_hint(
    form: Literal["mean", "sum"], reducer: Callable[[Signal], Reducer]
) -> None:
    with pytest.raises(ValueError, match=r"sf\.Logprob\('prob'\)"):
        sf.Fusion(_MEMBERS, signals={"lp": sf.Logprob(form)}, synthesizer=reducer(sf.signal("lp")))


@pytest.mark.parametrize("reducer", _WEIGHTED)
def test_vote_weight_accepts_logprob_prob(reducer: Callable[[Signal], Reducer]) -> None:
    fusion = sf.Fusion(
        _MEMBERS, signals={"p": sf.Logprob("prob")}, synthesizer=reducer(sf.signal("p"))
    )

    assert isinstance(fusion, sf.Fusion)


# --- LP#5: OpenRouter sf.Model members only ----------------------------------------------------


def test_logprob_refuses_non_openrouter_and_recipe_members() -> None:
    with pytest.raises(ValueError, match=re.escape("sf.Logprob supports OpenRouter models in v1")):
        sf.Fusion(
            [_ALPHA, "prov/beta"], signals={"lp": sf.Logprob("mean")}, synthesizer=_pick("lp")
        )
    nested: list[sf.Recipe] = [
        sf.Fusion([_ALPHA, _BETA], synthesizer=sf.Vote()),
        sf.Pipeline([_ALPHA, _BETA]),
    ]
    for member in nested:
        with pytest.raises(ValueError, match="one sf.Model call"):
            sf.Fusion([member, _GAMMA], signals={"lp": sf.Logprob("mean")}, synthesizer=_pick("lp"))
    with pytest.raises(ValueError, match="remove it from member 1"):
        sf.Fusion(
            [sf.Model(_ALPHA, params={"logprobs": False}), _BETA],
            signals={"lp": sf.Logprob("mean")},
            synthesizer=_pick("lp"),
        )
    # Control: without a declaration there is no member check.
    assert isinstance(sf.Fusion([_ALPHA, "prov/beta"], synthesizer=sf.Vote()), sf.Fusion)


# --- LP#6: logprobs=true on each member call, and the preflight sees it ------------------------


def test_logprob_compiles_logprobs_true_on_each_member_call() -> None:
    compiled = compile_candidate(
        sf.Fusion(_MEMBERS, signals={"lp": sf.Logprob("mean")}, synthesizer=_pick("lp")),
        operators=engine_operators(),
    )
    url4 = compiled.url4

    for name in ("alpha", "beta", "gamma"):
        assert f"/openrouter/acme/{name}?logprobs=true&q=(" in url4
    assert "top_logprobs" not in url4
    assert url4.count("params: 'logprobs=true'") == 3
    assert [(a.operation_id, a.model, dict(a.params)) for a in compiled.parameter_assignments] == [
        ("op_model_1", _ALPHA, {"logprobs": True}),
        ("op_model_2", _BETA, {"logprobs": True}),
        ("op_model_3", _GAMMA, {"logprobs": True}),
    ]
    # Control (DS-2): no declaration, no injected param, no sources.
    plain = compile_candidate(
        sf.Fusion(_MEMBERS, synthesizer=sf.Vote()), operators=engine_operators()
    )
    assert "logprobs" not in plain.url4
    assert "sources:" not in plain.url4
    assert plain.parameter_assignments == ()


@pytest.mark.parametrize(
    ("support", "expected"),
    [("unsupported", "is not supported by the provider"), (None, "is not available")],
)
def test_logprob_preflight_refuses_a_model_the_catalog_marks_without_logprobs(
    support: str | None, expected: str
) -> None:
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine(support),
        run_transport=transport,
    )
    candidate = sf.Fusion([_ALPHA], signals={"lp": sf.Logprob("mean")}, synthesizer=_pick("lp"))

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(candidate, benchmark="fixture")

    assert caught.value.code == "unsupported_model_parameter"
    assert "'logprobs'" in str(caught.value)
    assert expected in str(caught.value)
    assert transport.called is False


# --- LP#13 (SDK half): Pick and Filter take sum and prob ---------------------------------------


def test_pick_and_filter_accept_sum_and_prob() -> None:
    url4_sum = _compiled(
        sf.Fusion([_ALPHA, _BETA], signals={"lp": sf.Logprob("sum")}, synthesizer=_pick("lp"))
    )
    url4_prob = _compiled(
        sf.Pipeline(
            [
                sf.Fusion(
                    _MEMBERS,
                    signals={"p": sf.Logprob("prob")},
                    synthesizer=sf.Filter(where=sf.signal("p") >= 0.8),
                ),
                _WRITER,
            ]
        )
    )

    assert '"signals":{"lp":{"form":"sum","source":"logprob"}}' in url4_sum
    assert '"signals":{"p":{"form":"prob","source":"logprob"}}' in url4_prob


# --- LP#14: the url4 rebuild keeps sf.Logprob and drops the injected params --------------------


@pytest.mark.parametrize("quorum", ["all", 1])
def test_logprob_fusion_rebuilds_from_url4_without_injected_params(
    quorum: int | Literal["all"],
) -> None:
    fusion = sf.Fusion(
        [sf.Model(_ALPHA, params={"temperature": 0.5}), _BETA],
        signals={"lp": sf.Logprob("mean")},
        synthesizer=_pick("lp"),
        quorum=quorum,
    )
    url4 = _compiled(fusion)
    code = sf.Url4(url4).to_python()

    assert "sf.Logprob('mean')" in code
    assert "logprobs" not in code  # case-sensitive: sf.Logprob has a capital L
    assert "params={'temperature': 0.5}" in code
    recovered = _recovered(url4)
    assert repr(recovered) == repr(fusion)
    assert _compiled(recovered) == url4


# --- support (no PRD row): the form is closed ------------------------------------------------


def test_logprob_refuses_an_unknown_form() -> None:
    for bad in ("median", "", "MEAN", 1, None):
        with pytest.raises(ValueError, match="form must be 'mean', 'sum' or 'prob'"):
            sf.Logprob(bad)  # type: ignore[arg-type]
    assert repr(sf.Logprob("sum")) == "Logprob('sum')"
    assert sf.Logprob("prob") == sf.Logprob("prob")


# --- support (no PRD row): the wire entry round trip and its refusals --------------------------


def test_declared_from_spec_rebuilds_and_refuses_logprob_and_entropy_entries() -> None:
    entries = {"ent": sf.Entropy(top_logprobs=3)._spec(), "lp": sf.Logprob("sum")._spec()}
    assert declared_from_spec(entries) == {
        "ent": sf.Entropy(top_logprobs=3),
        "lp": sf.Logprob("sum"),
    }
    bad_entries: list[dict[str, object]] = [
        {"source": "logprob"},
        {"source": "logprob", "form": "median"},
        {"source": "logprob", "form": 1},
        {"source": "logprob", "form": "mean", "top_logprobs": 5},
        {"source": "entropy"},
        {"source": "entropy", "top_logprobs": True},
        {"source": "entropy", "top_logprobs": 0},
        {"source": "entropy", "top_logprobs": "5"},
        {"source": "entropy", "top_logprobs": 5, "form": "mean"},
    ]
    for entry in bad_entries:
        with pytest.raises(ValueError, match="cannot rebuild"):
            declared_from_spec({"x": entry})
