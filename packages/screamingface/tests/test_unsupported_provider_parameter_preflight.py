"""Refuse before spend when a Model's PROVIDER cannot accept a parameter the run asked for.

The gateway states the distinction this module defends
(``aigateway/core/chat_parameters/_types.py``): ``gateway_status`` carries POLICY,
``provider_support`` carries EVIDENCE, and the two are not the same claim. A parameter can be
``gateway_status: "enabled"`` — the gateway will happily forward it — while the provider's own
catalogue says that model does not accept it. OpenRouter is exactly that shape: its plugin rules
``seed`` as a blanket passthrough for every model it serves, so policy is ``enabled`` even for a
model whose ``provider_support`` is ``unsupported``.

INVARIANT: only an explicit provider denial refuses. ``supported`` obviously passes;
``unknown`` means no discovery source spoke, so refusing would refuse on our own ignorance and
block models that work; ``conditional`` means the provider does accept it under some condition a
catalogue row cannot express, so refusing would be a false negative. Written as a separate module
rather than appended to ``test_model_parameter_preflight.py`` because the append-only gate
protects prior test artifacts.
"""

from __future__ import annotations

import copy
from typing import Any, NoReturn

import httpx
import pytest
from _model_parameter_fixtures import DETAILS as _DETAILS
from _model_parameter_fixtures import SUMMARY as _SUMMARY
from url4 import RelExpr, expr, render, src, text

import screamingface as sf
from screamingface import _default_client

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

_MEMBER = "provider/opus"
_SYNTH = "provider/synth"


def _summary(model: str) -> dict[str, object]:
    provider = model.split("/", 1)[0]
    return {
        **_SUMMARY,
        "id": model,
        "owned_by": provider,
        "parameter_contract_url": f"/v1/model-parameters?model={model}",
    }


def _parameter(support: str) -> dict[str, object]:
    """One contract row whose gateway POLICY is enabled and whose provider EVIDENCE varies.

    The shared fixture carries no ``seed`` row, and it sits inside the append-only glob, so the
    support levels this module needs are built here instead of edited into it.
    """
    return {
        "request_path": "seed",
        "schema": {"type": "integer"},
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


def _details(model: str, support_by_model: dict[str, str]) -> dict[str, object]:
    """The fixture contract for one Model, with ``seed`` at that Model's support level."""
    value: dict[str, Any] = copy.deepcopy(_DETAILS)
    provider, upstream = model.split("/", 1)
    value["model"] = {
        "id": model,
        "gateway_provider": provider,
        "upstream_id": upstream,
    }
    value["parameters"]["seed"] = _parameter(support_by_model.get(model, "supported"))
    return value


def _unsupported_temperature(model: str, support_by_model: dict[str, str]) -> dict[str, object]:
    """The same contract, but with the PROVIDER denying ``temperature`` instead of ``seed``."""
    value: dict[str, Any] = _details(model, support_by_model)
    if model in support_by_model:
        value["parameters"]["temperature"]["provider"]["support"] = support_by_model[model]
    return value


class _ForbiddenTransport:
    called = False

    def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("provider-support preflight must refuse before any spend")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


class _ReachedTransport:
    called = False

    def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise RuntimeError("execution reached")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


class _AsyncForbiddenTransport:
    called = False

    async def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("provider-support preflight must refuse before any spend")

    async def cancel_active(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _engine(
    support_by_model: dict[str, str],
    *,
    models: tuple[str, ...] = (_MEMBER, _SYNTH),
    build: Any = _details,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/benchmarks/fixture":
            response = httpx.Response(200, json=_BENCHMARK)
        elif request.url.path == "/v1/models":
            response = httpx.Response(
                200,
                json={"object": "list", "data": [_summary(model) for model in models]},
            )
        elif request.url.path == "/v1/model-parameters":
            model = request.url.params["model"]
            response = httpx.Response(200, json=build(model, support_by_model))
        else:
            response = httpx.Response(404)
        return response

    return httpx.MockTransport(handler)


def _fusion() -> sf.Recipe:
    return sf.Fusion([sf.Model(_MEMBER)], synthesizer=_SYNTH)


def test_seeded_fusion_refuses_before_spend_when_the_synthesizer_provider_denies_seed() -> None:
    """The measured bug: the run died mid-flight AFTER billing the members that worked.

    INVARIANT: pre-spend. The cost of this bug was money, so the assertion that matters is that
    the transport is never reached, not merely that an error is raised.
    """
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_SYNTH: "unsupported"}),
        run_transport=transport,
    )

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(_fusion(), benchmark="fixture", answer_seed=42)

    assert caught.value.code == "unsupported_model_parameter"
    assert caught.value.permanent is True
    assert transport.called is False


