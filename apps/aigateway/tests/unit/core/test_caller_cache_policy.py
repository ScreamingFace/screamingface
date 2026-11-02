"""The caller-visible cache policy primitive (OME-479 §4.6, closure Unit 1).

FEATURE: an honest ``cache_behavior``. The detailed contract publishes ONE
unconditional value per request path, so the runtime decision has to be derivable
from the SAME thing the contract is derived from — the accepted caller-visible
rule set — and not from whatever survives provider preparation.

RED-first for the PURE core primitive ``caller_cache_bypass_paths(body, *, rules,
auth_mode)``. Fabricated rule sets only: no route, no network, no provider names,
so the mechanism stays provider-agnostic.

INVARIANT under test: the returned paths are exactly the paths the CALLER
addressed whose ENABLED rule declares ``cache_behavior="bypass"`` — computed
before projection, so a later rename/removal/nesting cannot change the answer.
"""

from __future__ import annotations

from aigateway.core.auth_types import AuthType
from aigateway.core.chat_parameters import CacheBehavior, ParameterProjectionRule, ParameterSchema
from aigateway.core.parameter_projection import (
    caller_cache_bypass_paths,
    classify_and_project_chat_parameters,
)

_NUM = ParameterSchema(type="number", minimum=0, maximum=2)


def _direct(
    path: str,
    *,
    auth: tuple[AuthType, ...] = ("api_key",),
    cache_behavior: CacheBehavior = "bypass",
    output_affecting: bool = True,
    target: str | None = None,
) -> ParameterProjectionRule:
    return ParameterProjectionRule(
        request_path=path,
        applicable_auth_modes=auth,
        projection_kind="direct",
        provider_target=target,
        cache_behavior=cache_behavior,
        output_affecting=output_affecting,
        projection_revision="r1",
        schema=_NUM,
    )


def _native(path: str, target: str) -> ParameterProjectionRule:
    return ParameterProjectionRule(
        request_path=path,
        applicable_auth_modes=("api_key",),
        projection_kind="provider_native",
        provider_target=target,
        cache_behavior="bypass",
        projection_revision="r1",
        schema=_NUM,
    )


def _policy(body, rules=(), auth_mode: AuthType = "api_key") -> tuple[str, ...]:
    return caller_cache_bypass_paths(body, rules=rules, auth_mode=auth_mode)


_PROMPT = {"model": "p/m", "messages": [{"role": "user", "content": "hi"}]}


def test_a_bare_prompt_addresses_no_bypassing_path() -> None:
    assert _policy(dict(_PROMPT), rules=(_direct("temperature"),)) == ()


def test_gateway_owned_fields_never_force_a_bypass() -> None:
    # model/messages/stream/extra_headers/metadata/timeout are authorized
    # STRUCTURALLY and carry no rule, so they can never be a bypass path — the
    # cache's own eligibility check owns `stream`.
    body = {**_PROMPT, "timeout": 30, "metadata": {"a": 1}, "extra_headers": {}}
    assert _policy(body, rules=(_direct("temperature"),)) == ()


def test_a_present_bypass_field_is_reported() -> None:
    body = {**_PROMPT, "temperature": 0.7}
    assert _policy(body, rules=(_direct("temperature"),)) == ("temperature",)


def test_a_wrapped_native_field_is_reported_at_its_request_path() -> None:
    # The wrapper is the caller-visible address; the provider TARGET
    # (extra_body.top_k) is deliberately not what the contract publishes.
    body = {**_PROMPT, "provider_params": {"top_k": 1}}
    rules = (_native("provider_params.top_k", "extra_body.top_k"),)
    assert _policy(body, rules=rules) == ("provider_params.top_k",)


def test_a_malformed_wrapper_addresses_nothing() -> None:
    # Classification rejects a non-object wrapper outright; the policy must not
    # crash trying to enumerate it.
    body = {**_PROMPT, "provider_params": "nope"}
    assert _policy(body, rules=(_native("provider_params.top_k", "extra_body.top_k"),)) == ()


def test_a_dotted_top_level_key_addresses_nothing() -> None:
    # OME-704: a top-level key spelled "provider_params.<leaf>" is not a caller
    # addressing form — classification rejects it, so it can never reach cache
    # planning. The two enumerations stay a true pair (see the anti-drift lock
    # below): if only one of them kept treating it as an address, the docstring
    # claim "the caller-visible addressing forms, and only those" would be false.
    body = {**_PROMPT, "provider_params.top_k": 1}
    rules = (_native("provider_params.top_k", "extra_body.top_k"),)
    assert _policy(body, rules=rules) == ()


def test_a_rule_outside_this_auth_mode_is_not_a_bypass_path() -> None:
    # The field is rejected by classification under this mode, so the request
    # never dispatches; the policy agrees it authorizes nothing here.
    body = {**_PROMPT, "temperature": 0.7}
    assert _policy(body, rules=(_direct("temperature", auth=("oauth",)),)) == ()


def test_a_keyed_rule_is_not_a_bypass_path() -> None:
    # `keyed` means "participates in the cache key", the opposite claim. Only
    # `bypass` forces a bypass — the primitive reads the rule, it does not assume.
    body = {**_PROMPT, "temperature": 0.7}
    assert _policy(body, rules=(_direct("temperature", cache_behavior="keyed"),)) == ()


def test_a_transport_only_rule_is_not_a_bypass_path() -> None:
    body = {**_PROMPT, "temperature": 0.7}
    rules = (_direct("temperature", cache_behavior="transport_only", output_affecting=False),)
    assert _policy(body, rules=rules) == ()


def test_multiple_bypass_paths_are_sorted_and_deduplicated() -> None:
    body = {**_PROMPT, "top_p": 0.9, "temperature": 0.7, "provider_params": {"top_k": 1}}
    rules = (
        _direct("temperature"),
        _direct("top_p"),
        _native("provider_params.top_k", "extra_body.top_k"),
    )
    assert _policy(body, rules=rules) == ("provider_params.top_k", "temperature", "top_p")


def test_the_policy_agrees_with_what_classification_accepted() -> None:
    """The anti-drift lock.

    INVARIANT: the two functions enumerate the caller's request paths from the
    SAME body by the same rules. If one ever learns a new addressing form the
    other does not, this fails — which is the whole reason the cache decision may
    be taken from the caller view instead of the projected body.
    """
    body = {**_PROMPT, "temperature": 0.7, "top_p": 0.9, "provider_params": {"top_k": 1}}
    rules = (
        _direct("temperature"),
        _direct("top_p"),
        _native("provider_params.top_k", "extra_body.top_k"),
    )
    projected = classify_and_project_chat_parameters(body, rules=rules, auth_mode="api_key")
    # Everything the caller addressed was accepted and projected...
    assert projected == {
        **_PROMPT,
        "temperature": 0.7,
        "top_p": 0.9,
        "extra_body": {"top_k": 1},
    }
    # ...and every accepted path shows up in the cache policy, at its REQUEST
    # path, not its projected target.
    assert set(_policy(body, rules=rules)) == {r.request_path for r in rules}
