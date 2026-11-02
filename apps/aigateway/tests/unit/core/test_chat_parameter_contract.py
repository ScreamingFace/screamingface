"""Phase 1 (OME-479): contract value types and rule algebra.

RED-first coverage for the frozen value objects and the pure derivations that
turn a provider-local rule set into (a) the conservative profile-independent
inline summary and (b) the overlaid detailed contract entries. No route or
provider dispatch is exercised here — this pins the algebra in isolation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aigateway.core.auth_types import AuthType
from aigateway.core.chat_parameters import (
    CacheBehavior,
    DuplicateParameterRuleError,
    InvalidParameterRuleError,
    ParameterContractEntry,
    ParameterProjectionRule,
    ParameterSchema,
    ProjectionKind,
    ProviderParameterObservation,
    ToolCapability,
    TransportCapability,
    compose_contract_entries,
    inline_supported_parameters,
    normalize_rules,
    stream_transport_capability,
    supported_tool_types,
)


def _rule(
    request_path: str,
    *,
    auth_modes: tuple[AuthType, ...] = ("api_key",),
    projection_kind: ProjectionKind = "direct",
    provider_target: str | None = None,
    cache_behavior: CacheBehavior = "bypass",
    output_affecting: bool = True,
    schema: ParameterSchema | None = None,
) -> ParameterProjectionRule:
    return ParameterProjectionRule(
        request_path=request_path,
        applicable_auth_modes=auth_modes,
        projection_kind=projection_kind,
        provider_target=provider_target,
        cache_behavior=cache_behavior,
        output_affecting=output_affecting,
        projection_revision="r1",
        schema=schema,
    )


# --- value-object invariants -------------------------------------------------


def test_rule_is_frozen_and_hashable() -> None:
    rule = _rule("temperature")
    with pytest.raises(ValidationError):
        rule.request_path = "top_p"  # type: ignore[misc]
    # INVARIANT: frozen + value-equal rules collapse in a set/dict key, which
    # deterministic dedup relies on. Pydantic regenerates __hash__ at runtime for
    # frozen=True, which the type checker cannot see (it statically treats any
    # __eq__-defining class as unhashable) — so the set literal is a known
    # false-positive here, not a real defect.
    assert {rule, _rule("temperature")} == {rule}  # type: ignore[reportUnhashable]


@pytest.mark.parametrize(
    "bad_path", ["", "  ", "temperature ", ".top_k", "provider_params.", "a..b"]
)
def test_invalid_request_path_fails(bad_path: str) -> None:
    with pytest.raises((ValidationError, InvalidParameterRuleError)):
        _rule(bad_path)


def test_empty_auth_modes_fail_closed() -> None:
    with pytest.raises((ValidationError, InvalidParameterRuleError)):
        _rule("temperature", auth_modes=())


@pytest.mark.parametrize("bad_mode", ["", "API_KEY", "session", "bearer"])
def test_unknown_auth_mode_fails_closed(bad_mode: str) -> None:
    with pytest.raises((ValidationError, InvalidParameterRuleError)):
        # deliberately off-contract auth mode: proves runtime fail-closed even
        # when a caller bypasses the AuthType literal (hence the type: ignore).
        _rule("temperature", auth_modes=(bad_mode,))  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["bogus", "SUPPORTED", "yes", ""])
def test_unknown_provider_support_enum_fails_closed(value: str) -> None:
    with pytest.raises(ValidationError):
        # off-contract enum value forced past the ProviderSupport literal.
        ProviderParameterObservation(request_path="temperature", support=value, source="s")  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["on", "ENABLED", "true", ""])
def test_unknown_gateway_status_enum_fails_closed(value: str) -> None:
    with pytest.raises(ValidationError):
        # off-contract enum value forced past the GatewayStatus literal.
        ToolCapability(tool_type="function", provider_support="supported", gateway_status=value)  # type: ignore[arg-type]


def test_output_affecting_rule_cannot_be_transport_only() -> None:
    with pytest.raises((ValidationError, InvalidParameterRuleError)):
        _rule("temperature", cache_behavior="transport_only", output_affecting=True)


def test_transport_only_allowed_for_non_output_affecting() -> None:
    rule = _rule("stream", cache_behavior="transport_only", output_affecting=False)
    assert rule.cache_behavior == "transport_only"


def test_provider_native_rule_requires_wrapper_path_and_target() -> None:
    # provider_native projection must originate under the provider_params wrapper
    with pytest.raises((ValidationError, InvalidParameterRuleError)):
        _rule("top_k", projection_kind="provider_native", provider_target="top_k")
    # and must name a concrete provider target
    with pytest.raises((ValidationError, InvalidParameterRuleError)):
        _rule("provider_params.top_k", projection_kind="provider_native", provider_target=None)
    ok = _rule("provider_params.top_k", projection_kind="provider_native", provider_target="top_k")
    assert ok.provider_target == "top_k"


# --- normalization / determinism --------------------------------------------


def test_normalize_rules_is_deterministic_regardless_of_input_order() -> None:
    a = _rule("temperature")
    b = _rule("provider_params.top_k", projection_kind="provider_native", provider_target="top_k")
    c = _rule("max_tokens")
    forward = normalize_rules([a, b, c])
    shuffled = normalize_rules([c, a, b])
    assert forward == shuffled
    assert [r.request_path for r in forward] == sorted(r.request_path for r in (a, b, c))


def test_duplicate_request_path_fails() -> None:
    with pytest.raises(DuplicateParameterRuleError):
        normalize_rules([_rule("temperature"), _rule("temperature", auth_modes=("oauth",))])


def test_duplicate_provider_target_across_distinct_paths_rejected() -> None:
    # INVARIANT (OME-597): one provider target == at most one rule per rule set. Two DISTINCT
    # provider_params.* request paths that both write the same wire target must fail at
    # construction, not pass silently and collide later as a caller-facing duplicate_channel 400.
    a = _rule("provider_params.alpha", projection_kind="provider_native", provider_target="top_k")
    b = _rule("provider_params.beta", projection_kind="provider_native", provider_target="top_k")
    with pytest.raises(DuplicateParameterRuleError):
        normalize_rules([a, b])


def test_direct_path_colliding_with_native_target_rejected() -> None:
    # INVARIANT (OME-597): a direct rule's target IS its request_path (provider_target is None).
    # If a provider_native rule targets that same wire field, the two race to write it — reject
    # at construction. request_paths differ ("top_k" vs "provider_params.top_k"), so only the
    # target check catches this; the request_path check alone would let it through.
    direct = _rule("top_k")  # direct → target == request_path == "top_k"
    native = _rule(
        "provider_params.top_k", projection_kind="provider_native", provider_target="top_k"
    )
    with pytest.raises(DuplicateParameterRuleError):
        normalize_rules([direct, native])


# --- conservative inline summary (profile-independent intersection) ----------


def test_single_auth_mode_provider_exposes_its_effective_set_directly() -> None:
    rules = normalize_rules([_rule("temperature"), _rule("max_tokens")])
    summary = inline_supported_parameters(rules, available_auth_modes=("oauth",))
    # A rule applicable only to api_key is invisible to an oauth-only provider.
    only_api = normalize_rules([_rule("reasoning", auth_modes=("api_key",))])
    assert summary == ()  # rules declared api_key are not applicable to oauth-only
    assert inline_supported_parameters(
        normalize_rules([_rule("temperature", auth_modes=("oauth",))]),
        available_auth_modes=("oauth",),
    ) == ("temperature",)
    assert only_api  # constructed fine, just not applicable here


def test_summary_is_intersection_across_all_available_auth_modes() -> None:
    rules = normalize_rules(
        [
            _rule("temperature", auth_modes=("api_key", "oauth")),  # both → in summary
            _rule("reasoning", auth_modes=("api_key",)),  # api_key only → excluded
            _rule("max_tokens", auth_modes=("oauth",)),  # oauth only → excluded
        ]
    )
    summary = inline_supported_parameters(rules, available_auth_modes=("api_key", "oauth"))
    assert summary == ("temperature",)


def test_summary_is_sorted_and_deduplicated() -> None:
    rules = normalize_rules([_rule("top_p"), _rule("frequency_penalty"), _rule("temperature")])
    summary = inline_supported_parameters(rules, available_auth_modes=("api_key",))
    assert summary == ("frequency_penalty", "temperature", "top_p")
    assert list(summary) == sorted(summary)


def test_no_auth_mode_provider_advertises_nothing() -> None:
    # WHY (conservative limit — OME-580): with NO auth mode available, no field can be
    # proven under "every available mode", so the summary must be EMPTY — never the
    # vacuous "∅ ⊆ anything is true → advertise all" result, which is the exact
    # opposite of conservative. Guards the latent trap where the first rule added to a
    # no-auth provider would otherwise be over-advertised on /v1/models.
    rules = normalize_rules([_rule("temperature"), _rule("max_tokens")])
    assert rules  # guard: the fixture actually carries rules that could be over-advertised
    assert inline_supported_parameters(rules, available_auth_modes=()) == ()


# --- tools consistency -------------------------------------------------------


def test_supported_tool_types_reports_only_enabled_sorted() -> None:
    tools = (
        ToolCapability(
            tool_type="function", provider_support="supported", gateway_status="enabled"
        ),
        ToolCapability(
            tool_type="web_search", provider_support="supported", gateway_status="disabled"
        ),
    )
    assert supported_tool_types(tools) == ("function",)


def test_supported_tool_types_empty_when_none_enabled() -> None:
    tools = (
        ToolCapability(
            tool_type="function", provider_support="unsupported", gateway_status="disabled"
        ),
    )
    assert supported_tool_types(tools) == ()


# --- detailed contract composition (overlay) --------------------------------


def test_observed_but_unruled_field_is_visible_disabled_with_reason() -> None:
    rules = normalize_rules([_rule("temperature")])
    observations = (
        ProviderParameterObservation(
            request_path="provider_params.new_option",
            support="supported",
            source="openrouter_model_catalog",
        ),
    )
    entries = compose_contract_entries(rules, observations, auth_mode="api_key")
    by_path = {e.request_path: e for e in entries}
    assert by_path["temperature"].gateway_status == "enabled"
    disabled = by_path["provider_params.new_option"]
    assert disabled.gateway_status == "disabled"
    assert disabled.gateway_reason == "projection_not_implemented"
    assert disabled.provider_support == "supported"


def test_enabled_entry_requires_rule_applicable_to_requested_auth_mode() -> None:
    # rule applies only to api_key; requesting oauth must NOT enable it
    rules = normalize_rules([_rule("reasoning", auth_modes=("api_key",))])
    observations = (
        ProviderParameterObservation(
            request_path="reasoning", support="supported", source="labelled_static"
        ),
    )
    api = {
        e.request_path: e
        for e in compose_contract_entries(rules, observations, auth_mode="api_key")
    }
    oauth = {
        e.request_path: e for e in compose_contract_entries(rules, observations, auth_mode="oauth")
    }
    assert api["reasoning"].gateway_status == "enabled"
    assert oauth["reasoning"].gateway_status == "disabled"


def test_enabled_rule_without_observation_reports_unknown_provider_support() -> None:
    rules = normalize_rules([_rule("temperature")])
    entries = compose_contract_entries(rules, (), auth_mode="api_key")
    entry = entries[0]
    assert entry.request_path == "temperature"
    assert entry.gateway_status == "enabled"
    assert entry.provider_support == "unknown"
    # Honest about the ABSENCE too: no observation means no source to cite. This pair
    # is the provider-agnostic home of the property (OME-646 removed the OpenRouter
    # instance of it when its last ruled-but-unobserved field was withdrawn).
    assert entry.provider_source == "none"


def test_inline_summary_entries_are_enabled_in_the_detailed_contract() -> None:
    # The consistency invariant: every inline-summary path is enabled in every
    # applicable detailed contract, from the SAME rule source.
    rules = normalize_rules(
        [
            _rule("temperature", auth_modes=("api_key", "oauth")),
            _rule("max_tokens", auth_modes=("api_key", "oauth")),
        ]
    )
    summary = set(inline_supported_parameters(rules, available_auth_modes=("api_key", "oauth")))
    for mode in ("api_key", "oauth"):
        entries = {e.request_path: e for e in compose_contract_entries(rules, (), auth_mode=mode)}
        for path in summary:
            assert entries[path].gateway_status == "enabled"


def test_contract_entry_serializes_to_locked_detail_shape() -> None:
    rules = normalize_rules(
        [
            _rule(
                "temperature",
                schema=ParameterSchema(type="number", minimum=0, maximum=2),
                cache_behavior="bypass",
            )
        ]
    )
    observations = (
        ProviderParameterObservation(
            request_path="temperature",
            support="supported",
            source="openrouter_model_catalog",
        ),
    )
    entry = compose_contract_entries(rules, observations, auth_mode="api_key")[0]
    assert isinstance(entry, ParameterContractEntry)
    detail = entry.to_detail_dict()
    assert detail["request_path"] == "temperature"
    assert detail["schema"] == {"type": "number", "minimum": 0, "maximum": 2}
    assert detail["provider"] == {
        "support": "supported",
        "source": "openrouter_model_catalog",
        "stale": False,
        # OME-647: lifecycle joins the evidence block. Still an EXACT-equality lock —
        # the key set is pinned, not merely sampled. `None` is the third state: this
        # observation's source models support but not deprecation, so nothing was
        # said, which is distinct from a source declaring the field current.
        "deprecated": None,
    }
    assert detail["gateway"] == {
        "status": "enabled",
        "projection": "direct",
        "cache_behavior": "bypass",
        # OME-649: auth applicability joins the POLICY block. Still an EXACT-equality
        # lock — the lock catching a newly published key is the lock doing its job.
        "applicable_auth_modes": ["api_key"],
    }


def test_transport_capability_serializes_with_reason() -> None:
    cap = TransportCapability(
        name="stream",
        provider_support="supported",
        gateway_status="disabled",
        reason="gateway_transport_not_implemented",
    )
    assert cap.to_dict() == {
        "provider_support": "supported",
        "gateway_status": "disabled",
        "reason": "gateway_transport_not_implemented",
    }


# --- transport capabilities (OME-601) ----------------------------------------


def test_stream_transport_capability_reports_an_enabled_gateway() -> None:
    # The gateway's own streaming policy, published so a client can read it
    # instead of discovering it from a 400.
    cap = stream_transport_capability(gateway_enabled=True)
    assert cap.name == "stream"
    assert cap.gateway_status == "enabled"
    # INVARIANT: the flag is GATEWAY policy, not provider evidence — the core has
    # observed nothing about the upstream, so it claims nothing about it.
    assert cap.provider_support == "unknown"
    assert cap.reason is None
    assert "reason" not in cap.to_dict()


def test_stream_transport_capability_reports_a_disabled_gateway_with_a_reason() -> None:
    cap = stream_transport_capability(gateway_enabled=False)
    assert cap.name == "stream"
    assert cap.gateway_status == "disabled"
    assert cap.provider_support == "unknown"
    # A STABLE machine-readable code, sibling to the parameters section's
    # ``projection_not_implemented`` — clients branch on it, so it is contract.
    assert cap.reason == "gateway_transport_not_implemented"
    assert cap.to_dict()["reason"] == "gateway_transport_not_implemented"


def test_the_stream_transport_name_is_the_field_callers_actually_send() -> None:
    # WHY it must be exactly "stream": that is the request field the dispatch gate
    # inspects, so any other spelling would publish a control nobody can act on.
    assert stream_transport_capability(gateway_enabled=True).name == "stream"
