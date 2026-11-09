"""OME-305 U1 — RED contract for the global v2 request fingerprint.

FEATURE: one global exact-request cache shared by every hosted user. The key is
the complete explicit output-affecting model call plus a PURE provider
projection — and nothing else. Account, profile, user, auth mode, credential and
BYOK identity are structurally absent, so the same explicit call from two
different callers produces one key.

STORY: as a benchmark operator, I send the same model call from two accounts and
the second one is answered from the first one's stored response, without a second
provider dispatch and without touching the second caller's credential.

INVARIANT under test: the key is built from the HARDENED CALLER-VISIBLE request
before any mutable provider preparation, profile default, auth-mode resolution or
credential access. Fabricated rule sets and a fabricated projection only — no
provider names, no route, no I/O — so the mechanism stays provider-agnostic.

INVARIANT under test: fail safe. Anything that cannot be represented exactly
(unknown parameter, declared bypass, malformed value, non-finite number,
unserializable value, unrecognized provider-prepared member) yields a bounded
``CacheBypass``, never a wrong hit and never an exception on the request path.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any

import pytest

from aigateway.core.auth_types import AuthMode
from aigateway.core.chat_parameters import (
    GATEWAY_OWNED_FIELDS,
    CacheBehavior,
    ParameterProjectionRule,
    ParameterSchema,
)
from aigateway.core.parameter_projection import WRAPPER_KEY
from aigateway.core.request_cache.global_keys import (
    BYPASS_DECLARED,
    EXCLUDED_TRANSPORT_FIELDS,
    PRESENCE_BYPASS_REASONS,
    PROMPT_FIELDS,
    TRUTHY_BYPASS_REASONS,
    CacheBypass,
    GlobalCacheKeyResult,
    GlobalChatCacheKey,
    build_global_cache_key,
    build_global_cache_key_dto,
    canonical_key_material,
)

_AUTH: tuple[AuthMode, ...] = ("api_key",)
_REVISION = "rule-r1"
_CONTRACT_REVISION = "pc-1"
_ADAPTER_REVISION = "pa-1"

_NUMBER = ParameterSchema(type="number", minimum=0, maximum=2)
_COUNT = ParameterSchema(type="integer", minimum=1, maximum=100)
_STRING = ParameterSchema(type="string", enum=("a", "b"))
# A decimal-string schema, so the fabricated provider below has something real to
# normalize: two spellings of one number must be ONE upstream request.
_DECIMAL = ParameterSchema(type="string", pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_FLAG = ParameterSchema(type="boolean")


def _direct(
    path: str,
    *,
    cache_behavior: CacheBehavior = "keyed",
    output_affecting: bool = True,
    schema: ParameterSchema | None = _NUMBER,
    revision: str = _REVISION,
) -> ParameterProjectionRule:
    return ParameterProjectionRule(
        request_path=path,
        applicable_auth_modes=_AUTH,
        projection_kind="direct",
        cache_behavior=cache_behavior,
        output_affecting=output_affecting,
        projection_revision=revision,
        schema=schema,
    )


def _native(
    leaf: str,
    target: str,
    *,
    cache_behavior: CacheBehavior = "keyed",
    schema: ParameterSchema | None = _COUNT,
) -> ParameterProjectionRule:
    return ParameterProjectionRule(
        request_path=f"provider_params.{leaf}",
        applicable_auth_modes=_AUTH,
        projection_kind="provider_native",
        provider_target=target,
        cache_behavior=cache_behavior,
        projection_revision=_REVISION,
        schema=schema,
    )


_RULES = (
    _direct("temperature"),
    _direct("top_p"),
    _direct("legacy_only", cache_behavior="bypass"),
    _direct("trace_label", cache_behavior="transport_only", output_affecting=False, schema=_STRING),
    _native("top_k", "extra_body.top_k"),
    _native("ceiling", "extra_body.ceiling", schema=_DECIMAL),
    _native("flag", "extra_body.flag", schema=_FLAG),
)

_PROVIDER = "fake"
_MODEL = "fake/m"
_MESSAGES = [{"role": "user", "content": "hi"}]


def _reconstructed(wrapper: Any) -> dict[str, Any]:
    """What this fabricated provider would actually send for its native controls.

    Models a real boundary rather than a passthrough, because that is what makes
    the native-parameter contract non-trivial: the value is RECONSTRUCTED into the
    location the rule targets, CANONICALIZED on the way, and OMITTED when the
    caller's value means exactly what absence means upstream. A provider that only
    copied values would prove nothing about either equivalence.
    """
    out: dict[str, Any] = {}
    if "top_k" in wrapper:
        out["top_k"] = wrapper["top_k"]
    if "ceiling" in wrapper:
        text = str(wrapper["ceiling"])
        out["ceiling"] = text[:-2] if text.endswith(".0") else text
    if wrapper.get("flag") is True:
        out["flag"] = True
    return out


def _projection(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
    """A pure, deterministic stand-in for a provider's own projection."""
    model = body["model"]
    prepared: dict[str, Any] = {"policy": {"require_parameters": True}}
    wrapper = body.get(WRAPPER_KEY)
    if isinstance(wrapper, dict):
        # INVARIANT a real provider must also keep: the surface its native rules
        # project into is described whenever the caller addresses it, even if every
        # value was deliberately omitted. Otherwise the key builder cannot tell a
        # deliberate omission from an undescribed field, and refuses to key it.
        prepared["extra_body"] = _reconstructed(wrapper)
    return {
        "resolved_model": model.split("/", 1)[1],
        "provider_adapter_revision": _ADAPTER_REVISION,
        "prepared": prepared,
    }


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"model": _MODEL, "messages": [dict(m) for m in _MESSAGES]}
    body.update(overrides)
    return body


