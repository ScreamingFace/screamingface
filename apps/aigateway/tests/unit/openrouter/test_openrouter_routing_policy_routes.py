"""OME-704: the routing controls through the REAL ``POST /v1/chat/completions``.

FEATURE: an authenticated researcher constrains an OpenRouter request by unit price
and downstream data policy, using five documented ``provider_params`` leaves, without
the gateway ever exposing OpenRouter's raw ``provider`` control object.

STORY: as a researcher benchmarking on a budget, I say "sort by price, refuse an
endpoint dearer than X per million prompt tokens, and refuse one that trains on my data" and I
get either a request served under exactly those constraints or an explicit refusal.

WHY this module exists alongside the unit suites: ``test_openrouter_routing_policy``
proves the RULES and ``test_openrouter_routing_policy_wire`` proves the BOUNDARY, both
by calling the pieces directly. Neither can prove the pipeline ORDER — that a refusal
happens before credential material is read, that the 503 precedes cache planning, that
the generic ingress strip still runs first. Order is a property of the composed route,
so it is tested through the route.

INVARIANT (the security core): nothing a caller can write reaches a credential or the
wire until classification has accepted it. Every negative case below therefore asserts
TWO things — the sanitized rejection, and that dispatch never happened.

AIDEV-NOTE: the fixtures/helpers are the house OpenRouter route harness (see
``test_openrouter_security`` and ``test_openrouter_error_policy``), copied rather than
shared because each module pins its own dispatch double.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from litellm.exceptions import NotFoundError

from aigateway.core.credential_strategy_cache import credential_strategy_cache
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.parameter_projection import caller_cache_bypass_paths
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_KEY = "sk-or-v1-routing"
_MODEL = "openrouter/anthropic/claude-fable-5"
_MESSAGES: list[Any] = [{"role": "user", "content": "hi"}]
_OFFICIAL_API_BASE = "https://openrouter.ai/api/v1"

# Spelled out, never imported: a rename of a production constant must not be able to
# silently rename what the caller writes or what OpenRouter receives.
_STRICT = {"require_parameters": True}


@pytest.fixture(autouse=True)
def _api_key_validation_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # Explicit test double (per tests/unit/conftest.py AIDEV-NOTE): key readiness is
    # not what the routing controls exercise.
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
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


def _create_connection(client) -> None:
    resp = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "work-openrouter", "api_key": _KEY},
    )
    assert resp.status_code == 201, resp.text


class _Dispatch:
    """Records every ``litellm.acompletion`` call — the last gateway-controlled point."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            model_dump=lambda: {
                "id": f"or-{len(self.calls)}",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            }
        )

    @property
    def only(self) -> dict[str, Any]:
        assert len(self.calls) == 1, f"expected exactly one dispatch, got {len(self.calls)}"
        return self.calls[0]


def _post_chat(client, body: dict[str, Any] | None = None):
    payload = {"model": _MODEL, "messages": list(_MESSAGES), **(body or {})}
    return client.post("/v1/chat/completions", json=payload)


def _post_wrapper(client, wrapper: dict[str, Any]):
    return _post_chat(client, {"provider_params": wrapper})


# --- the reviewed surface, spelled out ----------------------------------------
#
# (caller leaf, accepted value, the fragment it must produce inside `provider`).
_CONTROLS: tuple[tuple[str, Any, dict[str, Any]], ...] = (
    ("sort", "price", {"sort": "price"}),
    ("max_price_prompt", "1.5", {"max_price": {"prompt": "1.5"}}),
    ("max_price_completion", "0.002", {"max_price": {"completion": "0.002"}}),
    ("data_collection", "deny", {"data_collection": "deny"}),
    ("zdr", True, {"zdr": True}),
)
_ALL_LEAVES = {leaf: value for leaf, value, _ in _CONTROLS}
_ALL_POLICY = {
    "sort": "price",
    # The two price leaves are separate caller controls that share ONE upstream
    # object — the case a per-leaf test cannot reach.
    "max_price": {"prompt": "1.5", "completion": "0.002"},
    "data_collection": "deny",
    "zdr": True,
    **_STRICT,
}


# --- 1 + 2: each control, and all of them, dispatch once with the right policy ---


