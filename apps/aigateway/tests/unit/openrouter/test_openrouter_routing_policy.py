"""OME-704: OpenRouter price + privacy routing controls — rules and contract.

FEATURE: a researcher constrains an OpenRouter request by UNIT PRICE and by
downstream DATA POLICY without ever receiving OpenRouter's raw ``provider``
routing control plane. Four logical controls reach the caller as five leaves
under the existing ``provider_params`` wrapper:

    provider_params.sort                 -> provider.sort              (enum: price)
    provider_params.max_price_prompt     -> provider.max_price.prompt   (decimal str)
    provider_params.max_price_completion -> provider.max_price.completion
    provider_params.data_collection      -> provider.data_collection    (allow|deny)
    provider_params.zdr                  -> provider.zdr               (boolean)

STORY: as an authenticated researcher I cap what a benchmark run may pay per
million tokens and forbid endpoints that collect my prompts — and I cannot, through those
same controls, pin a provider, order providers, enable fallbacks, or otherwise
reach the control plane the gateway owns.

INVARIANT: raw ``provider`` stays UNRULED. Every control here is addressed only
at its wrapper path, validated by a gateway-owned schema before any credential
material is read, and projected to a documented ``provider.*`` location the
plugin later reconstructs from an allowlist.

INVARIANT: prices cross the gateway as EXACT decimal STRINGS. A JSON number is
binary floating point, so ``0.0000001`` would already be a different value than
the caller wrote before validation could see it — a silently loosened ceiling.

Wire reconstruction, ``require_parameters`` strictness and the sanitized 503 for
an unexpected projected policy live in test_openrouter_routing_policy_wire.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.auth_types import AuthType
from aigateway.core.chat_parameters import inline_supported_parameters
from aigateway.core.model_parameter_contract import build_model_parameter_document
from aigateway.core.parameter_projection import (
    UnsupportedParametersError,
    classify_and_project_chat_parameters,
)
from aigateway.plugins.openrouter_provider import observations as openrouter_observations
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin

_MODEL = "openrouter/anthropic/claude-fable-5"
_PROMPT: dict[str, Any] = {"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]}

# The five caller-visible leaves and the wire locations they own.
_TARGETS = {
    "sort": ("provider", "sort"),
    "max_price_prompt": ("provider", "max_price", "prompt"),
    "max_price_completion": ("provider", "max_price", "completion"),
    "data_collection": ("provider", "data_collection"),
    "zdr": ("provider", "zdr"),
}
_PATHS = tuple(f"provider_params.{leaf}" for leaf in _TARGETS)

_DECIMAL_PATTERN = r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"


def _rules(auth_mode: AuthType = "api_key"):
    return OpenRouterProviderPlugin().chat_parameter_rules(model=_MODEL, auth_type=auth_mode)


def _classify(wrapper: dict[str, Any], auth_mode: AuthType = "api_key") -> dict[str, Any]:
    """Admit + project a provider_params wrapper through the REAL rule set."""
    return classify_and_project_chat_parameters(
        {**_PROMPT, "provider_params": wrapper},
        rules=_rules(auth_mode),
        auth_mode=auth_mode,
    )


def _rejected(wrapper: dict[str, Any]) -> dict[str, str]:
    with pytest.raises(UnsupportedParametersError) as exc:
        _classify(wrapper)
    return exc.value.rejected


def _rule_by_path() -> dict[str, Any]:
    return {rule.request_path: rule for rule in _rules()}


def test_reviewed_routing_evidence_is_an_explicit_inventory() -> None:
    # Evidence must not be generated from the rules it is meant to corroborate.
    # Equality is the conformance tripwire; the two inventories remain independently
    # reviewable and either side fails when a control is added only once.
    assert openrouter_observations.ROUTING_POLICY_EVIDENCE_LEAVES == frozenset(_TARGETS)


# --- admission: sort ----------------------------------------------------------


def test_sort_price_is_accepted_and_projected() -> None:
    out = _classify({"sort": "price"})
    assert out["provider"] == {"sort": "price"}
    # the caller-visible wrapper is fully consumed; only the provider object goes on
    assert "provider_params" not in out


@pytest.mark.parametrize(
    "value",
    [
        "throughput",  # a real OpenRouter sort this task deliberately does NOT expose
        "latency",
        "PRICE",  # enum membership is case-SENSITIVE
        "price ",
        "",
        "cheapest",
        0,  # not a string at all
        True,
        None,
        ["price"],
        {"sort": "price"},
    ],
)
def test_only_the_price_sort_is_admitted(value: Any) -> None:
    # WHY only `price`: ordering by throughput or latency is provider SELECTION
    # policy, which this task excludes (OME-703 owns pinning). One reviewed enum
    # member is the whole exposed surface, so widening it is a rule change with a
    # review, never a caller decision.
    assert _rejected({"sort": value}) == {"provider_params.sort": "malformed"}


# --- admission: max_price_prompt / max_price_completion -----------------------


@pytest.mark.parametrize("leaf", ["max_price_prompt", "max_price_completion"])
@pytest.mark.parametrize(
    "value",
    [
        "0",  # a zero ceiling is meaningful: free endpoints only
        "1",
        "10",
        "0.5",
        "1.000",  # trailing zeros are the caller's business, not an error
        "100.00",
        "0." + "9" * 62,  # exactly 64 characters — the inclusive bound
    ],
)
def test_a_fixed_point_decimal_price_is_accepted(leaf: str, value: str) -> None:
    out = _classify({leaf: value})
    field = "prompt" if leaf.endswith("prompt") else "completion"
    assert out["provider"] == {"max_price": {field: value}}


@pytest.mark.parametrize("leaf", ["max_price_prompt", "max_price_completion"])
@pytest.mark.parametrize(
    "value",
    [
        1,  # a JSON NUMBER: exactness already lost before we could check it
        1.5,
        0,
        True,
        None,
        "-1",  # a negative ceiling is not a ceiling
        "-0.5",
        "1e5",  # exponent notation: not fixed-point
        "1E5",
        "1e-5",
        "+1",
        "01",  # leading zero: ambiguous spelling of one value
        ".5",
        "1.",
        "1 ",
        " 1",
        "1\n",
        "",
        "NaN",
        "nan",
        "inf",
        "Infinity",
        "-inf",
        "0x1",
        "1_000",
        "1,5",
        "٣",  # a non-ASCII digit int() would happily parse
        "0." + "9" * 63,  # 65 characters — one past the bound
        ["1"],
        {"prompt": "1"},
    ],
)
def test_a_price_that_is_not_an_exact_non_negative_decimal_is_rejected(
    leaf: str, value: Any
) -> None:
    assert _rejected({leaf: value}) == {f"provider_params.{leaf}": "malformed"}


def test_both_price_ceilings_coexist_under_one_max_price_object() -> None:
    # Two independent caller leaves, ONE upstream object — the projection has to
    # merge them rather than have the second overwrite the first.
    out = _classify({"max_price_prompt": "1.5", "max_price_completion": "3"})
    assert out["provider"] == {"max_price": {"prompt": "1.5", "completion": "3"}}


# --- admission: data_collection / zdr ----------------------------------------


@pytest.mark.parametrize("value", ["allow", "deny"])
def test_the_data_collection_policy_enum_is_accepted(value: str) -> None:
    assert _classify({"data_collection": value})["provider"] == {"data_collection": value}


@pytest.mark.parametrize(
    "value", ["ALLOW", "Deny", "denied", "none", "", "off", True, False, 0, None, ["deny"]]
)
def test_any_other_data_collection_value_is_rejected(value: Any) -> None:
    assert _rejected({"data_collection": value}) == {"provider_params.data_collection": "malformed"}


@pytest.mark.parametrize("value", [True, False])
def test_zdr_accepts_a_real_boolean(value: bool) -> None:
    # INVARIANT: `false` is ADMITTED here (it is a valid caller statement); whether
    # it reaches the wire is the provider boundary's decision, proven in the wire
    # module — admission and projection are separate questions.
    assert _classify({"zdr": value})["provider"] == {"zdr": value}


@pytest.mark.parametrize("value", ["true", "false", "1", 1, 0, "", None, [], {}])
def test_zdr_rejects_anything_that_is_not_a_boolean(value: Any) -> None:
    assert _rejected({"zdr": value}) == {"provider_params.zdr": "malformed"}


# --- the whole policy at once -------------------------------------------------


def test_all_five_controls_project_to_their_documented_wire_locations() -> None:
    out = _classify(
        {
            "sort": "price",
            "max_price_prompt": "1.5",
            "max_price_completion": "3",
            "data_collection": "deny",
            "zdr": True,
        }
    )
    assert out["provider"] == {
        "sort": "price",
        "max_price": {"prompt": "1.5", "completion": "3"},
        "data_collection": "deny",
        "zdr": True,
    }


def test_a_routing_control_coexists_with_the_promoted_native_top_k() -> None:
    # The wrapper carries BOTH kinds of native field; routing policy projects to
    # `provider`, sampling to `extra_body`, and neither disturbs the other.
    out = _classify({"top_k": 40, "sort": "price"})
    assert out["extra_body"] == {"top_k": 40}
    assert out["provider"] == {"sort": "price"}


def test_one_malformed_control_rejects_the_whole_request() -> None:
    # Fail closed as a unit: a request that is partly invalid never dispatches its
    # valid half against a ceiling the caller did not get.
    assert _rejected({"sort": "price", "max_price_prompt": "-1"}) == {
        "provider_params.max_price_prompt": "malformed"
    }


def test_every_malformed_control_is_named_at_once() -> None:
    # The caller gets one 400 listing every offending path, not a guessing game.
    assert _rejected({"sort": "cheap", "zdr": "yes", "data_collection": "maybe"}) == {
        "provider_params.sort": "malformed",
        "provider_params.zdr": "malformed",
        "provider_params.data_collection": "malformed",
    }


# --- the routing control plane stays closed ----------------------------------


@pytest.mark.parametrize(
    "leaf",
    [
        "order",  # provider pinning/ordering — OME-703, deliberately deferred
        "only",
        "ignore",
        "allow_fallbacks",
        "quantizations",
        "require_parameters",  # gateway-owned strictness; not the caller's to set
        "max_price",  # the nested object itself is NOT an addressing form
        "sort_by",
        "zero_data_retention",
        "maxPrice",
        "data-collection",
    ],
)
def test_an_unreviewed_wrapper_leaf_stays_an_unknown_rejection(leaf: str) -> None:
    # INVARIANT: adding four controls widens the surface by exactly five leaves.
    # Everything else under the wrapper — including the upstream spellings and the
    # nested object the projection builds — fails closed with a NAMED path.
    assert _rejected({leaf: "x"}) == {f"provider_params.{leaf}": "unknown"}


def test_the_raw_provider_object_is_still_unruled() -> None:
    # The whole point of the feature: the caller expresses policy through reviewed
    # leaves, never by handing the gateway an OpenRouter `provider` object.
    with pytest.raises(UnsupportedParametersError) as exc:
        classify_and_project_chat_parameters(
            {**_PROMPT, "provider": {"sort": "price"}},
            rules=_rules(),
            auth_mode="api_key",
        )
    assert exc.value.rejected == {"provider": "unknown"}
    assert "provider" not in {rule.request_path for rule in _rules()}


@pytest.mark.parametrize("path", _PATHS)
def test_a_dotted_top_level_alias_of_a_control_fails_closed(path: str) -> None:
    # OME-704: the wrapper OBJECT is the only addressing form. A top-level key
    # spelled "provider_params.sort" must not be a second, unpublished channel into
    # the routing policy.
    with pytest.raises(UnsupportedParametersError) as exc:
        classify_and_project_chat_parameters(
            {**_PROMPT, path: "price"}, rules=_rules(), auth_mode="api_key"
        )
    assert exc.value.rejected == {path: "unknown"}


# --- the rules themselves -----------------------------------------------------


@pytest.mark.parametrize("path", _PATHS)
def test_every_routing_control_is_ruled_as_a_wrapped_native_field(path: str) -> None:
    rule = _rule_by_path()[path]
    assert rule.projection_kind == "provider_native"
    leaf = path.removeprefix("provider_params.")
    assert rule.provider_target == ".".join(_TARGETS[leaf])
    assert rule.applicable_auth_modes == ("api_key",)
    assert rule.parameter_schema is not None  # an unvalidatable rule is not enabled


@pytest.mark.parametrize("path", _PATHS)
def test_every_routing_control_is_keyed_into_the_global_cache(path: str) -> None:
    # SUPERSEDED (OME-305, was `..._bypasses_the_prompt_cache`): the response depends
    # on WHICH endpoint served it, and the resolved endpoint is a function of the whole
    # routing policy — so that policy has to be IN the key. It now is: the v2 key
    # hashes `prepared_request`, which OpenRouter's `global_cache_projection` fills by
    # calling the same `build_provider_policy` reconstruction dispatch uses. The
    # blocker this rule deferred to (OME-702) was absorbed into OME-305 and its
    # precondition is discharged.
    #
    # INVARIANT preserved from the superseded version: an answer produced under a
    # different ceiling or data policy is never served as if it satisfied this
    # request. Bypassing achieved that by never caching; keying achieves it by
    # landing on a different hash — see
    # test_two_requests_differing_only_in_one_control_never_cross_hit.
    rule = _rule_by_path()[path]
    assert rule.cache_behavior == "keyed"
    assert rule.output_affecting is True


def test_the_price_schemas_publish_the_exact_accepted_grammar() -> None:
    # The published schema IS the contract a client validates against before
    # sending, so it must be the same bound the gateway enforces.
    for path in ("provider_params.max_price_prompt", "provider_params.max_price_completion"):
        schema = _rule_by_path()[path].parameter_schema
        assert schema is not None
        assert schema.to_json_schema() == {
            "type": "string",
            "pattern": _DECIMAL_PATTERN,
            "maxLength": 64,
        }


def test_the_enum_and_boolean_schemas_are_bounded_as_published() -> None:
    by_path = _rule_by_path()
    assert by_path["provider_params.sort"].parameter_schema.to_json_schema() == {
        "type": "string",
        "enum": ["price"],
    }
    assert by_path["provider_params.data_collection"].parameter_schema.to_json_schema() == {
        "type": "string",
        "enum": ["allow", "deny"],
    }
    assert by_path["provider_params.zdr"].parameter_schema.to_json_schema() == {"type": "boolean"}


# --- the published contract ---------------------------------------------------


def _document_parameters(auth_mode: AuthType = "api_key") -> dict[str, Any]:
    # Mirrors routes/model_parameters.py: the SAME plugin hooks, the SAME composer.
    plugin = OpenRouterProviderPlugin()
    document = build_model_parameter_document(
        canonical_id=_MODEL,
        gateway_provider="openrouter",
        auth_mode=auth_mode,
        scope="account_connection",
        context_identity="acct:test|prof:1",
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=auth_mode),
        observations=plugin.chat_parameter_observations(model=_MODEL, auth_type=auth_mode),
        tools=plugin.chat_parameter_tools(model=_MODEL, auth_type=auth_mode),
        transport=plugin.chat_transport_capabilities(model=_MODEL, auth_type=auth_mode),
        freshness={"stale": False, "degraded": False},
    )
    return document["parameters"]


@pytest.mark.parametrize("path", _PATHS)
def test_the_detail_contract_publishes_every_control_as_enabled(path: str) -> None:
    entry = _document_parameters()[path]
    assert entry["gateway"]["status"] == "enabled"
    assert entry["gateway"]["projection"] == "provider_native"
    # SUPERSEDED (OME-305): was `"bypass"`. The PUBLISHED cache behaviour must equal
    # the rule's, and the rule is now keyed — a document still advertising `bypass`
    # would tell a client its routing controls are uncacheable when they are keyed.
    assert entry["gateway"]["cache_behavior"] == "keyed"
    assert entry["gateway"]["applicable_auth_modes"] == ["api_key"]
    # the PUBLISHED bound is the bound dispatch enforces — same schema object.
    assert entry["schema"] == _rule_by_path()[path].parameter_schema.to_json_schema()


@pytest.mark.parametrize("path", _PATHS)
def test_the_detail_contract_carries_routing_policy_provenance(path: str) -> None:
    # INVARIANT: an observation never ENABLES a field — but an enabled field must
    # still say where its evidence came from. Routing policy is reviewed local
    # evidence about the ROUTING API, not the sampling inventory and not a live
    # fetch, so it carries its own source label.
    provider_evidence = _document_parameters()[path]["provider"]
    assert provider_evidence["support"] == "supported"
    assert provider_evidence["source"] == "openrouter:routing-policy"


def test_the_detail_contract_never_publishes_a_bare_routing_leaf() -> None:
    # A native field is addressed at EXACTLY one path. If the observation literal
    # and the rule ever disagree about the wrapper, the contract would list the
    # field twice — once bare, once wrapped.
    params = _document_parameters()
    for leaf in _TARGETS:
        assert leaf not in params, leaf
    assert "provider" not in params


def test_the_models_summary_is_derived_from_the_same_rules() -> None:
    summary = set(inline_supported_parameters(_rules(), available_auth_modes=("api_key",)))
    assert set(_PATHS) <= summary
    # …and the excluded control plane is advertised nowhere.
    assert summary.isdisjoint({"provider", "plugins", "route", "models"})
    assert summary.isdisjoint({f"provider_params.{leaf}" for leaf in ("order", "only", "ignore")})