def _build(
    body: dict[str, Any] | None = None,
    *,
    provider: str = _PROVIDER,
    rules: tuple[ParameterProjectionRule, ...] = _RULES,
    projection: Any = _projection,
    provider_auth_modes: tuple[str, ...] = _AUTH,
    parameter_contract_revision: str = _CONTRACT_REVISION,
) -> GlobalCacheKeyResult | CacheBypass:
    return build_global_cache_key(
        provider=provider,
        body=_body() if body is None else body,
        rules=rules,
        projection=projection,
        provider_auth_modes=provider_auth_modes,
        parameter_contract_revision=parameter_contract_revision,
    )


def _hash(body: dict[str, Any] | None = None, **kwargs: Any) -> str:
    built = _build(body, **kwargs)
    assert isinstance(built, GlobalCacheKeyResult), built
    return built.key_hash


def _reason(body: dict[str, Any] | None = None, **kwargs: Any) -> str:
    built = _build(body, **kwargs)
    assert isinstance(built, CacheBypass), built
    return built.reason


# --- the key is structurally identity-free ------------------------------------


def test_the_builder_accepts_no_identity_profile_or_credential_input() -> None:
    """INVARIANT (plan §10): identity cannot enter the v2 key, so the builder has
    nowhere to put it. Proven structurally rather than by a value assertion — a
    later parameter named ``account_id`` would fail here even if no test passed
    one.

    ``provider_auth_modes`` is the one parameter that mentions auth, and it is
    deliberately PROVIDER METADATA — which modes this provider offers at all, not
    which one this caller resolved to. That distinction is the whole reason the
    mode-restriction guard can live inside the pure stage: the same value is passed
    for every caller of a given provider, so it cannot partition the key by identity.
    """
    parameters = set(inspect.signature(build_global_cache_key).parameters)
    assert parameters == {
        "provider",
        "body",
        "rules",
        "projection",
        "provider_auth_modes",
        "parameter_contract_revision",
    }


def test_the_provider_projection_port_receives_only_the_request_body() -> None:
    # Plan §2.3: the pure projection never receives CurrentAccount, identity
    # headers, account/profile ids, auth mode, or credentials.
    from aigateway.core.plugin_base import ProviderPluginBase

    parameters = list(inspect.signature(ProviderPluginBase.global_cache_projection).parameters)
    assert parameters == ["self", "body"]


def test_the_same_explicit_request_yields_one_key() -> None:
    assert _hash() == _hash()


def test_the_canonical_dto_has_exactly_the_closed_member_set() -> None:
    dto = build_global_cache_key_dto(
        provider=_PROVIDER,
        body=_body(),
        rules=_RULES,
        projection=_projection,
        provider_auth_modes=_AUTH,
        parameter_contract_revision=_CONTRACT_REVISION,
    )
    assert isinstance(dto, GlobalChatCacheKey), dto
    assert set(json.loads(canonical_key_material(dto))) == {
        "schema",
        "operation",
        "provider",
        "requested_model",
        "resolved_model",
        "messages",
        "system",
        "keyed_parameters",
        "prepared_request",
        "parameter_contract_revision",
        "provider_adapter_revision",
    }