def test_the_refusal_names_the_parameter_the_model_and_the_reproducibility_cost() -> None:
    """A message reading like an outage is what made the original failure unactionable."""
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_SYNTH: "unsupported"}),
        run_transport=transport,
    )

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(_fusion(), benchmark="fixture", answer_seed=42)

    message = str(caught.value)
    assert "'seed'" in message
    assert _SYNTH in message
    assert "reproducible" in message
    assert caught.value.details == {
        "model": _SYNTH,
        "parameter": "seed",
        "provider_support": "unsupported",
        "provider_source": "openrouter:models",
    }


def test_a_denied_parameter_reports_the_denial_even_when_the_value_is_also_invalid() -> None:
    """Gate 3 runs BEFORE schema validation, and that order decides the user's next action.

    INVARIANT: pins gate 3 above gate 4. Reversed, a denied `seed` carrying a bad value reports
    `invalid_model_parameter` — "expected integer" — so the researcher corrects the value,
    reruns, and hits the same wall. The provider's denial is the fact that ends the
    conversation, so it is the one reported. Measured: both orders leave every other test in
    this suite green, which is exactly why this one has to exist.
    """
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_MEMBER: "unsupported"}),
        run_transport=transport,
    )

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(sf.Model(_MEMBER, params={"seed": "not-an-integer"}), benchmark="fixture")

    assert caught.value.code == "unsupported_model_parameter"
    assert "is not supported by the provider" in str(caught.value)
    assert transport.called is False


def test_gateway_disabled_parameter_keeps_its_credential_reason_when_provider_denies() -> None:
    """Gate 3 runs AFTER the gateway-policy gate, and that order is load-bearing too.

    INVARIANT: pins gate 3 below gate 2. Reversed, a row this account's auth mode cannot reach
    loses the message naming WHICH credential would open it, and the reader is told the provider
    refuses when connecting the right credential would in fact have worked.
    """
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_MEMBER: "unsupported"}, build=_gateway_disabled_seed),
        run_transport=transport,
    )

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(sf.Model(_MEMBER, params={"seed": 42}), benchmark="fixture")

    assert "is disabled for Model" in str(caught.value)
    assert caught.value.details == {
        "model": _MEMBER,
        "parameter": "seed",
        "reason": "projection_not_available_for_auth_mode",
        "applicable_auth_modes": ["oauth"],
    }
    assert transport.called is False


def test_a_denial_read_from_a_stale_catalogue_says_so_in_the_hint() -> None:
    """A stale verdict can refuse a run that would work today, so the reader is told.

    INVARIANT: the refusal still fires — the alternative reopens the mid-run spend this whole
    unit exists to close — but the hint says the evidence is stale, so "swap the Model" is not
    the only visible fix for a verdict that may already be out of date.
    """
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_MEMBER: "unsupported"}, build=_stale_seed),
        run_transport=transport,
    )

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(sf.Model(_MEMBER, params={"seed": 42}), benchmark="fixture")

    assert "stale" in (caught.value.hint or "")
    assert "refreshing it may change the answer" in (caught.value.hint or "")
    assert transport.called is False


def test_one_denying_member_refuses_the_whole_seeded_run_and_names_that_member() -> None:
    """The supporting member must not mask the denying one, whichever is fetched first."""
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_MEMBER: "unsupported"}),
        run_transport=transport,
    )

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(_fusion(), benchmark="fixture", answer_seed=42)

    assert _MEMBER in str(caught.value)
    assert transport.called is False


def test_the_same_fusion_unseeded_still_reaches_execution() -> None:
    """INVARIANT: the seed branch is entered only when a seed is declared.

    This is what keeps an unseeded run's egress byte-identical and every request-keyed cache
    identity valid — the new refusal must be invisible to a run that asked for nothing.
    """
    transport = _ReachedTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_SYNTH: "unsupported"}),
        run_transport=transport,
    )

    with client, pytest.raises(RuntimeError, match="execution reached"):
        client.evaluate(_fusion(), benchmark="fixture")

    assert transport.called is True


def test_a_declared_seed_refuses_through_the_same_gate_with_no_ambient_seed() -> None:
    """A typed parameter is a direct instruction, so it refuses on its own evidence."""
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_MEMBER: "unsupported"}),
        run_transport=transport,
    )

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(sf.Model(_MEMBER, params={"seed": 42}), benchmark="fixture")

    assert caught.value.code == "unsupported_model_parameter"
    assert "'seed'" in str(caught.value)
    assert transport.called is False


def test_declaring_the_seed_only_on_models_that_accept_it_is_allowed() -> None:
    """The refusal is about what the run ASKED for, not about who is in the line-up.

    A researcher can still seed a fusion that contains a denying Model by declaring the seed
    per-Model on the ones that accept it and leaving it off the one that does not — the
    supported way to run a deliberately partial sitting. Nothing was asked of the denying
    Model, so nothing is refused.

    INVARIANT: this is the negative space of the gate above, and it is easy to destroy. A
    preflight that checked seed support for every candidate Model regardless of how the seed
    arrived would look stricter and would silently remove this workflow.
    """
    transport = _ReachedTransport()
    candidate = sf.Fusion([sf.Model(_MEMBER, params={"seed": 42})], synthesizer=_SYNTH)
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_SYNTH: "unsupported"}),
        run_transport=transport,
    )

    with client, pytest.raises(RuntimeError, match="execution reached"):
        client.evaluate(candidate, benchmark="fixture")

    assert transport.called is True


