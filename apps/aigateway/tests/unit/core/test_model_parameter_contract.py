"""Phase 3 (OME-479): detailed /v1/model-parameters document composition.

RED-first for the PURE application-layer composer that overlays a plugin's OWN
observations + gateway rules + tools + transport into the locked v1 detailed
document, and derives the opaque, non-secret ``contract_id`` / ``context.revision``
digests. No route, no network, no clock — the composer is deterministic given its
inputs, so ``freshness`` and the opaque ``context_identity`` token are passed IN.
"""

from __future__ import annotations

from typing import Any

from aigateway.core.auth_types import AuthType
from aigateway.core.chat_parameters import (
    ParameterProjectionRule,
    ParameterSchema,
    ProviderParameterObservation,
    ToolCapability,
    TransportCapability,
    inline_supported_parameters,
    normalize_rules,
)
from aigateway.core.model_parameter_contract import (
    SCHEMA_VERSION,
    build_model_parameter_document,
    upstream_model_id,
)

_LOCAL_FRESHNESS: dict[str, Any] = {"stale": False, "degraded": False}


def _rule(
    request_path: str,
    *,
    auth_modes: tuple[AuthType, ...] = ("api_key",),
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


def _doc(
    *,
    canonical_id: str = "openrouter/google/gemini-3.6-flash",
    gateway_provider: str = "openrouter",
    auth_mode: AuthType = "api_key",
    scope: str = "account_connection",
    context_identity: str = "acct:a1|prof:p1:authenticated:-",
    rules: tuple[ParameterProjectionRule, ...] = (),
    observations: tuple[ProviderParameterObservation, ...] = (),
    tools: tuple[ToolCapability, ...] = (),
    transport: tuple[TransportCapability, ...] = (),
) -> dict[str, Any]:
    return build_model_parameter_document(
        canonical_id=canonical_id,
        gateway_provider=gateway_provider,
        auth_mode=auth_mode,
        scope=scope,
        context_identity=context_identity,
        rules=rules,
        observations=observations,
        tools=tools,
        transport=transport,
        freshness=dict(_LOCAL_FRESHNESS),
    )


# --- upstream id -------------------------------------------------------------


def test_upstream_id_strips_only_the_gateway_prefix() -> None:
    # the model author id is the canonical id minus its owning-provider segment,
    # NEVER derived from a LiteLLM transport prefix (plan 4.1).
    assert upstream_model_id("openrouter/google/gemini-3.6-flash") == "google/gemini-3.6-flash"
    assert upstream_model_id("ollama/llama3:8b") == "llama3:8b"
    assert upstream_model_id("anthropic/claude-opus-4-8") == "claude-opus-4-8"


# --- locked v1 envelope ------------------------------------------------------


def test_document_emits_locked_v1_envelope() -> None:
    doc = _doc()
    assert doc["schema_version"] == SCHEMA_VERSION == 1
    assert doc["contract_id"].startswith("pc_")
    assert doc["model"] == {
        "id": "openrouter/google/gemini-3.6-flash",
        "gateway_provider": "openrouter",
        "upstream_id": "google/gemini-3.6-flash",
    }
    assert doc["context"]["scope"] == "account_connection"
    assert doc["context"]["auth_mode"] == "api_key"
    assert doc["context"]["revision"].startswith("ctx_")
    assert doc["freshness"] == {"stale": False, "degraded": False}
    for section in ("parameters", "tools", "transport"):
        assert isinstance(doc[section], dict)


def test_parameters_are_keyed_by_path_and_use_the_detail_shape() -> None:
    doc = _doc(
        rules=(_rule("temperature", schema=ParameterSchema(type="number", minimum=0, maximum=2)),),
        observations=(
            ProviderParameterObservation(
                request_path="temperature", support="supported", source="labelled_static"
            ),
            ProviderParameterObservation(
                request_path="provider_params.new_option",
                support="supported",
                source="labelled_static",
            ),
        ),
    )
    params = doc["parameters"]
    assert params["temperature"]["request_path"] == "temperature"
    assert params["temperature"]["schema"] == {"type": "number", "minimum": 0, "maximum": 2}
    assert params["temperature"]["gateway"] == {
        "status": "enabled",
        "projection": "direct",
        "cache_behavior": "bypass",
        # OME-649: auth applicability joins the published policy block.
        "applicable_auth_modes": ["api_key"],
    }
    # observed-but-unruled field is VISIBLE but never dispatchable.
    disabled = params["provider_params.new_option"]
    assert disabled["gateway"]["status"] == "disabled"
    assert disabled["gateway"]["reason"] == "projection_not_implemented"


def test_tools_and_transport_serialize_with_status() -> None:
    doc = _doc(
        tools=(
            ToolCapability(
                tool_type="function", provider_support="supported", gateway_status="enabled"
            ),
            ToolCapability(
                tool_type="web_search", provider_support="supported", gateway_status="disabled"
            ),
        ),
        transport=(
            TransportCapability(
                name="stream",
                provider_support="supported",
                gateway_status="disabled",
                reason="gateway_transport_not_implemented",
            ),
        ),
    )
    assert doc["tools"]["function"] == {
        "provider_support": "supported",
        "gateway_status": "enabled",
    }
    # detail reports every tool with its status (unlike the enabled-only summary).
    assert doc["tools"]["web_search"]["gateway_status"] == "disabled"
    assert doc["transport"]["stream"] == {
        "provider_support": "supported",
        "gateway_status": "disabled",
        "reason": "gateway_transport_not_implemented",
    }


# --- opaque, deterministic, revision-sensitive digests -----------------------


def test_digests_are_deterministic_for_identical_inputs() -> None:
    a = _doc(rules=(_rule("temperature"),))
    b = _doc(rules=(_rule("temperature"),))
    assert a["contract_id"] == b["contract_id"]
    assert a["context"]["revision"] == b["context"]["revision"]


def test_both_digests_change_when_any_relevant_input_changes() -> None:
    base = _doc(rules=(_rule("temperature"),))
    base_ids = (base["contract_id"], base["context"]["revision"])

    mutations = [
        _doc(canonical_id="openrouter/x/other", rules=(_rule("temperature"),)),  # model
        _doc(auth_mode="oauth", rules=(_rule("temperature", auth_modes=("oauth",)),)),  # auth mode
        _doc(  # context identity (selected profile/connection generation)
            context_identity="acct:a1|prof:p1:authenticated:CHANGED",
            rules=(_rule("temperature"),),
        ),
        _doc(rules=(_rule("temperature"), _rule("max_tokens"))),  # gateway projection revision
        _doc(  # provider evidence revision
            rules=(_rule("temperature"),),
            observations=(
                ProviderParameterObservation(
                    request_path="temperature", support="supported", source="labelled_static"
                ),
            ),
        ),
    ]
    for mutated in mutations:
        assert (mutated["contract_id"], mutated["context"]["revision"]) != base_ids
    # domain separation: the two ids are never equal to each other.
    assert base["contract_id"] != base["context"]["revision"]


def test_digests_never_expose_their_secret_or_identity_inputs() -> None:
    secretish_identity = "acct:11111111-2222-3333-4444-555555555555|prof:super-secret-token"
    doc = _doc(context_identity=secretish_identity, rules=(_rule("temperature"),))
    blob = doc["contract_id"] + doc["context"]["revision"]
    assert "555555555555" not in blob
    assert "super-secret-token" not in blob
    assert secretish_identity not in blob


# --- single-source consistency (summary ⊆ enabled detail) --------------------


def test_inline_summary_entries_are_enabled_in_the_document() -> None:
    # The cross-projection invariant, at the document level: every path the
    # profile-independent summary advertises is ENABLED in the applicable
    # detailed contract, because BOTH read the same rule source.
    rules = normalize_rules(
        (
            _rule("temperature", auth_modes=("api_key", "oauth")),
            _rule("max_tokens", auth_modes=("api_key", "oauth")),
        )
    )
    summary = inline_supported_parameters(rules, available_auth_modes=("api_key", "oauth"))
    assert summary  # guard: the fixture actually advertises something
    doc = _doc(auth_mode="api_key", rules=rules)
    for path in summary:
        assert doc["parameters"][path]["gateway"]["status"] == "enabled"


def test_contract_id_changes_when_only_a_rule_schema_changes() -> None:
    # LIVE facet (OME-579): the contract identity must move when a rule's
    # VALIDATION SCHEMA changes and nothing else — otherwise narrowing a bound
    # (e.g. Anthropic temperature maximum 2 -> 1) leaves a cached contract
    # byte-identical and stale, advertising the wrong range to clients.
    wide = _doc(
        rules=(_rule("temperature", schema=ParameterSchema(type="number", minimum=0, maximum=2)),)
    )
    narrow = _doc(
        rules=(_rule("temperature", schema=ParameterSchema(type="number", minimum=0, maximum=1)),)
    )
    assert wide["contract_id"] != narrow["contract_id"]
    assert wide["context"]["revision"] != narrow["context"]["revision"]


# --- identity completeness: EVERY published section moves the digests --------
#
# INVARIANT under test (OME-600): the digests are the cache key for the SERVED
# document, so any change a client can observe must move them. Omitting a
# published field fails DANGEROUSLY (a stale document under a frozen key);
# including one that did not need it fails SAFELY (extra churn). Hence: every
# section is covered, and the single exclusion is asserted deliberately below.


def _ids(doc: dict[str, Any]) -> tuple[str, str]:
    return (doc["contract_id"], doc["context"]["revision"])


def _tool(tool_type: str, *, status: str = "enabled") -> ToolCapability:
    return ToolCapability(
        tool_type=tool_type,
        provider_support="supported",
        gateway_status=status,  # type: ignore[arg-type]
    )


def _obs(
    request_path: str,
    *,
    schema: ParameterSchema | None = None,
    support: str = "supported",
) -> ProviderParameterObservation:
    return ProviderParameterObservation(
        request_path=request_path,
        support=support,  # type: ignore[arg-type]
        source="labelled_static",
        schema=schema,
    )


def test_digests_move_when_a_tool_is_enabled_or_disabled() -> None:
    # A tool flipping status is a CONTRACT change: a client that cached on the id
    # would keep offering a tool the gateway no longer dispatches.
    enabled = _doc(tools=(_tool("function"),))
    disabled = _doc(tools=(_tool("function", status="disabled"),))
    assert _ids(enabled) != _ids(disabled)
    # guard: the mutation really is visible in the served body.
    assert enabled["tools"] != disabled["tools"]


def test_digests_move_when_a_tool_type_is_added() -> None:
    one = _doc(tools=(_tool("function"),))
    two = _doc(tools=(_tool("function"), _tool("web_search")))
    assert _ids(one) != _ids(two)


def test_digests_move_when_a_transport_capability_changes_status() -> None:
    off = _doc(
        transport=(
            TransportCapability(
                name="stream", provider_support="supported", gateway_status="disabled"
            ),
        )
    )
    on = _doc(
        transport=(
            TransportCapability(
                name="stream", provider_support="supported", gateway_status="enabled"
            ),
        )
    )
    assert _ids(off) != _ids(on)


def test_digests_move_when_only_a_transport_reason_changes() -> None:
    # ``reason`` is published only when non-None, so it is the field most likely
    # to be missed by a hash built from a fixed field list rather than the
    # serialized section.
    def _with(reason: str) -> dict[str, Any]:
        return _doc(
            transport=(
                TransportCapability(
                    name="stream",
                    provider_support="supported",
                    gateway_status="disabled",
                    reason=reason,
                ),
            )
        )

    first = _with("gateway_transport_not_implemented")
    second = _with("provider_transport_unavailable")
    assert first["transport"]["stream"]["reason"] != second["transport"]["stream"]["reason"]
    assert _ids(first) != _ids(second)


def test_digests_move_when_a_published_field_merely_APPEARS() -> None:
    # The structural claim behind digesting the SERIALIZED section: a key that is
    # only sometimes published still moves the identity when it shows up. This
    # pins the design — rewriting the section digest as a hand-listed field set
    # would pass every other test here and fail this one.
    def _with(reason: str | None) -> dict[str, Any]:
        return _doc(
            transport=(
                TransportCapability(
                    name="stream",
                    provider_support="supported",
                    gateway_status="disabled",
                    reason=reason,
                ),
            )
        )

    absent = _with(None)
    present = _with("gateway_transport_not_implemented")
    assert "reason" not in absent["transport"]["stream"]
    assert "reason" in present["transport"]["stream"]
    assert _ids(absent) != _ids(present)


def test_digests_move_when_only_a_disabled_entrys_observation_schema_changes() -> None:
    # An observed-but-unruled path publishes the OBSERVATION's schema directly,
    # so a change there is caller-visible and must move the identity.
    wide = _doc(observations=(_obs("provider_params.x", schema=ParameterSchema(type="integer")),))
    narrow = _doc(
        observations=(_obs("provider_params.x", schema=ParameterSchema(type="integer", maximum=8)),)
    )
    assert (
        wide["parameters"]["provider_params.x"]["schema"]
        != (narrow["parameters"]["provider_params.x"]["schema"])
    )
    assert _ids(wide) != _ids(narrow)


def test_digests_move_when_an_enabled_entry_falls_back_to_the_observation_schema() -> None:
    # The second publication route: an ENABLED rule carrying no schema of its own
    # serves the observation's schema instead.
    def _with(schema: ParameterSchema) -> dict[str, Any]:
        return _doc(
            rules=(_rule("temperature"),),
            observations=(_obs("temperature", schema=schema),),
        )

    wide = _with(ParameterSchema(type="number", minimum=0, maximum=2))
    narrow = _with(ParameterSchema(type="number", minimum=0, maximum=1))
    assert wide["parameters"]["temperature"]["gateway"]["status"] == "enabled"
    assert wide["parameters"]["temperature"]["schema"]["maximum"] == 2
    assert _ids(wide) != _ids(narrow)


def test_digests_move_when_only_the_gateway_provider_changes() -> None:
    # Redundant with the model id at today's only call site, but the composer
    # takes them as INDEPENDENT arguments and enforces no relationship — so the
    # published value is hashed rather than assumed.
    a = _doc(gateway_provider="openrouter")
    b = _doc(gateway_provider="relabelled")
    assert a["model"]["gateway_provider"] != b["model"]["gateway_provider"]
    assert _ids(a) != _ids(b)


def test_digests_move_when_only_the_scope_changes() -> None:
    # WHY: ``context.scope`` is published AND hashed, so renaming the scope literal
    # (OME-1138 close-out: ``account_connection``) rotates ``contract_id`` and
    # ``context.revision`` once. That rotation is the stated, owner-accepted cost of
    # the rename; a scope left out of the digest would serve a renamed context under
    # a frozen id.
    a = _doc(scope="account_connection")
    b = _doc(scope="relabelled")
    assert a["context"]["scope"] != b["context"]["scope"]
    # WHY: each id is checked on its own; a pair comparison passes if only one moved.
    assert a["contract_id"] != b["contract_id"]
    assert a["context"]["revision"] != b["context"]["revision"]


def test_freshness_is_deliberately_excluded_from_the_identity() -> None:
    # WHY the one exclusion: freshness is TIME-VARYING. Folding it in would move
    # the id on essentially every request, making it useless as a cache key. The
    # body genuinely differs — so this test would catch an accidental inclusion,
    # it is not vacuously true.
    def _with(freshness: dict[str, Any]) -> dict[str, Any]:
        return build_model_parameter_document(
            canonical_id="openrouter/google/gemini-3.6-flash",
            gateway_provider="openrouter",
            auth_mode="api_key",
            scope="account_connection",
            context_identity="acct:a1|prof:p1:authenticated:-",
            rules=(_rule("temperature"),),
            observations=(),
            tools=(),
            transport=(),
            freshness=freshness,
        )

    fresh = _with({"stale": False, "degraded": False})
    stale = _with({"stale": True, "degraded": True})
    assert fresh["freshness"] != stale["freshness"]
    assert _ids(fresh) == _ids(stale)


def test_every_published_section_is_classified_as_covered_or_excluded() -> None:
    # TRIPWIRE: a new top-level section cannot be added to the document without
    # someone deciding whether it belongs in the identity. Failing here is the
    # prompt to make that decision — never to widen the set without one.
    digest_covered = {"schema_version", "model", "context", "parameters", "tools", "transport"}
    deliberately_excluded = {"freshness"}
    identity_itself = {"contract_id"}
    doc = _doc(
        rules=(_rule("temperature"),),
        observations=(_obs("temperature"),),
        tools=(_tool("function"),),
        transport=(
            TransportCapability(
                name="stream", provider_support="supported", gateway_status="disabled"
            ),
        ),
    )
    assert set(doc) == digest_covered | deliberately_excluded | identity_itself