def test_the_mvp_has_no_variant_dimension() -> None:
    # Plan §8 #19 / requirements §3.5: an exact request has ONE global response.
    dto = build_global_cache_key_dto(
        provider=_PROVIDER,
        body=_body(),
        rules=_RULES,
        projection=_projection,
        provider_auth_modes=_AUTH,
        parameter_contract_revision=_CONTRACT_REVISION,
    )
    assert isinstance(dto, GlobalChatCacheKey)
    assert "variant" not in canonical_key_material(dto)
    with pytest.raises(TypeError):
        GlobalChatCacheKey(**{**dto.__dict__, "variant": "sample-0"})  # type: ignore[arg-type]


def test_no_secret_identity_or_transport_material_reaches_canonical_key_material() -> None:
    # Plan §8 #5 + §10: not one of these may appear, whether the caller sent it or
    # not. The transport/identity fields below are exactly the excluded list in
    # requirements §3.1.
    # WHY no ``metadata`` here: its mere presence bypasses, so including it would
    # make this test vacuous — nothing would be canonicalized to inspect.
    body = _body(timeout=30, temperature=0.7, trace_label="a", provider_params={"top_k": 3})
    body["extra_headers"] = {"Authorization": "Bearer sk-live-DEADBEEF"}
    dto = build_global_cache_key_dto(
        provider=_PROVIDER,
        body=body,
        rules=_RULES,
        projection=_projection,
        provider_auth_modes=_AUTH,
        parameter_contract_revision=_CONTRACT_REVISION,
    )
    assert isinstance(dto, GlobalChatCacheKey), dto
    material = canonical_key_material(dto)
    for forbidden in (
        "sk-live-DEADBEEF",
        "Authorization",
        "extra_headers",
        "timeout",
        "trace_label",
        "account_id",
        "profile_name",
        "credential",
        "X-User-Email",
    ):
        assert forbidden not in material, forbidden


def test_the_result_carries_only_hashes_and_non_sensitive_provenance() -> None:
    # Plan §10: a prompt or canonical DTO must never be persisted, so the object
    # the route holds and logs cannot contain either.
    built = _build(_body(messages=[{"role": "user", "content": "SECRET-PROMPT"}]))
    assert isinstance(built, GlobalCacheKeyResult), built
    assert "SECRET-PROMPT" not in repr(built)
    assert not hasattr(built, "key_version")
    assert built.provider == _PROVIDER
    assert built.model == _MODEL
    assert len(built.key_hash) == 64
    assert len(built.prompt_hash) == 64


# --- prompt fidelity ----------------------------------------------------------


def test_prompt_whitespace_and_case_are_preserved_exactly() -> None:
    # Plan §2.2: no trim, lowercasing, whitespace folding or Unicode rewriting
    # participates in key construction.
    variants = (
        "hi",
        " hi",
        "hi ",
        "HI",
        "h i",
        "hi\n",
    )
    hashes = {_hash(_body(messages=[{"role": "user", "content": text}])) for text in variants}
    assert len(hashes) == len(variants)


def test_message_order_participates_in_the_key() -> None:
    first = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    second = list(reversed(first))
    assert _hash(_body(messages=first)) != _hash(_body(messages=second))


def test_non_ascii_prompt_text_is_not_escaped_in_canonical_material() -> None:
    dto = build_global_cache_key_dto(
        provider=_PROVIDER,
        body=_body(messages=[{"role": "user", "content": "héllo"}]),
        rules=_RULES,
        projection=_projection,
        provider_auth_modes=_AUTH,
        parameter_contract_revision=_CONTRACT_REVISION,
    )
    assert isinstance(dto, GlobalChatCacheKey), dto
    assert "héllo" in canonical_key_material(dto)


# --- keyed / bypass / transport_only classification ---------------------------


def test_a_keyed_parameter_changes_the_key() -> None:
    bare = _hash()
    assert _hash(_body(temperature=0.7)) != bare
    assert _hash(_body(temperature=0.7)) != _hash(_body(temperature=0.8))


def test_two_keyed_parameters_are_addressed_independently() -> None:
    assert _hash(_body(temperature=0.7)) != _hash(_body(top_p=0.7))