@pytest.mark.parametrize(("leaf", "value", "fragment"), _CONTROLS, ids=[c[0] for c in _CONTROLS])
def test_each_control_dispatches_once_with_its_documented_policy(
    leaf, value, fragment, enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        resp = _post_wrapper(authenticated_client, {leaf: value})

    assert resp.status_code == 200, resp.text
    # Exactly one upstream call: an accepted control must not cost a retry.
    assert dispatch.only["provider"] == {**fragment, **_STRICT}


def test_the_whole_control_set_dispatches_as_one_policy(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # Four logical controls, five caller leaves, one upstream object.
    _create_connection(authenticated_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        resp = _post_wrapper(authenticated_client, dict(_ALL_LEAVES))

    assert resp.status_code == 200, resp.text
    assert dispatch.only["provider"] == _ALL_POLICY
    # The credential still comes from the account-scoped connection, and the host is
    # still the pinned official base: no routing field may redirect either.
    assert dispatch.only["api_key"] == _KEY
    assert dispatch.only["api_base"] == _OFFICIAL_API_BASE


# --- 10: omission changes nothing ---------------------------------------------


def test_omitting_every_control_leaves_the_request_as_it_was(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # The feature is additive: a caller who says nothing about routing gets exactly
    # the pre-OME-704 request — the gateway-owned strict-routing policy alone.
    _create_connection(authenticated_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        resp = _post_chat(authenticated_client)

    assert resp.status_code == 200, resp.text
    assert dispatch.only["provider"] == _STRICT


# --- 8: a no-eligible-endpoint refusal stays sanitized and keeps the key valid ---


_WIRE_REQUEST = httpx.Request("POST", _OFFICIAL_API_BASE)


def _as_transport(exc: Exception, *, wire_status: int) -> Exception:
    # Mirrors the provenance a real litellm OpenRouter transport failure carries
    # (chained httpx.HTTPStatusError + surfaced wire headers), so the fail-closed
    # classifier reads it as transport rather than as an ambiguous 502.
    response = httpx.Response(wire_status, request=_WIRE_REQUEST)
    exc.__cause__ = httpx.HTTPStatusError(
        f"{wire_status}", request=_WIRE_REQUEST, response=response
    )
    exc.litellm_response_headers = dict(response.headers)  # type: ignore[attr-defined]
    return exc


def _active_labels(client, account_id: str) -> list[str]:
    async def _list() -> list[str]:
        connections = await OAuthConnectionStore().list(
            account_id, provider="openrouter", status="active"
        )
        return sorted(connection.label for connection in connections)

    return client.portal.call(_list)


def test_a_price_ceiling_no_endpoint_can_meet_is_refused_without_touching_the_key(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # This is what a price ceiling BUYS, and its cost: OpenRouter refuses rather than
    # quietly serving the request at a higher price. The refusal must arrive as a
    # refusal, sanitized — and it says nothing about the CREDENTIAL, so the key that
    # was perfectly valid must still be active afterwards. Marking it invalid here
    # would lock a researcher out of their account over a routing constraint.
    _create_connection(authenticated_client)
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    exc = _as_transport(
        NotFoundError(
            message=(
                "No endpoints found that satisfy max_price. Tried provider secret-internal-router."
            ),
            llm_provider="openrouter",
            model=_MODEL,
            response=httpx.Response(404, request=_WIRE_REQUEST),
        ),
        wire_status=404,
    )

    async def _raise(**_kwargs):
        raise exc

    with patch("litellm.acompletion", _raise):
        resp = _post_wrapper(authenticated_client, {"max_price_prompt": "0.0000001"})

    assert resp.status_code == 404, resp.text
    assert resp.status_code != 200
    # Neither the provider's prose nor a named internal endpoint reaches the caller.
    assert "secret-internal-router" not in resp.text
    assert "No endpoints found" not in resp.text
    # INVARIANT: only a 401 may invalidate an OpenRouter credential.
    assert _active_labels(authenticated_client, account_id) == ["work-openrouter"]


def test_a_zdr_refusal_embedded_in_a_200_body_still_keeps_the_key_valid(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # The second shape of the same refusal — an error object inside an HTTP 200. A
    # gateway reading only the status would hand back a "successful" completion with
    # no choices while the ZDR constraint was never honored.
    _create_connection(authenticated_client)
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    payload = {
        "id": "gen-zdr",
        "choices": [],
        "error": {
            "code": 404,
            "message": "No endpoints found that support zero data retention",
            "metadata": {"provider_name": "secret-internal-router"},
        },
    }

    async def _return(**_kwargs):
        return SimpleNamespace(model_dump=lambda: payload)

    with patch("litellm.acompletion", _return):
        resp = _post_wrapper(authenticated_client, {"zdr": True})

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "provider_error"
    # OME-1136: the provider message is relayed only sanitized.
    assert (
        resp.json()["detail"]["upstream_message"]
        == "No endpoints found that support zero data retention"
    )
    assert "secret-internal-router" not in resp.text
    assert _active_labels(authenticated_client, account_id) == ["work-openrouter"]


# --- 11: ZDR is upstream endpoint ELIGIBILITY, never a retention guarantee -----


def test_no_response_claims_end_to_end_zero_retention(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # WHY this test exists: `zdr` and `data_collection: "deny"` are ENDPOINT
    # ELIGIBILITY filters — they ask OpenRouter to route to endpoints that declare a
    # property. The gateway does not observe upstream storage and cannot verify a
    # claim about it, so no gateway response may imply one. A caller who read
    # "zero data retention guaranteed" in an AIGateway response would make a real
    # privacy decision on a promise nobody here can keep.
    _create_connection(authenticated_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        resp = _post_wrapper(authenticated_client, {"zdr": True, "data_collection": "deny"})

    assert resp.status_code == 200, resp.text
    lowered = resp.text.lower()
    for claim in ("zero data retention", "not retained", "no retention", "guarantee"):
        assert claim not in lowered, f"the response implies a retention promise: {claim!r}"
    # The controls are carried as what they are — routing conditions on the request.
    assert dispatch.only["provider"] == {"zdr": True, "data_collection": "deny", **_STRICT}


# --- 9: every routing-control request bypasses the prompt cache ----------------


@pytest.fixture
def _cache_env(monkeypatch):
    # Must run before the `client` fixture builds the app so Settings sees it.
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")


@pytest.fixture
def cache_client(_cache_env, authenticated_client: TestClient) -> TestClient:
    return authenticated_client


def _stored_entries(client) -> int:
    return client.portal.call(RequestCacheEntry.all().count)


def _post_cacheable(client, wrapper: dict[str, Any] | None = None):
    body: dict[str, Any] = {"cache": {"use-cache": True}}
    if wrapper is not None:
        body["provider_params"] = wrapper
    return _post_chat(client, body)


@pytest.mark.parametrize(
    ("leaf", "value"),
    [*[(leaf, value) for leaf, value, _ in _CONTROLS], ("zdr", False)],
    ids=[*[c[0] for c in _CONTROLS], "zdr-false"],
)
def test_a_routing_control_request_is_cached_under_the_policy_it_will_be_sent_with(
    leaf, value, enabled_openrouter, credential_blobs, cache_client
) -> None:
    """SUPERSEDED (OME-305), was
    ``test_a_routing_control_request_bypasses_the_cache_and_stores_nothing``.

    The old assertion was ``bypass`` twice, no key, two dispatches, zero rows — and it
    was correct for v1, whose key builder accepted only ``model``/``messages``/
    ``system`` and therefore could not carry a routing policy (OME-702). OME-702 is
    absorbed into OME-305: OpenRouter now PROJECTS its prepared request, so the policy
    that will actually be sent participates in the hash and the five controls declare
    ``cache_behavior="keyed"``. Demanding a bypass here would demand the defect.

    RECONSTRUCTED, not dropped. The old test's real subject was the SAFETY property in
    its comment — "serving a cached answer produced under a DIFFERENT price ceiling or
    data policy would silently violate the constraint the caller set". v1 delivered it
    by refusing to cache at all; v2 delivers it by keying the policy. So this case now
    proves the caching works, and ``test_two_requests_under_different_routing_policies_
    never_share_an_entry`` below proves the constraint it protects. Both are needed:
    either one alone can be satisfied by a cache that is simply broken.

    The ``zdr: false`` row stays for the same reason it was added — it is the value the
    gateway OMITS upstream. Under v1 its presence alone forced a bypass; under v2 it
    must still resolve through a real rule and land on the same key as omitting it
    (pinned at the key level in ``test_openrouter_global_cache_projection``).
    """
    _create_connection(cache_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        first = _post_cacheable(cache_client, {leaf: value})
        second = _post_cacheable(cache_client, {leaf: value})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.headers["X-AIGW-Cache"] == "miss"
    assert first.headers["X-AIGW-Cache-Write"] == "stored"
    assert second.headers["X-AIGW-Cache"] == "hit"
    # A participating request DOES publish a key, and both requests resolve to one.
    assert len(first.headers["X-AIGW-Cache-Key"]) == 12
    assert second.headers["X-AIGW-Cache-Key"] == first.headers["X-AIGW-Cache-Key"]
    # Symmetric proof, inverted: it read (one dispatch, not two) and wrote (one row).
    assert len(dispatch.calls) == 1
    assert _stored_entries(cache_client) == 1


def test_two_requests_under_different_routing_policies_never_share_an_entry(
    enabled_openrouter, credential_blobs, cache_client
) -> None:
    """The safety property the superseded bypass test existed to protect.

    A caller who says "refuse an endpoint that trains on my data" must never be handed
    a response produced without that constraint. v1 guaranteed it by never caching a
    routing-controlled request; v2 guarantees it by putting the reconstructed policy in
    the key — so this is the route-level proof that the promotion did not trade the
    guarantee away for a hit rate.

    ``data_collection`` is used because it is the one reviewed control with two
    distinct valid values (``sort`` admits only ``"price"``), so the two requests differ
    in nothing but the policy.
    """
    _create_connection(cache_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        allow = _post_cacheable(cache_client, {"data_collection": "allow"})
        deny = _post_cacheable(cache_client, {"data_collection": "deny"})

    assert allow.status_code == 200, allow.text
    assert deny.status_code == 200, deny.text
    assert allow.headers["X-AIGW-Cache"] == "miss"
    assert deny.headers["X-AIGW-Cache"] == "miss", "a stricter policy must not hit a laxer fill"
    assert deny.headers["X-AIGW-Cache-Key"] != allow.headers["X-AIGW-Cache-Key"]
    assert len(dispatch.calls) == 2
    assert _stored_entries(cache_client) == 2


@pytest.mark.parametrize(
    ("leaf", "value"),
    [*[(leaf, value) for leaf, value, _ in _CONTROLS], ("zdr", False)],
    ids=[*[c[0] for c in _CONTROLS], "zdr-false"],
)
def test_no_control_is_attributed_as_a_caller_visible_bypass_path(leaf, value) -> None:
    """Every reviewed routing control remains keyed in the compatibility policy view."""
    plugin = OpenRouterProviderPlugin()
    rules = tuple(plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key"))
    paths = caller_cache_bypass_paths(
        {
            "model": _MODEL,
            "messages": list(_MESSAGES),
            # ``zdr: False`` is omitted upstream but must still resolve through a real rule.
            "provider_params": {leaf: value},
        },
        rules=rules,
        auth_mode="api_key",
    )
    assert paths == ()
    by_path = {rule.request_path: rule for rule in rules}
    assert by_path[f"provider_params.{leaf}"].cache_behavior == "keyed"


# --- 10: the operator gate reaches the cache path too (OME-305 review, MEDIUM-1) --


def test_a_pre_existing_row_is_not_replayed_after_the_provider_is_disabled(
    monkeypatch, enabled_openrouter, credential_blobs, cache_client
) -> None:
    """A disabled provider must not keep answering from rows it filled while enabled.

    WHY this is a route test and not only a projection test: the global cache is a
    SECOND path to this provider's responses, and it needs neither a registered model
    nor a credential to be walked — so the D2 guarantees on `register_models` and
    `api_key_strategy_for` do not cover it. Cache rows never expire, so without the gate
    the replay window is unbounded.

    The row is filled FIRST, while enabled, because that is the only arrangement in
    which the defect is observable: a gate that merely stops new writes would pass a
    test that never stored anything.

    AIDEV-NOTE: this is proven by a tripwire that was OBSERVED TO FIRE — with the
    ``participates_in_global_cache`` check in ``build_global_cache_plan`` neutralized,
    this test fails with ``x-aigw-cache: hit`` and a real key (``22bc51f35b2c``),
    returning a 200 body to a provider that is switched off. That also settles WHERE
    the gate has to live: the cache read happens ahead of model resolution and
    credential rejection, so the D2 404/400 paths never get a chance to refuse the
    request. Do not relocate this gate downstream on the assumption that dispatch-side
    failure covers it — and do not move it INTO the projection either, which is pure by
    contract (``test_no_projection_reads_operator_configuration``).
    """
    _create_connection(cache_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        filled = _post_cacheable(cache_client)
        assert filled.status_code == 200, filled.text
        assert filled.headers["X-AIGW-Cache-Write"] == "stored"
        assert _stored_entries(cache_client) == 1

        monkeypatch.setattr(
            openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=False)
        )
        # Production settings are read once when a process starts, so disabling the
        # provider also starts with no strategy cached by its formerly enabled state.
        credential_strategy_cache(cache_client.app).clear()
        after = _post_cacheable(cache_client)

    # A fresh disabled process follows the existing provider refusal path: it neither
    # replays the row nor dispatches with the credential strategy created while enabled.
    assert after.status_code == 400, after.text
    assert after.json()["detail"] == {
        "code": "api_key_not_supported",
        "provider": "openrouter",
    }
    assert len(dispatch.calls) == 1
    # ...and the row survives untouched: the gate declines to PARTICIPATE, it does not
    # invalidate. Re-enabling the provider must find its cache exactly as it left it.
    assert _stored_entries(cache_client) == 1


# --- 11: the declared `top_k` leaf really keys (OME-305 review, MEDIUM-2) --------


def test_the_same_top_k_request_is_served_from_cache_the_second_time(
    enabled_openrouter, credential_blobs, cache_client
) -> None:
    """`provider_params.top_k` declares ``cache_behavior="keyed"``; this is the proof.

    Before the fix every one of these requests bypassed with `unprojected_parameter`,
    because the projection never emitted the `extra_body` root its own rule targets.
    Fail-safe — but `top_k` is the one supported output-affecting provider parameter,
    so benchmark traffic using it could never reuse a response.
    """
    _create_connection(cache_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        first = _post_cacheable(cache_client, {"top_k": 3})
        second = _post_cacheable(cache_client, {"top_k": 3})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.headers["X-AIGW-Cache"] == "miss"
    assert first.headers["X-AIGW-Cache-Write"] == "stored"
    assert second.headers["X-AIGW-Cache"] == "hit"
    assert second.headers["X-AIGW-Cache-Key"] == first.headers["X-AIGW-Cache-Key"]
    assert len(dispatch.calls) == 1
    assert _stored_entries(cache_client) == 1
    # The value the key describes is the value the provider was actually sent.
    assert dispatch.only["extra_body"]["top_k"] == 3


def test_two_different_top_k_values_never_share_an_entry(
    enabled_openrouter, credential_blobs, cache_client
) -> None:
    """The safety half of keying `top_k`, and the reason the leaf must be projected.

    `top_k` changes the sampling distribution, so a response produced under 3 must
    never be handed to a caller who asked for 7. Emitting the `extra_body` ROOT while
    omitting the leaf would satisfy the key builder's root-only presence gate and
    produce exactly that collision — silently, with no bypass to signal it.
    """
    _create_connection(cache_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        three = _post_cacheable(cache_client, {"top_k": 3})
        seven = _post_cacheable(cache_client, {"top_k": 7})

    assert three.status_code == 200, three.text
    assert seven.status_code == 200, seven.text
    assert three.headers["X-AIGW-Cache"] == "miss"
    assert seven.headers["X-AIGW-Cache"] == "miss", "a different top_k must not hit"
    assert seven.headers["X-AIGW-Cache-Key"] != three.headers["X-AIGW-Cache-Key"]
    assert len(dispatch.calls) == 2
    assert _stored_entries(cache_client) == 2
