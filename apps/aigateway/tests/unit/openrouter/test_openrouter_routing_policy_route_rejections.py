"""OME-704 route-level validation and fail-closed ordering."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest

from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.dispatch_errors import (
    _unexpected_routing_policy_error,
)
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_KEY = "sk-or-v1-routing"
_MODEL = "openrouter/anthropic/claude-fable-5"
_MESSAGES: list[Any] = [{"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def _api_key_validation_ok(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _post_chat(client, body: dict[str, Any] | None = None):
    payload = {"model": _MODEL, "messages": list(_MESSAGES), **(body or {})}
    return client.post("/v1/chat/completions", json=payload)


def _post_wrapper(client, wrapper: dict[str, Any]):
    return _post_chat(client, {"provider_params": wrapper})


_INVALID: tuple[tuple[str, Any], ...] = (
    ("sort", "throughput"),
    ("sort", "latency"),
    ("sort", "price "),
    ("sort", 1),
    ("max_price_prompt", "-1"),
    ("max_price_prompt", "+1"),
    ("max_price_prompt", "1e5"),
    ("max_price_prompt", "01"),
    ("max_price_prompt", ".5"),
    ("max_price_prompt", "1."),
    ("max_price_prompt", " 1"),
    ("max_price_prompt", "NaN"),
    ("max_price_prompt", "inf"),
    ("max_price_prompt", ""),
    ("max_price_prompt", 1.5),
    ("max_price_prompt", True),
    ("max_price_prompt", "1" * 65),
    ("max_price_completion", "0.1.2"),
    ("max_price_completion", None),
    ("data_collection", "maybe"),
    ("data_collection", "Deny"),
    ("data_collection", ""),
    ("zdr", "true"),
    ("zdr", 1),
    ("zdr", None),
)


@pytest.mark.parametrize(("leaf", "value"), _INVALID, ids=[f"{k}={v!r}" for k, v in _INVALID])
def test_an_invalid_value_is_refused_and_never_dispatched(
    leaf, value, enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        resp = _post_wrapper(authenticated_client, {leaf: value})

    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "unsupported_parameters"
    assert detail["rejected"] == {f"provider_params.{leaf}": "malformed"}
    assert dispatch.calls == []


def test_a_rejection_never_echoes_the_raw_value(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    marker = "9e5c-canary-value"
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        resp = _post_wrapper(authenticated_client, {"max_price_prompt": marker})

    assert resp.status_code == 400, resp.text
    assert marker not in resp.text
    assert dispatch.calls == []


def test_a_refusal_names_every_bad_leaf_at_once(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        resp = _post_wrapper(
            authenticated_client,
            {"sort": "throughput", "max_price_prompt": "-1", "zdr": "yes", "data_collection": "ok"},
        )

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["rejected"] == {
        "provider_params.sort": "malformed",
        "provider_params.max_price_prompt": "malformed",
        "provider_params.zdr": "malformed",
        "provider_params.data_collection": "malformed",
    }
    assert dispatch.calls == []


def test_one_bad_leaf_refuses_the_whole_request(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    dispatch = _Dispatch()
    with patch("litellm.acompletion", dispatch):
        resp = _post_wrapper(
            authenticated_client, {"sort": "price", "max_price_prompt": "not-a-price"}
        )

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["rejected"] == {"provider_params.max_price_prompt": "malformed"}
    assert dispatch.calls == []


# OME-1207: the seam is the PORT's `authorize` (op 4) — the one operation that turns a
# resolved target into provider credential headers. Chat reaches it through
# `provider_access_for(app)`, so patching the implementation's method covers every call site
# a refused request could take, and cannot be bypassed by a future route-level rename.
_CREDENTIAL_SEAM = "aigateway.core.provider_access.ProfileBackedProviderAccess.authorize"


def _credential_tripwire(_self, _target, **_kwargs):
    raise AssertionError("credential injection ran on a refused request")


@pytest.mark.parametrize(
    "wrapper",
    [
        {"max_price_prompt": "-1"},
        {"sort": "throughput"},
        {"zdr": "true"},
        {"order": ["anthropic"]},
        {"max_price": {"prompt": "1"}},
    ],
    ids=["bad-price", "bad-sort", "bad-zdr", "wrapped-order", "wrapped-max_price"],
)
def test_a_refused_request_never_reaches_credential_material(
    wrapper, enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    dispatch = _Dispatch()
    with (
        patch(_CREDENTIAL_SEAM, _credential_tripwire),
        patch("litellm.acompletion", dispatch),
    ):
        resp = _post_wrapper(authenticated_client, wrapper)

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "unsupported_parameters"
    assert dispatch.calls == []


def test_a_refused_request_never_reaches_provider_preparation(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)

    def _tripwire(_self, _body):
        raise AssertionError("prepare_chat_body ran on a refused routing control")

    target = "aigateway.plugins.openrouter_provider.plugin.OpenRouterProviderPlugin"
    with patch(f"{target}.prepare_chat_body", _tripwire):
        resp = _post_wrapper(authenticated_client, {"max_price_prompt": "1e5"})

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_parameters"


class _FillTripwire:
    """A store that refuses to be FILLED, and records whether it was read.

    Replaces the v1 ``_resolve_cache_plan`` tripwire: under v2 the cache stage runs
    ahead of provider preparation by design, so "planning must not run" is no longer
    the property. What must still hold is that a request which ends in a 503 leaves
    NOTHING behind for the next caller to be served.
    """

    def __init__(self) -> None:
        self.probes = 0
        self.reads: list[str] = []

    def cache_available(self) -> bool:
        # Probed once per request, ahead of the plan — so a non-zero count proves the
        # cache stage actually RAN, which is what makes "no read happened" meaningful
        # rather than vacuously true because the stage was never reached.
        self.probes += 1
        return True

    async def get(self, key_hash: str):
        self.reads.append(key_hash)
        return None

    async def set_if_absent(self, entry):
        raise AssertionError("a request that ended in a 503 filled the global cache")


def test_a_reconstruction_mismatch_refuses_without_credentials_dispatch_or_a_cache_fill(
    enabled_openrouter, credential_blobs, authenticated_client, caplog
) -> None:
    """SUPERSEDED (OME-305), was ``..._precedes_cache_credentials_dispatch_and_logs``.

    The old ordering was ``prepare_chat_body`` THEN cache planning, so a reconstruction
    503 provably meant planning never ran. OME-305 inverts
    that ordering deliberately: the cache is consulted BEFORE preparation, because a
    hit must not require a credential. So "the 503 precedes cache planning" is not
    merely untrue now, it is the opposite of the deliverable.

    RECONSTRUCTED: the tripwires are replaced by the property that still matters and is
    strictly stronger — a request that ends in a 503 must leave NOTHING in the shared
    store for the next caller. Every other assertion is preserved verbatim: the
    sanitized 503, no credential read, no dispatch, and the provider's raw marker
    absent from both the response and the logs.

    AIDEV-NOTE: the companion property — that a caller whose routing policy cannot be
    rebuilt is never served a 200 HIT — is the test immediately below. This one cannot
    prove it: it patches the classifier, which runs AFTER the cache stage, so the cache
    stage here sees a legitimate body and a legitimate miss.
    """
    _create_connection(authenticated_client)
    marker = "route-reconstruction-secret-7f21"
    dispatch = _Dispatch()
    store = _FillTripwire()
    # cast: TestClient.app is typed as the raw ASGI callable, not the Starlette app.
    # INVARIANT: the store is reached through exactly one attribute on app.state.
    cast(Any, authenticated_client.app).state.request_cache_store = store

    def _mismatched_projection(body, **_kwargs):
        return {**body, "provider": {"require_parameters": marker}}

    with (
        patch(
            "aigateway.routes.chat.classify_and_project_chat_parameters",
            _mismatched_projection,
        ),
        patch(_CREDENTIAL_SEAM, _credential_tripwire),
        patch("litellm.acompletion", dispatch),
        caplog.at_level("DEBUG"),
    ):
        resp = _post_chat(authenticated_client)

    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"] == {
        "code": "provider_unavailable",
        "message": "OpenRouter dispatch is unavailable",
    }
    assert marker not in resp.text
    assert marker not in caplog.text
    assert dispatch.calls == []


def test_a_body_whose_routing_policy_cannot_be_rebuilt_is_never_served_from_cache(
    enabled_openrouter, credential_blobs, authenticated_client, caplog
) -> None:
    """The property that REPLACES v1's "the 503 precedes cache planning" (decision 12).

    Moving the cache read ahead of ``prepare_chat_body`` created a new way to be wrong:
    a body the provider would REFUSE to dispatch (503) could be answered 200 from cache
    instead, because the refusal now happens after the read. The projection closes it
    by calling the same ``build_provider_policy`` reconstruction and returning
    ``CacheBypass`` when it raises — so such a request is unkeyable, performs no read
    and no write, and still reaches its 503.

    AIDEV-NOTE: TWO patch targets model ONE refusing function, and the count matters.
    ``build_provider_policy`` has a single implementation, but it is imported into two
    namespaces — ``plugin`` for dispatch and ``global_cache`` for the projection — so a
    body it genuinely could not rebuild would be refused at BOTH. Patching only one
    reproduces half the cause and passes for the wrong reason: patch just
    ``global_cache`` and the projection bypasses while dispatch succeeds with a 200,
    which is what this test caught when the projection moved out of ``plugin``. If a
    later refactor collapses or moves these bindings, keep the rule rather than the
    line: every namespace that resolves the reconstruction must see it refuse.
    """
    _create_connection(authenticated_client)
    dispatch = _Dispatch()
    store = _FillTripwire()
    cast(Any, authenticated_client.app).state.request_cache_store = store

    # WHY the REAL error factory rather than a stand-in: the projection catches
    # ``_UnexpectedRoutingPolicyError`` by type, so a fabricated exception would prove
    # nothing about the guard that actually runs in production.
    def _unrebuildable(_policy):
        raise _unexpected_routing_policy_error()

    with (
        patch(
            "aigateway.plugins.openrouter_provider.global_cache.build_provider_policy",
            _unrebuildable,
        ),
        patch(
            "aigateway.plugins.openrouter_provider.plugin.build_provider_policy",
            _unrebuildable,
        ),
        patch("litellm.acompletion", dispatch),
        caplog.at_level("DEBUG"),
    ):
        resp = _post_chat(authenticated_client)

    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"]["code"] == "provider_unavailable"
    assert dispatch.calls == []
    # The stage ran (so the assertion below is not vacuous) and still produced no
    # read: the body was unkeyable, so there was no key to look anything up under.
    assert store.probes == 1
    assert store.reads == []
    # AIDEV-NOTE: deliberately NO cache-header assertions here. An HTTPException is
    # rendered by the exception middleware, which builds a fresh response and does not
    # carry the route's injected sub-response headers — so a 503 publishes no cache
    # disposition at all. That is framework behavior, not a cache property; the cache
    # properties worth pinning are the store assertions above.