@pytest.mark.parametrize("support", ["supported", "conditional", "unknown"])
def test_every_support_level_other_than_unsupported_passes_through_seeded(support: str) -> None:
    """The stated policy: only explicit provider denial acts.

    INVARIANT: ``unknown`` is the default when no discovery source spoke, so refusing on it
    would refuse on absent evidence and block models that work today; ``conditional`` means the
    provider does accept the parameter under a condition a catalogue row cannot express.
    """
    transport = _ReachedTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_MEMBER: support, _SYNTH: support}),
        run_transport=transport,
    )

    with client, pytest.raises(RuntimeError, match="execution reached"):
        client.evaluate(_fusion(), benchmark="fixture", answer_seed=42)

    assert transport.called is True


def test_the_rule_is_over_the_field_not_special_cased_to_seed() -> None:
    """A declared non-seed parameter the provider denies refuses too, without seed wording."""
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_MEMBER: "unsupported"}, build=_unsupported_temperature),
        run_transport=transport,
    )

    with client, pytest.raises(sf.PlanningError) as caught:
        client.evaluate(sf.Model(_MEMBER, params={"temperature": 0.2}), benchmark="fixture")

    message = str(caught.value)
    assert "'temperature'" in message
    assert "reproducible" not in message
    assert transport.called is False


@pytest.mark.asyncio
async def test_async_evaluation_shares_the_same_provider_support_gate() -> None:
    transport = _AsyncForbiddenTransport()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=_engine({_SYNTH: "unsupported"}),
        run_transport=transport,
    )

    with pytest.raises(sf.PlanningError) as caught:
        await client.evaluate(_fusion(), benchmark="fixture", answer_seed=42)
    await client.aclose()

    assert caught.value.code == "unsupported_model_parameter"
    assert transport.called is False


# Row builders for the gate-ORDER and staleness cases below. They live at the end of the
# module, after the tests that use them, because this file is append-only across cycles:
# new content goes at the bottom so a reader diffing two cycles sees additions only.
def _gateway_disabled_parameter(support: str) -> dict[str, object]:
    """The same row with the GATEWAY's door shut too — both axes closed on one parameter."""
    row: dict[str, Any] = _parameter(support)
    row["gateway"] = {
        "status": "disabled",
        "reason": "projection_not_available_for_auth_mode",
        "cache_behavior": "bypass",
        "applicable_auth_modes": ["oauth"],
    }
    return row


def _gateway_disabled_seed(model: str, support_by_model: dict[str, str]) -> dict[str, object]:
    """A ``seed`` row the GATEWAY disables while the provider ALSO denies it — both gates shut."""
    value: dict[str, Any] = _details(model, support_by_model)
    value["parameters"]["seed"] = _gateway_disabled_parameter(
        support_by_model.get(model, "supported")
    )
    return value


def _stale_seed(model: str, support_by_model: dict[str, str]) -> dict[str, object]:
    """A denial read from a catalogue snapshot the cache has marked stale."""
    value: dict[str, Any] = _details(model, support_by_model)
    row: dict[str, Any] = _parameter(support_by_model.get(model, "supported"))
    row["provider"] = {**row["provider"], "stale": True}
    value["parameters"]["seed"] = row
    return value


def test_the_notebook_call_sf_evaluate_reaches_the_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal is reachable from the door the examples actually use.

    Every test above drives `Client.evaluate`, but `examples/*.ipynb` — and the run that
    produced this ticket's evidence — call the module-level `sf.evaluate`. Those are two links
    in one chain, each pinned separately: the wrapper's forwarding in
    `test_default_client_evaluate_passthrough.py`, the gate here. Two pinned links do not pin
    the join, and this is the exact join that silently came apart before: `answer_seed` shipped
    on the Client and stayed unreachable from `sf.evaluate` until a `TypeError` surfaced it
    (OME-1227).

    So this drives the REAL default-client seam — a real `Client` behind
    `default_client`, not a recording stub — and asserts the notebook idiom refuses pre-spend.
    """
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=_engine({_SYNTH: "unsupported"}),
        run_transport=transport,
    )
    monkeypatch.setattr(_default_client, "default_client", lambda: client)

    with client, pytest.raises(sf.PlanningError) as caught:
        sf.evaluate(_fusion(), benchmark="fixture", answer_seed=42)

    assert caught.value.code == "unsupported_model_parameter"
    assert _SYNTH in str(caught.value)
    assert transport.called is False