def test_a_wrapped_native_parameter_is_keyed_through_the_prepared_projection() -> None:
    """Plan §2.6: a native control participates as the value the provider SENDS.

    WHY not the caller's request path and raw value: the boundary reconstructs its
    own object from an allowlist, so several accepted spellings are one upstream
    request. Keying the spelling would split that one request across several
    entries; keying the reconstruction is what makes the equivalences below true.
    """
    dto = build_global_cache_key_dto(
        provider=_PROVIDER,
        body=_body(temperature=0.7, provider_params={"top_k": 3}),
        rules=_RULES,
        projection=_projection,
        provider_auth_modes=_AUTH,
        parameter_contract_revision=_CONTRACT_REVISION,
    )
    assert isinstance(dto, GlobalChatCacheKey), dto
    assert set(dto.keyed_parameters) == {"temperature"}
    assert dto.prepared_request["extra_body"] == {"top_k": 3}
    assert WRAPPER_KEY not in canonical_key_material(dto)


def test_a_native_parameter_value_still_changes_the_key() -> None:
    # The route through the projection must stay value-SENSITIVE: dropping the raw
    # spelling may never mean dropping the parameter.
    bare = _hash()
    assert _hash(_body(provider_params={"top_k": 3})) != bare
    assert _hash(_body(provider_params={"top_k": 3})) != _hash(_body(provider_params={"top_k": 5}))


def test_two_spellings_the_provider_canonicalizes_share_one_key() -> None:
    # Plan §2.6: "1" == "1.0" for a value the provider normalizes before sending.
    assert _hash(_body(provider_params={"ceiling": "1"})) == _hash(
        _body(provider_params={"ceiling": "1.0"})
    )
    assert _hash(_body(provider_params={"ceiling": "1"})) != _hash(
        _body(provider_params={"ceiling": "2"})
    )


def test_a_native_value_the_provider_omits_matches_leaving_it_out() -> None:
    # Plan §2.6: a flag whose ``false`` is sent as nothing at all is the same
    # upstream request as omitting it, so the two must share one entry — while
    # ``true`` stays distinct.
    omitted = _hash(_body(provider_params={"top_k": 3}))
    assert _hash(_body(provider_params={"top_k": 3, "flag": False})) == omitted
    assert _hash(_body(provider_params={"top_k": 3, "flag": True})) != omitted


