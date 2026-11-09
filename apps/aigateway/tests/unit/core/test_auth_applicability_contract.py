"""OME-649 (OME-479 §6.3): auth applicability in the detailed contract.

FEATURE: a detailed ``/v1/model-parameters`` contract that says WHICH credential a
parameter needs. A rule the gateway holds but which does not cover the reading auth
mode stays visible and DISABLED, carrying the modes that do cover it.

STORY: as an API consumer on an OAuth (Claude Code subscription) connection I can see
that Anthropic's native ``top_k`` is disabled *for my credential* rather than missing
from the gateway — so I know connecting an API key enables it, instead of waiting for
gateway work that already shipped.

INVARIANT (evidence-only, unchanged): making a non-covering rule VISIBLE never makes it
DISPATCHABLE and never enters the ``/v1/models`` summary. Only a covering rule
authorizes, and the dispatch classifier filters on its own path.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.auth_types import AuthType
from aigateway.core.chat_parameters import (
    ParameterProjectionRule,
    ParameterSchema,
    ProviderParameterObservation,
    compose_contract_entries,
    inline_supported_parameters,
    normalize_rules,
)
from aigateway.core.model_parameter_contract import build_model_parameter_document
from aigateway.core.parameter_projection import (
    UnsupportedParametersError,
    classify_and_project_chat_parameters,
)
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin

_API_KEY_ONLY: tuple[AuthType, ...] = ("api_key",)
_BOTH: tuple[AuthType, ...] = ("api_key", "oauth")

# The two DISABLED reasons this unit separates. Spelled out here rather than imported
# from the private module constants: these are PUBLISHED strings a client reads, so the
# test must break if the wire value changes even when the constant is merely renamed.
_AUTH_REASON = "projection_not_available_for_auth_mode"
_UNPROJECTED_REASON = "projection_not_implemented"

# WHY: this suite exercises auth applicability, so use a model where top_k is
# genuinely supported. Opus 4.7+ rejects every non-default sampling value.
_ANTHROPIC_MODEL = "anthropic/claude-sonnet-4-5"
_NATIVE_TOP_K = "provider_params.top_k"
_STATIC = "anthropic:static"


def _rule(
    request_path: str,
    *,
    auth_modes: tuple[AuthType, ...],
    schema: ParameterSchema | None = None,
) -> ParameterProjectionRule:
    return ParameterProjectionRule(
        request_path=request_path,
        applicable_auth_modes=auth_modes,
        projection_kind="direct",
        cache_behavior="bypass",
        projection_revision="r1",
        schema=schema,
    )


def _obs(request_path: str, *, source: str = "labelled_static") -> ProviderParameterObservation:
    return ProviderParameterObservation(
        request_path=request_path, support="supported", source=source
    )


def _rows(
    rules: tuple[ParameterProjectionRule, ...],
    observations: tuple[ProviderParameterObservation, ...],
    *,
    auth_mode: AuthType,
) -> dict[str, dict[str, Any]]:
    entries = compose_contract_entries(normalize_rules(rules), observations, auth_mode=auth_mode)
    return {entry.request_path: entry.to_detail_dict() for entry in entries}


# --- the rule survives composition -------------------------------------------


def test_a_rule_that_does_not_cover_the_reading_mode_is_not_dropped() -> None:
    rows = _rows((_rule("top_k", auth_modes=_API_KEY_ONLY),), (_obs("top_k"),), auth_mode="oauth")

    # the DEFECT: the rule was filtered out of the rule side, so this path could only
    # arrive through the observation branch — as if the gateway had no projection.
    assert "top_k" in rows
    assert rows["top_k"]["gateway"]["status"] == "disabled"
    assert rows["top_k"]["gateway"]["reason"] == _AUTH_REASON


def test_the_rule_survives_even_when_nothing_observed_the_path() -> None:
    # No observation at all: under the old filter the path vanished entirely, so a
    # client could not tell "no such parameter" from "not for this credential".
    rows = _rows((_rule("top_k", auth_modes=_API_KEY_ONLY),), (), auth_mode="oauth")

    assert rows["top_k"]["gateway"]["reason"] == _AUTH_REASON
    assert rows["top_k"]["gateway"]["applicable_auth_modes"] == ["api_key"]
    # nothing was observed, so the evidence axis says exactly that — a surviving rule
    # must not invent provider evidence to justify its own visibility.
    assert rows["top_k"]["provider"]["support"] == "unknown"
    assert rows["top_k"]["provider"]["source"] == "none"


# --- the two disabled reasons are distinguishable ----------------------------


def test_wrong_auth_and_unimplemented_are_separate_reasons_in_one_document() -> None:
    rows = _rows(
        (_rule("top_k", auth_modes=_API_KEY_ONLY),),
        (_obs("top_k"), _obs("provider_params.unruled")),
        auth_mode="oauth",
    )

    # both DISABLED, and a client can act on exactly one of them: connect an API key.
    assert rows["top_k"]["gateway"]["status"] == "disabled"
    assert rows["provider_params.unruled"]["gateway"]["status"] == "disabled"
    assert rows["top_k"]["gateway"]["reason"] == _AUTH_REASON
    assert rows["provider_params.unruled"]["gateway"]["reason"] == _UNPROJECTED_REASON


def test_an_unruled_path_still_publishes_the_unimplemented_reason_under_every_mode() -> None:
    # Regression guard on the branch this unit did NOT change: no rule at all keeps its
    # original reason, so widening the composer did not reclassify unruled evidence.
    for auth_mode in ("api_key", "oauth"):
        rows = _rows((), (_obs("provider_params.unruled"),), auth_mode=auth_mode)
        assert rows["provider_params.unruled"]["gateway"]["reason"] == _UNPROJECTED_REASON
        assert rows["provider_params.unruled"]["gateway"]["applicable_auth_modes"] == []


# --- applicability is published ----------------------------------------------


def test_the_disabled_row_publishes_the_modes_that_do_cover_the_rule() -> None:
    rows = _rows((_rule("top_k", auth_modes=_API_KEY_ONLY),), (_obs("top_k"),), auth_mode="oauth")

    # the actionable half: "disabled" alone is a dead end; this names the way out.
    assert rows["top_k"]["gateway"]["applicable_auth_modes"] == ["api_key"]


def test_an_enabled_row_publishes_its_applicability_too() -> None:
    rows = _rows(
        (_rule("temperature", auth_modes=_BOTH),), (_obs("temperature"),), auth_mode="oauth"
    )

    assert rows["temperature"]["gateway"]["status"] == "enabled"
    assert rows["temperature"]["gateway"]["applicable_auth_modes"] == ["api_key", "oauth"]


def test_the_published_applicability_is_the_rules_own_tuple_not_the_reading_mode() -> None:
    # INVARIANT: the field describes the RULE, so it reads identically from either
    # credential. A value that tracked the reading mode would be useless — the client
    # already knows which mode it is reading as (``context.auth_mode``).
    rules = (_rule("top_k", auth_modes=_API_KEY_ONLY),)
    observations = (_obs("top_k"),)
    from_api_key = _rows(rules, observations, auth_mode="api_key")
    from_oauth = _rows(rules, observations, auth_mode="oauth")

    assert from_api_key["top_k"]["gateway"]["applicable_auth_modes"] == ["api_key"]
    assert from_oauth["top_k"]["gateway"]["applicable_auth_modes"] == ["api_key"]
    # ... while the STATUS is exactly what differs between the two reads.
    assert from_api_key["top_k"]["gateway"]["status"] == "enabled"
    assert from_oauth["top_k"]["gateway"]["status"] == "disabled"


# --- the reviewed schema reaches the disabled row -----------------------------


def test_the_disabled_row_publishes_the_rules_reviewed_schema() -> None:
    schema = ParameterSchema(type="integer", minimum=1)
    # the observation carries NO schema, which is the shipping Anthropic shape.
    rows = _rows(
        (_rule("top_k", auth_modes=_API_KEY_ONLY, schema=schema),),
        (_obs("top_k"),),
        auth_mode="oauth",
    )

    # WHY this matters: the row now asserts a reviewed projection exists. Publishing
    # null for what it validates would contradict that claim in the same object.
    assert rows["top_k"]["schema"] == {"type": "integer", "minimum": 1}


def test_an_observation_schema_still_fills_in_where_no_rule_has_one() -> None:
    observed_schema = ParameterSchema(type="number", minimum=0, maximum=2)
    rows = _rows(
        (_rule("top_k", auth_modes=_API_KEY_ONLY),),
        (
            ProviderParameterObservation(
                request_path="top_k",
                support="supported",
                source="labelled_static",
                schema=observed_schema,
            ),
        ),
        auth_mode="oauth",
    )

    assert rows["top_k"]["schema"] == {"type": "number", "minimum": 0, "maximum": 2}


# --- the serialized shape ------------------------------------------------------


def test_the_disabled_for_auth_gateway_block_serializes_to_an_exact_shape() -> None:
    rows = _rows(
        (_rule("top_k", auth_modes=_API_KEY_ONLY, schema=ParameterSchema(type="integer")),),
        (_obs("top_k"),),
        auth_mode="oauth",
    )

    # EXACT equality: the key set is pinned, not sampled, so a future field cannot be
    # added to the published gateway block without a decision recorded here.
    assert rows["top_k"]["gateway"] == {
        "status": "disabled",
        "reason": _AUTH_REASON,
        # a disabled row forwards nothing, so it keys nothing.
        "cache_behavior": "bypass",
        "applicable_auth_modes": ["api_key"],
    }


# --- evidence-only semantics are untouched -------------------------------------


def test_a_visible_non_covering_rule_is_still_refused_at_dispatch() -> None:
    # THE invariant this unit must not breach: publishing a row is not authorizing it.
    rules = (_rule("top_k", auth_modes=_API_KEY_ONLY),)
    with pytest.raises(UnsupportedParametersError):
        classify_and_project_chat_parameters(
            {"model": "m", "messages": [], "top_k": 3}, rules=rules, auth_mode="oauth"
        )
    # the same field under the covering credential DOES project — so the refusal above
    # is the auth filter, not an unrelated rejection.
    projected = classify_and_project_chat_parameters(
        {"model": "m", "messages": [], "top_k": 3}, rules=rules, auth_mode="api_key"
    )
    assert projected["top_k"] == 3


def test_a_visible_non_covering_rule_stays_out_of_the_conservative_summary() -> None:
    rules = normalize_rules(
        (_rule("temperature", auth_modes=_BOTH), _rule("top_k", auth_modes=_API_KEY_ONLY))
    )
    summary = inline_supported_parameters(rules, available_auth_modes=_BOTH)

    # §6.3: the profile-independent summary is the INTERSECTION, so a field one
    # credential cannot use never appears — regardless of what the detail row shows.
    assert "temperature" in summary
    assert "top_k" not in summary


# --- through the real Anthropic contract ---------------------------------------


def _anthropic_document(auth_mode: AuthType, *, extra_observations: tuple = ()) -> dict[str, Any]:
    # Mirrors routes/model_parameters.py: the SAME plugin hooks, the SAME composer.
    plugin = AnthropicProviderPlugin()
    return build_model_parameter_document(
        canonical_id=_ANTHROPIC_MODEL,
        gateway_provider="anthropic",
        auth_mode=auth_mode,
        scope="account_connection",
        context_identity="acct:test|prof:1",
        rules=plugin.chat_parameter_rules(model=_ANTHROPIC_MODEL, auth_type=auth_mode),
        observations=(
            *plugin.chat_parameter_observations(model=_ANTHROPIC_MODEL, auth_type=auth_mode),
            *extra_observations,
        ),
        tools=plugin.chat_parameter_tools(model=_ANTHROPIC_MODEL, auth_type=auth_mode),
        transport=plugin.chat_transport_capabilities(model=_ANTHROPIC_MODEL, auth_type=auth_mode),
        freshness={"stale": False, "degraded": False},
    )


def test_the_real_anthropic_contract_shows_both_disabled_kinds_side_by_side() -> None:
    # Anthropic observes exactly the paths it rules, so the unruled half is supplied
    # here — the point is that ONE document can carry both reasons unambiguously.
    document = _anthropic_document("oauth", extra_observations=(_obs("provider_params.unruled"),))
    params = document["parameters"]

    assert params[_NATIVE_TOP_K]["gateway"]["reason"] == _AUTH_REASON
    assert params[_NATIVE_TOP_K]["gateway"]["applicable_auth_modes"] == ["api_key"]
    assert params["provider_params.unruled"]["gateway"]["reason"] == _UNPROJECTED_REASON
    assert params["provider_params.unruled"]["gateway"]["applicable_auth_modes"] == []


@pytest.mark.asyncio
async def test_the_route_reports_native_top_k_enabled_on_an_api_key_credential(
    authenticated_client,
) -> None:
    body = await _anthropic_contract(authenticated_client, "api_key")
    entry = body["parameters"][_NATIVE_TOP_K]

    assert body["context"]["auth_mode"] == "api_key"
    assert entry["gateway"]["status"] == "enabled"
    assert entry["gateway"]["applicable_auth_modes"] == ["api_key"]


@pytest.mark.asyncio
async def test_the_route_reports_native_top_k_wrong_auth_on_an_oauth_credential(
    authenticated_client,
) -> None:
    body = await _anthropic_contract(authenticated_client, "oauth")
    entry = body["parameters"][_NATIVE_TOP_K]

    assert body["context"]["auth_mode"] == "oauth"
    assert entry["gateway"]["status"] == "disabled"
    # the served string, through the real route — not the composer in isolation.
    assert entry["gateway"]["reason"] == _AUTH_REASON
    assert entry["gateway"]["applicable_auth_modes"] == ["api_key"]
    # the evidence axis is untouched by the auth verdict: the field IS supported
    # upstream, and the contract keeps saying so.
    assert entry["provider"]["support"] == "supported"
    assert entry["provider"]["source"] == _STATIC


@pytest.mark.asyncio
async def test_the_served_oauth_contract_never_calls_a_shipped_projection_unimplemented(
    authenticated_client,
) -> None:
    body = await _anthropic_contract(authenticated_client, "oauth")

    # Every Anthropic path is ruled, so after this unit NO row in the served document
    # may claim the gateway has no projection for it.
    unimplemented = [
        path
        for path, entry in body["parameters"].items()
        if entry["gateway"].get("reason") == _UNPROJECTED_REASON
    ]
    assert unimplemented == []


async def _anthropic_contract(client, auth_type: AuthType) -> dict[str, Any]:
    from tests.unit.migrated_pair_seed import seed_migrated_pair

    account_id = client.get("/v1/auth/me").json()["id"]
    # WHY the key: a migrated api_key pair reads its blob at resolve; an OAuth one reads none.
    key = "sk-ant-api03-never-validated" if auth_type == "api_key" else None
    seed_migrated_pair(client, account_id, "anthropic", auth_type=auth_type, credential=key)
    resp = client.get("/v1/model-parameters", params={"model": _ANTHROPIC_MODEL})
    assert resp.status_code == 200, resp.text
    return resp.json()
