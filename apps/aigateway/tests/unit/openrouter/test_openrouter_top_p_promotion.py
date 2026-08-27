"""OME-479 closure Unit 2: provider-local OpenRouter ``top_p`` promotion.

FEATURE: one reviewed rule enables validated dispatch without shared core/route edits.
STORY: callers can send the observed field under validation and strict routing.
INVARIANT: observation remains evidence only; the rule is authorization.
INVARIANT: final wire carries ``top_p`` with ``require_parameters=true``.
AIDEV-NOTE: the local route harness owns its autouse API-key-validation fixture.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from aigateway.core.chat_parameters import inline_supported_parameters
from aigateway.core.model_parameter_contract import build_model_parameter_document
from aigateway.core.parameter_projection import (
    UnsupportedParametersError,
    classify_and_project_chat_parameters,
)
from aigateway.core.standard_parameters import direct_rule
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.parameters import _AUTH, _REVISION
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_KEY = "sk-or-v1-test"
_MODEL = "openrouter/anthropic/claude-fable-5"
_UPSTREAM = "anthropic/claude-fable-5"
_MESSAGES: list[Any] = [{"role": "user", "content": "hi"}]
# Spelled out so a production rename cannot silently rename the wire expectation.
_STRICT = {"require_parameters": True}


# Harness


@pytest.fixture(autouse=True)
def _api_key_validation_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # Explicit test double: key readiness is not what this promotion exercises.
    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(_self, _plugin, _provider, _api_key) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


@pytest.fixture()
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN,
        "settings",
        # OME-972 setup-only amendment: this suite exercises the STATIC top_p
        # promotion, not live discovery — live_models=False keeps its listing
        # reads off the (transport-less) live catalog. Assertions untouched.
        OpenRouterPluginSettings(enabled=True, live_models=False),
    )


@pytest.fixture()
def _cache_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")


@pytest.fixture()
def cache_client(_cache_env, authenticated_client: TestClient) -> TestClient:
    return authenticated_client


def _rules(*, without: str | None = None):
    plugin = OpenRouterProviderPlugin()
    rules = plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key")
    if without is None:
        return rules
    return tuple(rule for rule in rules if rule.request_path != without)


def _dispatch_body(caller_body: dict[str, Any], *, without: str | None = None) -> dict[str, Any]:
    """The exact route pipeline: strip controls → fail-closed classify/project → prepare."""
    plugin = OpenRouterProviderPlugin()
    stripped = plugin.strip_provider_dispatch_controls(caller_body)
    projected = classify_and_project_chat_parameters(
        stripped, rules=_rules(without=without), auth_mode="api_key"
    )
    return plugin.prepare_chat_body(projected)


def _wire_json(dispatch_body: dict[str, Any]) -> dict[str, Any]:
    """The FINAL OpenRouter request JSON, through the installed litellm path."""
    from litellm.llms.openrouter.chat.transformation import OpenrouterConfig
    from litellm.utils import get_optional_params

    passthrough = {
        key: value
        for key, value in dispatch_body.items()
        # Transport plumbing, not request content — never part of the JSON body.
        if key not in {"model", "messages", "api_base", "extra_headers", "api_key"}
    }
    optional = get_optional_params(model=_UPSTREAM, custom_llm_provider="openrouter", **passthrough)
    return OpenrouterConfig().transform_request(
        model=_UPSTREAM,
        messages=list(_MESSAGES),
        optional_params=dict(optional),
        litellm_params={},
        headers={},
    )


def _parameters(*, without: str | None = None) -> dict[str, Any]:
    # Mirrors routes/model_parameters.py verbatim: the SAME plugin hooks, the SAME
    # composer. ``without`` withholds a rule while leaving observations untouched.
    plugin = OpenRouterProviderPlugin()
    document = build_model_parameter_document(
        canonical_id=_MODEL,
        gateway_provider="openrouter",
        auth_mode="api_key",
        scope="account_profile",
        context_identity="acct:test|prof:1",
        rules=_rules(without=without),
        observations=plugin.chat_parameter_observations(model=_MODEL, auth_type="api_key"),
        tools=plugin.chat_parameter_tools(model=_MODEL, auth_type="api_key"),
        transport=plugin.chat_transport_capabilities(model=_MODEL, auth_type="api_key"),
        freshness={"stale": False, "degraded": False},
    )
    return document["parameters"]


def _create_connection(client) -> None:
    resp = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "work-openrouter", "api_key": _KEY},
    )
    assert resp.status_code == 201, resp.text


def _fake_acompletion(captured: dict):
    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            model_dump=lambda: {"id": "or-1", "choices": [{"message": {"content": "ok"}}]}
        )

    return fake_acompletion


def _post_chat(client, body: dict[str, Any] | None = None):
    payload = {"model": _MODEL, "messages": list(_MESSAGES), **(body or {})}
    return client.post("/v1/chat/completions", json=payload)


# (1) Provider-local schema validation


def test_the_rule_binds_the_shared_bounded_top_p_schema() -> None:
    # OpenRouter uses the shared [0, 1] range; unlike top_k, no local override is needed.
    from aigateway.core.standard_parameters import TOP_P_SCHEMA

    rule = next(r for r in _rules() if r.request_path == "top_p")
    assert rule.parameter_schema == TOP_P_SCHEMA
    assert rule.applicable_auth_modes == ("api_key",)


@pytest.mark.parametrize("value", [0, 0.5, 1, 1.0])
def test_in_range_values_validate(value) -> None:
    rule = next(r for r in _rules() if r.request_path == "top_p")
    assert rule.parameter_schema is not None
    rule.parameter_schema.validate_value(value)  # does not raise


@pytest.mark.parametrize("value", [-0.1, 1.1, 2, "0.5", True, None, [0.5]])
def test_out_of_range_or_mistyped_values_fail_closed(value) -> None:
    from aigateway.core.chat_parameters import ParameterValidationError

    rule = next(r for r in _rules() if r.request_path == "top_p")
    assert rule.parameter_schema is not None
    with pytest.raises(ParameterValidationError):
        rule.parameter_schema.validate_value(value)


# (2) Provider-local rule and projection


def test_top_p_projects_to_its_own_top_level_target() -> None:
    # A direct field must not disturb the separately projected native top_k.
    body = _dispatch_body(
        {
            "model": _MODEL,
            "messages": list(_MESSAGES),
            "top_p": 0.9,
            "provider_params": {"top_k": 40},
        }
    )
    assert body["top_p"] == 0.9
    assert body["extra_body"] == {"top_k": 40}
    assert "provider_params" not in body


# (3) Observation is evidence; the rule is authorization


def test_the_observation_alone_still_does_not_authorize() -> None:
    """The two axes stay independent AFTER the promotion.

    Before this unit, ``top_p`` demonstrated the property by accident: it was
    observed and happened to have no rule. Withholding the rule while leaving the
    REAL observation set untouched proves the same property deliberately — the
    observation is unchanged by this commit, so it cannot be what enabled the
    field.
    """
    plugin = OpenRouterProviderPlugin()
    observed = {o.request_path for o in plugin.chat_parameter_observations(model=_MODEL)}
    assert "top_p" in observed, "the evidence this unit relies on must still be present"

    with pytest.raises(UnsupportedParametersError) as exc:
        classify_and_project_chat_parameters(
            {"model": _MODEL, "messages": list(_MESSAGES), "top_p": 0.9},
            rules=_rules(without="top_p"),
            auth_mode="api_key",
        )
    assert exc.value.rejected == {"top_p": "unknown"}

    # …and the contract says so too, for the same reason.
    entry = _parameters(without="top_p")["top_p"]
    assert entry["provider"]["support"] == "supported"
    assert entry["gateway"]["status"] == "disabled"
    assert entry["gateway"]["reason"] == "projection_not_implemented"


def test_the_promotion_added_a_rule_and_left_the_evidence_alone() -> None:
    # The ruled set grows; the observation source remains independent.
    plugin = OpenRouterProviderPlugin()
    observed = {o.request_path for o in plugin.chat_parameter_observations(model=_MODEL)}
    ruled = {r.request_path for r in _rules()}
    assert "top_p" in ruled
    assert observed - ruled == set(), (
        "every observed OpenRouter path is now ruled; if this fails a new "
        "observation appeared and needs its own review, not an automatic rule"
    )


# (4) The detailed contract moves the field from disabled to enabled


def test_the_detail_contract_publishes_top_p_as_enabled_with_evidence() -> None:
    entry = _parameters()["top_p"]
    assert entry["gateway"]["status"] == "enabled"
    assert entry["gateway"]["projection"] == "direct"
    assert entry["gateway"]["applicable_auth_modes"] == ["api_key"]
    # the disabled reason is GONE, not left stale next to an enabled status
    assert "reason" not in entry["gateway"]
    # it keeps the evidence it always had — enabling did not fabricate provenance
    assert entry["provider"]["support"] == "supported"
    assert entry["provider"]["source"] == "openrouter:static"
    # and it publishes the bounded schema callers must satisfy
    assert entry["schema"]["type"] == "number"
    assert entry["schema"]["minimum"] == 0
    assert entry["schema"]["maximum"] == 1


# (5) The /v1/models summary stays correct


def test_the_model_summary_advertises_top_p_from_the_same_rule_set() -> None:
    summary = set(inline_supported_parameters(_rules(), available_auth_modes=("api_key",)))
    assert "top_p" in summary
    # one source, three surfaces: the summary never advertises a path the
    # classifier would reject.
    assert summary == {r.request_path for r in _rules()}


def test_the_live_models_route_lists_top_p_for_openrouter(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    rows = authenticated_client.get("/v1/models").json()["data"]
    openrouter_rows = [row for row in rows if row["id"].startswith("openrouter/")]
    assert openrouter_rows, "the enabled OpenRouter plugin must contribute rows"
    for row in openrouter_rows:
        assert "top_p" in row["supported_parameters"], row["id"]


# (6) Chat accepts valid values and rejects invalid ones before dispatch


def test_a_valid_top_p_reaches_dispatch(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    captured: dict = {}
    with patch("litellm.acompletion", _fake_acompletion(captured)):
        resp = _post_chat(authenticated_client, {"top_p": 0.9})
    assert resp.status_code == 200, resp.text
    assert captured["top_p"] == 0.9


@pytest.mark.parametrize("value", [1.5, -0.5, "0.9"])
def test_an_invalid_top_p_rejects_before_credential_access_and_dispatch(
    value, enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # INVARIANT: a malformed value costs the caller nothing — no credential read,
    # no provider call. A parameter that reaches OpenRouter and fails there has
    # already spent a stored credential.
    _create_connection(authenticated_client)
    captured: dict = {}
    with patch("litellm.acompletion", _fake_acompletion(captured)):
        resp = _post_chat(authenticated_client, {"top_p": value})
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["rejected"] == {"top_p": "malformed"}
    assert captured == {}  # fail closed


# (7) + (8) Final wire JSON carries the value and strict routing


def test_final_wire_json_carries_top_p_together_with_strict_routing() -> None:
    # The load-bearing proof, against the INSTALLED litellm transform rather than
    # mocked dispatch kwargs: the promotion is only real if OpenRouter receives
    # the value, and only SAFE if it receives it under require_parameters=true —
    # otherwise an endpoint that ignores top_p would silently serve a differently
    # sampled response.
    wire = _wire_json(_dispatch_body({"model": _MODEL, "messages": list(_MESSAGES), "top_p": 0.9}))
    assert wire["top_p"] == 0.9
    assert wire["provider"] == _STRICT


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_the_boundary_values_survive_the_installed_transform(value) -> None:
    # FINAL-TRANSFORM PROOF: the gateway accepts the closed interval [0, 1], so
    # both endpoints must reach the wire unchanged — 0.0 in particular, since a
    # falsy value is the one a "drop empty params" transform would silently eat.
    body = _dispatch_body({"model": _MODEL, "messages": list(_MESSAGES), "top_p": value})
    wire = _wire_json(body)
    assert wire["top_p"] == value
    assert wire["provider"] == _STRICT


def test_a_caller_cannot_relax_strict_routing_alongside_top_p(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # `provider` carries no rule, so the fail-closed classifier refuses the whole
    # request before any credential is read — the caller cannot pair a promoted
    # parameter with permission for the endpoint to ignore it.
    _create_connection(authenticated_client)
    captured: dict = {}
    with patch("litellm.acompletion", _fake_acompletion(captured)):
        resp = _post_chat(
            authenticated_client,
            {"top_p": 0.9, "provider": {"require_parameters": False, "allow_fallbacks": True}},
        )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["rejected"] == {"provider": "unknown"}
    assert captured == {}


def test_the_boundary_refuses_a_provider_that_reaches_it_with_top_p_present() -> None:
    # Second, independent layer: a projected gateway-owned member is a mismatch;
    # reconstruction may not overwrite it even when an unrelated field is valid.
    plugin = OpenRouterProviderPlugin()
    with pytest.raises(HTTPException) as exc:
        plugin.prepare_chat_body(
            {
                "model": _MODEL,
                "messages": list(_MESSAGES),
                "top_p": 0.9,
                "provider": {"require_parameters": False},
            }
        )
    assert exc.value.status_code == 503


# (9) Observed cache behaviour matches the published declaration


def test_the_contract_declares_top_p_as_keyed() -> None:
    """SUPERSEDED (OME-305, owner decision B).

    Was ``test_the_contract_declares_bypass_for_top_p``, asserting verbatim:
    ``assert _parameters()["top_p"]["gateway"]["cache_behavior"] == "bypass"``.

    Decision B keys every reviewed output-affecting parameter on a provider that
    implements ``global_cache_projection``. ``top_p`` changes the response, so under v1
    it had to bypass (a v1 key could not carry it and OpenRouter bodies were
    structurally ineligible anyway); under v2 it is keyed, which is what makes the
    cache usable by a real client instead of only by bare ``{model, messages}``.
    """
    assert _parameters()["top_p"]["gateway"]["cache_behavior"] == "keyed"


def test_the_caller_visible_policy_reports_top_p_as_a_keyed_path() -> None:
    """The restored policy view agrees with the real OpenRouter rule table."""
    from aigateway.core.parameter_projection import caller_cache_bypass_paths

    rule = next(r for r in _rules() if r.request_path == "top_p")
    assert rule.cache_behavior == "keyed", "the rule must declare what the contract publishes"

    assert (
        caller_cache_bypass_paths(
            {"model": _MODEL, "messages": list(_MESSAGES), "top_p": 0.9},
            rules=_rules(),
            auth_mode="api_key",
        )
        == ()
    )
    # An actual declared-bypass rule proves the helper does not return ``()`` vacuously.
    #
    # WHY a FABRICATED rule rather than a real OpenRouter one (OME-781): this example has
    # broken twice from being coupled to whichever real path happened to be `bypass` —
    # first ``tools`` (OME-787 promoted it to `keyed`), then ``web_search`` (OME-781
    # promoted it too). OpenRouter now has 17 keyed rules and zero `bypass`/
    # `transport_only`, so there is no real path left to couple to, and there is no
    # guarantee a future one stays un-promoted either. A proof of non-vacuity must not
    # depend on some rule staying un-promoted, so it is built from a synthetic rule that
    # cannot be promoted out from under this test.
    synthetic_bypass_rule = direct_rule(
        "_synthetic_bypass_probe",
        auth_modes=_AUTH,
        projection_revision=_REVISION,
        cache_behavior="bypass",
    )
    assert caller_cache_bypass_paths(
        {"model": _MODEL, "messages": list(_MESSAGES), "_synthetic_bypass_probe": True},
        rules=(*_rules(), synthetic_bypass_rule),
        auth_mode="api_key",
    ) == ("_synthetic_bypass_probe",)


def test_two_top_p_values_never_share_a_cache_entry_through_the_real_route(
    enabled_openrouter, credential_blobs, cache_client
) -> None:
    """SUPERSEDED (OME-305, owner decision B) — and STRENGTHENED, not merely flipped.

    Was ``test_a_top_p_request_bypasses_the_cache_through_the_real_route``, asserting
    verbatim: ``assert first.headers["X-AIGW-Cache"] == "bypass"``, ``assert
    "X-AIGW-Cache-Key" not in first.headers`` and ``assert len(calls) == 2, "a declared
    -bypass request must reach the provider every time"``.

    INVARIANT that replaces it, and the one that actually matters once the parameter is
    keyed: a repeat of the SAME ``top_p`` is served from cache, and a DIFFERENT
    ``top_p`` is never served that entry. The old test could only prove the cache was
    not used; keying makes a stronger property both available and necessary, because
    the failure mode changed from "wasted dispatch" to "wrong answer".

    WHY the differing-value half is not optional: promoting a parameter to ``keyed``
    without it in the fingerprint is exactly how one caller receives another caller's
    response. This is the case that would catch it.
    """
    _create_connection(cache_client)
    calls: list[dict] = []

    async def counting_acompletion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            model_dump=lambda: {
                "id": f"or-{len(calls)}",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            }
        )

    with patch("litellm.acompletion", counting_acompletion):
        first = _post_chat(cache_client, {"top_p": 0.9})
        repeat = _post_chat(cache_client, {"top_p": 0.9})
        other = _post_chat(cache_client, {"top_p": 0.5})

    assert first.status_code == repeat.status_code == other.status_code == 200, first.text
    assert first.headers["X-AIGW-Cache"] == "miss"
    assert first.headers["X-AIGW-Cache-Write"] == "stored"
    assert repeat.headers["X-AIGW-Cache"] == "hit"
    assert other.headers["X-AIGW-Cache"] == "miss", "a different top_p must not hit"
    assert first.headers["X-AIGW-Cache-Key"] != other.headers["X-AIGW-Cache-Key"]
    # Two dispatches, not three: the repeat was served from the entry, and the
    # differing value was not.
    assert len(calls) == 2
    assert [c["top_p"] for c in calls] == [0.9, 0.5]