def test_a_native_parameter_the_projection_does_not_describe_bypasses() -> None:
    """The guard that keeps the projection route from becoming a silent omission.

    A provider that accepts a native path but never describes the surface it
    projects into would otherwise hand two different values the SAME key — the one
    failure mode a shared cache may never have. Fail safe: bypass instead.
    """

    def _undescribed(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        return {
            "resolved_model": "m",
            "provider_adapter_revision": _ADAPTER_REVISION,
            "prepared": {"policy": {"require_parameters": True}},
        }

    assert (
        _reason(_body(provider_params={"top_k": 3}), projection=_undescribed)
        == "unprojected_parameter"
    )


def test_a_keyed_parameter_revision_bump_changes_the_key() -> None:
    # Plan §2.5: bump a revision whenever an output-affecting behaviour changes
    # without appearing in the canonical request.
    bumped = tuple(
        _direct("temperature", revision="rule-r2") if rule.request_path == "temperature" else rule
        for rule in _RULES
    )
    body = _body(temperature=0.7)
    assert _hash(body) != _hash(body, rules=bumped)


def test_the_parameter_contract_revision_changes_the_key() -> None:
    assert _hash() != _hash(parameter_contract_revision="pc-2")


def test_a_transport_only_parameter_does_not_change_the_key() -> None:
    # Plan §2.4: excluded ONLY because the rule proves it does not affect output.
    assert _hash(_body(trace_label="a")) == _hash()
    assert _hash(_body(trace_label="a")) == _hash(_body(trace_label="b"))


def test_an_unknown_caller_parameter_bypasses() -> None:
    assert _reason(_body(nonesuch=1)) == "unknown_parameter"


def test_an_unknown_wrapped_native_parameter_bypasses() -> None:
    assert _reason(_body(provider_params={"nonesuch": 1})) == "unknown_parameter"


def test_a_parameter_whose_rule_declares_bypass_bypasses() -> None:
    # Bound to the CONSTANT, not the literal: this asserts the plumbing (which rule
    # produced the refusal), and the caller-visible spelling is owned in exactly one
    # place, test_global_cache_reason_vocabulary.py. A literal here would be a second
    # source of truth that has to be edited on every vocabulary decision.
    assert _reason(_body(legacy_only=1)) == BYPASS_DECLARED


def test_a_keyed_value_that_fails_its_schema_bypasses() -> None:
    # WHY bypass rather than key it: a schema-invalid value is auth-INDEPENDENT,
    # so the miss path will 400 it. Keying it would let a later identical request
    # be answered 200 from cache for a request the gateway must refuse.
    assert _reason(_body(temperature=99)) == "malformed_parameter"
    assert _reason(_body(temperature="warm")) == "malformed_parameter"


def test_a_non_object_wrapper_bypasses() -> None:
    assert _reason(_body(provider_params="nope")) == "unsupported_shape"


def test_a_dotted_top_level_key_bypasses() -> None:
    # OME-704: the wrapper OBJECT is the only caller addressing form, so a
    # top-level key spelled that way is malformed addressing — never a silent
    # second door into a keyed parameter.
    assert _reason(_body(**{"provider_params.top_k": 3})) == "unknown_parameter"


@pytest.mark.parametrize("path", ["reasoning.max_tokens", "unknown.path", "x.y"])
def test_an_unknown_direct_dotted_parameter_bypasses(path: str) -> None:
    # INVARIANT: cache eligibility runs before dispatch classification. A dotted path without a
    # rule must bypass, or a hit could answer 200 for a request whose miss path returns 400.
    assert _reason(_body(**{path: "value"})) == "unknown_parameter"


def test_a_provider_rule_set_that_cannot_be_normalized_bypasses() -> None:
    # Two rules claiming one request path is a provider misconfiguration. It must
    # degrade to bypass on the request path, never raise into the route.
    duplicated = (*_RULES, _direct("temperature", revision="rule-r9"))
    assert _reason(_body(temperature=0.7), rules=duplicated) == "provider_rule_set"


# --- gateway-owned and protocol fields ---------------------------------------


def test_streaming_is_ineligible() -> None:
    assert _reason(_body(stream=True)) == "stream"


def test_stream_false_is_eligible_and_does_not_change_the_key() -> None:
    assert _hash(_body(stream=False)) == _hash()


def test_tool_bearing_requests_are_eligible() -> None:
    # OME-782 (owner decision D1): tools/tool_choice presence no longer bypasses
    # unconditionally — whether they key or bypass is decided the ordinary way, by
    # whatever rule a provider declares for them. ``_RULES`` above declares NO
    # ``tools``/``tool_choice`` rule at all, so this fabricated provider's answer is
    # "unknown_parameter" — the same answer any other undeclared path gets — not a
    # tool-specific reason. See test_global_cache_tool_requests.py for the keyed
    # case, on a provider that DOES declare function-calling rules.
    tools = [{"type": "function", "function": {"name": "f"}}]
    assert _reason(_body(tools=tools)) == "unknown_parameter"
    assert _reason(_body(tool_choice="auto")) == "unknown_parameter"


def test_caller_metadata_is_ineligible() -> None:
    # Plan §1.3: metadata bypasses until a closed transport-only subset is
    # separately proven — including an EMPTY object, because presence is the fact.
    assert _reason(_body(metadata={"run_id": "r1"})) == "metadata"
    assert _reason(_body(metadata={})) == "metadata"


def test_timeout_is_excluded_from_the_key() -> None:
    assert _hash(_body(timeout=30)) == _hash()
    assert _hash(_body(timeout=30)) == _hash(_body(timeout=60))


def test_the_requested_and_resolved_model_both_participate() -> None:
    assert _hash(_body(model="fake/other")) != _hash()

    def _other_resolution(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        return {
            "resolved_model": "pinned-snapshot",
            "provider_adapter_revision": _ADAPTER_REVISION,
            "prepared": {"policy": {"require_parameters": True}},
        }

    assert _hash(projection=_other_resolution) != _hash()


def test_the_provider_participates_in_the_key() -> None:
    assert _hash(provider="other") != _hash()


def test_an_absent_system_context_differs_from_an_explicit_null() -> None:
    # Plan §2.5: missing, null, false and zero remain distinct.
    assert _hash(_body(system=None)) != _hash()
    assert _hash(_body(system="be terse")) != _hash(_body(system=None))
    assert _hash(_body(system="")) != _hash(_body(system=None))


def test_zero_false_and_null_keyed_values_remain_distinct() -> None:
    boolean = _direct("flag", schema=ParameterSchema(type="boolean"))
    number = _direct("amount", schema=ParameterSchema(type="number", minimum=0, maximum=2))
    rules = (*_RULES, boolean, number)
    hashes = {
        _hash(_body(), rules=rules),
        _hash(_body(flag=False), rules=rules),
        _hash(_body(amount=0), rules=rules),
    }
    assert len(hashes) == 3


# --- the provider projection --------------------------------------------------


def test_a_provider_projection_bypass_propagates_with_its_reason() -> None:
    def _refuses(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        return CacheBypass(reason="provider_projection")

    assert _reason(projection=_refuses) == "provider_projection"


def test_an_unrecognized_projection_member_bypasses() -> None:
    # Plan §1.3: unsafe or unrecognized provider-prepared output-affecting fields
    # bypass. The projection contract is CLOSED, so a new member cannot slip into
    # the key unreviewed — nor be silently dropped from it.
    def _extra(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        return {
            "resolved_model": "m",
            "provider_adapter_revision": _ADAPTER_REVISION,
            "prepared": {},
            "surprise": True,
        }

    assert _reason(projection=_extra) == "provider_projection"


@pytest.mark.parametrize(
    "returned",
    [
        {"provider_adapter_revision": "pa-1", "prepared": {}},
        {"resolved_model": "m", "prepared": {}},
        {"resolved_model": "m", "provider_adapter_revision": "pa-1"},
        {"resolved_model": 7, "provider_adapter_revision": "pa-1", "prepared": {}},
        {"resolved_model": "m", "provider_adapter_revision": 7, "prepared": {}},
        {"resolved_model": "m", "provider_adapter_revision": "pa-1", "prepared": "nope"},
        "not-a-mapping",
        None,
    ],
)
def test_a_malformed_projection_bypasses(returned: Any) -> None:
    assert _reason(projection=lambda body: returned) == "provider_projection"


def test_a_projection_that_raises_bypasses_instead_of_failing_the_request() -> None:
    # The cache is an optimization and must never become an availability
    # dependency (plan §5.4), so even a buggy provider hook only costs a bypass.
    def _explodes(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        raise RuntimeError("boom")

    assert _reason(projection=_explodes) == "provider_projection"


def test_the_projection_cannot_mutate_the_callers_body() -> None:
    seen: list[dict[str, Any]] = []

    def _mutates(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        seen.append(body)
        body["messages"] = [{"role": "user", "content": "rewritten"}]
        return _projection({"model": _MODEL})

    body = _body()
    _build(body, projection=_mutates)
    assert body["messages"] == _MESSAGES
    assert seen and seen[0] is not body


def test_the_prepared_state_participates_in_the_key() -> None:
    def _other_policy(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        return {
            "resolved_model": "m",
            "provider_adapter_revision": _ADAPTER_REVISION,
            "prepared": {"policy": {"require_parameters": True, "zdr": True}},
        }

    assert _hash(projection=_other_policy) != _hash()


def test_the_provider_adapter_revision_changes_the_key() -> None:
    def _bumped(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        return {
            "resolved_model": "m",
            "provider_adapter_revision": "pa-2",
            "prepared": {"policy": {"require_parameters": True}},
        }

    assert _hash(projection=_bumped) != _hash()


# --- canonicalization ---------------------------------------------------------


def test_canonical_material_is_sorted_compact_and_utf8() -> None:
    dto = build_global_cache_key_dto(
        provider=_PROVIDER,
        body=_body(),
        rules=_RULES,
        projection=_projection,
        provider_auth_modes=_AUTH,
        parameter_contract_revision=_CONTRACT_REVISION,
    )
    assert isinstance(dto, GlobalChatCacheKey), dto
    assert canonical_key_material(dto) == (
        '{"keyed_parameters":{},'
        '"messages":[{"content":"hi","role":"user"}],'
        '"operation":"chat.completions",'
        '"parameter_contract_revision":"pc-1",'
        '"prepared_request":{"policy":{"require_parameters":true}},'
        '"provider":"fake",'
        '"provider_adapter_revision":"pa-1",'
        '"requested_model":"fake/m",'
        '"resolved_model":"m",'
        '"schema":"aigw-global-chat-cache-2026-08",'
        '"system":{"present":false}}'
    )


def test_the_key_hash_is_sha256_of_the_canonical_bytes() -> None:
    dto = build_global_cache_key_dto(
        provider=_PROVIDER,
        body=_body(),
        rules=_RULES,
        projection=_projection,
        provider_auth_modes=_AUTH,
        parameter_contract_revision=_CONTRACT_REVISION,
    )
    assert isinstance(dto, GlobalChatCacheKey), dto
    expected = hashlib.sha256(canonical_key_material(dto).encode("utf-8")).hexdigest()
    assert _hash() == expected


def test_body_key_order_does_not_change_the_key() -> None:
    # Object keys SORT; only arrays preserve order.
    ordered = {"model": _MODEL, "messages": [dict(m) for m in _MESSAGES], "temperature": 0.7}
    reordered = {"temperature": 0.7, "messages": [dict(m) for m in _MESSAGES], "model": _MODEL}
    assert _hash(ordered) == _hash(reordered)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_number_bypasses_as_a_canonicalization_failure(value: float) -> None:
    # A NaN ceiling or an infinite temperature has no canonical spelling, so it
    # can never be a key dimension. json.dumps(allow_nan=False) would also refuse
    # it — this fails BEFORE that, with a bounded reason instead of a ValueError.
    unbounded = _direct("amount", schema=None)
    assert _reason(_body(amount=value), rules=(*_RULES, unbounded)) == "canonicalization_failure"


def test_an_unserializable_value_bypasses_as_a_canonicalization_failure() -> None:
    unbounded = _direct("amount", schema=None)
    assert _reason(_body(amount={1, 2}), rules=(*_RULES, unbounded)) == "canonicalization_failure"


def test_a_non_string_object_key_bypasses_as_a_canonicalization_failure() -> None:
    # ``json.dumps`` COERCES an int key to a string, so {1: "a"} and {"1": "a"}
    # would collide on one hash. Refusing is the only safe answer.
    unbounded = _direct("amount", schema=None)
    assert _reason(_body(amount={1: "a"}), rules=(*_RULES, unbounded)) == "canonicalization_failure"


def test_a_malformed_body_bypasses_instead_of_raising() -> None:
    assert _reason({"messages": _MESSAGES}) == "unsupported_shape"
    assert _reason({"model": _MODEL}) == "unsupported_shape"
    assert _reason({"model": 7, "messages": _MESSAGES}) == "unsupported_shape"
    assert _reason({"model": _MODEL, "messages": "hi"}) == "unsupported_shape"


# --- the reviewed field inventory (U2) ----------------------------------------

_DISPOSITION_GROUPS = (
    ("prompt", PROMPT_FIELDS),
    ("excluded", EXCLUDED_TRANSPORT_FIELDS),
    ("bypass_on_presence", frozenset(PRESENCE_BYPASS_REASONS)),
    ("bypass_when_truthy", frozenset(TRUTHY_BYPASS_REASONS)),
)


def test_every_gateway_owned_field_has_an_explicit_reviewed_disposition() -> None:
    """The inventory guard: nothing is silently defaulted.

    A gateway-owned field is not a request path, so no provider rule dispositions
    it — the key builder must. Adding one to ``GATEWAY_OWNED_FIELDS`` without
    deciding here whether it is prompt material, excluded transport, or a bypass
    would make it silently absent from the hash.
    """
    dispositioned = frozenset().union(*(fields for _name, fields in _DISPOSITION_GROUPS))
    assert GATEWAY_OWNED_FIELDS <= dispositioned, GATEWAY_OWNED_FIELDS - dispositioned


def test_no_field_carries_two_dispositions() -> None:
    for index, (name, fields) in enumerate(_DISPOSITION_GROUPS):
        for other_name, other in _DISPOSITION_GROUPS[index + 1 :]:
            assert not fields & other, (name, other_name, fields & other)


def test_the_wrapper_is_not_dispositioned_as_an_ordinary_field() -> None:
    # The wrapper is a container with its own branch: its nested keys are request
    # paths in their own right. Listing it as prompt/excluded/bypass material
    # would hide every provider-native parameter from the key.
    for name, fields in _DISPOSITION_GROUPS:
        assert WRAPPER_KEY not in fields, name
