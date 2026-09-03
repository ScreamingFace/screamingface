"""OME-884 — direct OpenAI dispatch: what it forwards, and what it REFUSES.

FEATURE: one global exact-request cache (OME-305). The cache is a SECOND route to this
provider's answers — a stored row needs neither a registered model nor a credential — so
the ambient-runtime verdict the cache reader uses has to be the same one dispatch uses.
This suite is that verdict seen from the 503 side.

INVARIANT under test: every refusal lands BEFORE the API key is read, before the HTTP
client exists and before ``litellm.acompletion``, and it is the sanitized, non-retryable
``503 unsafe_openai_environment`` in every case. A request the gateway cannot certify does
no upstream work at all.

Scope of THIS file: model-grammar validation and the fail-closed ambient sweep. Siblings:
  ``test_openai_dispatch_wire.py``     — the final URL, headers and payload.
  ``test_openai_dispatch_controls.py`` — the projection/dispatch coupling, both ways.
  ``test_openai_runtime_guard.py``     — the same verdict seen from the cache side.
  ``test_openai_runtime_modifier.py``  — the one asymmetric hazard.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import httpx
import litellm
import pytest
from fastapi import HTTPException
from openai import AsyncOpenAI

from aigateway.core.retry import is_retryable_status
from aigateway.plugins.openai_provider import plugin as plugin_module
from aigateway.plugins.openai_provider.plugin import PLUGIN

# Bound to the original private names so every relocated test body below reads unchanged.
from .dispatch_harness import SELECTED_KEY as _SELECTED_KEY
from .dispatch_harness import capture_client_factory as _capture_client_factory
from .dispatch_harness import completion_response as _completion_response


class _FalseyProxyAuth:
    def __bool__(self) -> bool:
        return False


def test_prepare_chat_body_forwards_any_route_valid_model_and_refuses_malformed_ids() -> None:
    """OME-884 (authorized contract change): the catalog publishes, it does not admit.

    OME-864 refused any model absent from ``default_models`` here. That made the
    bootstrap ``/v1/models`` listing a dispatch allowlist, so a model OpenAI serves
    could not be addressed directly, and unpublishing one silently revoked dispatch.
    Preparation now validates the model ID's GRAMMAR — the same predicate the
    global-cache projection uses, so the two can never disagree about which requests
    are forwardable — and OpenAI remains the authority on whether the model exists and
    whether the caller's key may use it.
    """
    unlisted = "openai/gpt-4o-2024-11-20"
    assert unlisted not in PLUGIN.settings.default_models

    prepared = PLUGIN.prepare_chat_body({"model": unlisted, "messages": []})

    assert prepared == {
        "model": unlisted,
        "messages": [],
        "api_base": "https://api.openai.com/v1",
    }

    for malformed in ("openai/", "openai/gpt 5", "openai/gpt/5", "openrouter/openai/gpt-4o"):
        with pytest.raises(HTTPException) as raised:
            PLUGIN.prepare_chat_body({"model": malformed, "messages": []})
        assert raised.value.status_code == 400, malformed
        assert raised.value.detail == {
            "code": "invalid_model",
            "provider": "openai",
            "message": "model is not a valid direct OpenAI model id",
        }


@pytest.mark.asyncio
async def test_nonempty_ambient_custom_headers_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", '{"X-Leak":"ambient"}')

    with pytest.raises(HTTPException) as raised:
        await PLUGIN.chat_completion(
            {
                "model": "openai/gpt-5.6-sol",
                "messages": [],
                "api_key": _SELECTED_KEY,
                "api_base": "https://api.openai.com/v1",
            }
        )

    assert raised.value.status_code == 503
    assert raised.value.detail == {
        "code": "unsafe_openai_environment",
        "provider": "openai",
        "message": "direct OpenAI dispatch is unavailable",
    }
    assert "X-Leak" not in repr(raised.value.detail)


@pytest.mark.asyncio
async def test_process_global_litellm_headers_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(litellm, "headers", {"X-Leak": "ambient"})

    with pytest.raises(HTTPException) as raised:
        await PLUGIN.chat_completion(
            {
                "model": "openai/gpt-5.6-sol",
                "messages": [],
                "api_key": _SELECTED_KEY,
                "api_base": "https://api.openai.com/v1",
            }
        )

    assert raised.value.status_code == 503
    assert raised.value.detail == {
        "code": "unsafe_openai_environment",
        "provider": "openai",
        "message": "direct OpenAI dispatch is unavailable",
    }
    assert "X-Leak" not in repr(raised.value.detail)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_fallbacks", ["openai/gpt-4o-mini"]),
        ("callbacks", [object()]),
        ("pre_call_rules", [object()]),
        ("model_alias_map", {"openai/gpt-5.6-sol": "openai/gpt-4o"}),
        ("proxy_auth", _FalseyProxyAuth()),
        ("drop_params", True),
    ],
)
@pytest.mark.asyncio
async def test_process_global_routing_or_observation_state_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(litellm, "headers", None)
    monkeypatch.setattr(litellm, field, value)

    def forbidden_client(**_kwargs: Any) -> AsyncOpenAI:
        raise AssertionError("unsafe global state reached client construction")

    monkeypatch.setattr(plugin_module, "AsyncOpenAI", forbidden_client)

    with pytest.raises(HTTPException) as raised:
        await PLUGIN.chat_completion(
            {
                "model": "openai/gpt-5.6-sol",
                "messages": [],
                "api_key": _SELECTED_KEY,
                "api_base": "https://api.openai.com/v1",
            }
        )

    assert raised.value.status_code == 503
    assert raised.value.detail == {
        "code": "unsafe_openai_environment",
        "provider": "openai",
        "message": "direct OpenAI dispatch is unavailable",
    }
    assert is_retryable_status(raised.value) is False


@pytest.mark.asyncio
async def test_missing_selected_key_fails_before_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(litellm, "headers", None)

    with pytest.raises(HTTPException) as raised:
        await PLUGIN.chat_completion(
            {
                "model": "openai/gpt-5.6-sol",
                "messages": [],
                "api_base": "https://api.openai.com/v1",
            }
        )

    assert raised.value.status_code == 503
    assert raised.value.detail == {
        "code": "unsafe_openai_environment",
        "provider": "openai",
        "message": "direct OpenAI dispatch is unavailable",
    }


def test_every_seed_is_chat_mode_in_the_locked_runtime() -> None:
    for entry in PLUGIN.register_models():
        upstream_model = entry.model_name.split("/", 1)[1]
        assert litellm.get_model_info(upstream_model)["mode"] == "chat", entry.model_name


# --- OME-884: the runtime states that must ALSO stop a cache read --------------
#
# WHY these are dispatch tests as well as participation tests: the two verdicts come
# from ONE shared predicate on purpose. A state that only stopped dispatch would leave
# the cache serving rows from a runtime the gateway refuses to dispatch into; a state
# that only stopped participation would let the poisoned runtime answer live requests.


@pytest.mark.parametrize(
    "poison",
    [
        pytest.param(
            lambda mp: mp.setattr(litellm.OpenAIConfig, "temperature", 1),
            id="openai_config",
        ),
        pytest.param(
            lambda mp: mp.setenv("EXPERIMENTAL_OPENAI_BASE_LLM_HTTP_HANDLER", "true"),
            id="experimental_handler",
        ),
        pytest.param(
            lambda mp: mp.setattr(litellm, "secret_manager_client", object()),
            id="secret_manager",
        ),
    ],
)
@pytest.mark.asyncio
async def test_ambient_openai_configuration_and_transport_swaps_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    poison: Callable[[pytest.MonkeyPatch], None],
) -> None:
    """Three states OME-864 did not cover, each of which silently changes the call.

    * ``litellm.OpenAIConfig`` entries are merged into ``optional_params`` for EVERY
      OpenAI completion, so an operator-set temperature changes the answer while the
      cache key cannot see it.
    * ``EXPERIMENTAL_OPENAI_BASE_LLM_HTTP_HANDLER`` swaps the dispatch handler, so the
      client construction, retry and TLS guarantees this plugin's adapter revision pins
      are no longer the ones in force.
    * a configured secret-manager client resolves values — including the flag above —
      from outside this process, so no environment read here is authoritative any more.
    """
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.delenv("EXPERIMENTAL_OPENAI_BASE_LLM_HTTP_HANDLER", raising=False)
    monkeypatch.setattr(litellm, "secret_manager_client", None)
    monkeypatch.setattr(litellm, "headers", None)
    poison(monkeypatch)

    def forbidden_client(**_kwargs: Any) -> AsyncOpenAI:
        raise AssertionError("unsafe ambient state reached client construction")

    monkeypatch.setattr(plugin_module, "AsyncOpenAI", forbidden_client)

    with pytest.raises(HTTPException) as raised:
        await PLUGIN.chat_completion(
            {
                "model": "openai/gpt-5.6-sol",
                "messages": [],
                "api_key": _SELECTED_KEY,
                "api_base": "https://api.openai.com/v1",
            }
        )

    assert raised.value.status_code == 503
    assert raised.value.detail == {
        "code": "unsafe_openai_environment",
        "provider": "openai",
        "message": "direct OpenAI dispatch is unavailable",
    }
    assert is_retryable_status(raised.value) is False


@pytest.mark.asyncio
async def test_an_alias_for_another_model_leaves_this_one_dispatchable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The alias refusal is per-MODEL, and this is the half that proves it is not global.

    ``test_process_global_routing_or_observation_state_fails_closed`` already pins that
    an alias FOR the requested model refuses. Without this companion, a guard that
    disabled the provider outright whenever ANY alias existed would pass that test —
    and would abandon every unrelated model's cache over one poisoned entry.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_completion_response("gpt-5.6-sol"))

    _capture_client_factory(monkeypatch, handler)
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(litellm, "headers", None)
    monkeypatch.setattr(litellm, "model_alias_map", {"openai/gpt-4o": "openai/gpt-4o-mini"})

    body = PLUGIN.prepare_chat_body(
        {"model": "openai/gpt-5.6-sol", "messages": [{"role": "user", "content": "ping"}]}
    )
    body["api_key"] = _SELECTED_KEY

    result = await PLUGIN.chat_completion(body)
    await asyncio.sleep(0.05)

    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(requests) == 1


# --- OME-884 review: an ambient read that RAISES must still refuse -------------


class _ExplodingAliasMap(Mapping[str, str]):
    """A ``model_alias_map`` whose membership test raises instead of answering."""

    def __contains__(self, key: object) -> bool:
        raise RuntimeError("hostile alias map")

    def __getitem__(self, key: str) -> str:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


class _ExplodingTruthiness:
    """An ambient global that cannot even be asked whether it is set."""

    def __bool__(self) -> bool:
        raise RuntimeError("hostile truthiness")


def _raising_get_config() -> dict[str, Any]:
    raise RuntimeError("ambient config read exploded")


@pytest.mark.parametrize(
    "poison",
    [
        pytest.param(
            lambda mp: mp.setattr(
                litellm.OpenAIConfig, "get_config", staticmethod(_raising_get_config)
            ),
            id="get_config",
        ),
        pytest.param(
            lambda mp: mp.setattr(litellm, "model_alias_map", _ExplodingAliasMap()),
            id="alias_lookup",
        ),
        pytest.param(
            lambda mp: mp.setattr(litellm, "headers", _ExplodingTruthiness()),
            id="truthiness",
        ),
    ],
)
@pytest.mark.asyncio
async def test_an_ambient_read_that_raises_refuses_before_client_construction(
    monkeypatch: pytest.MonkeyPatch,
    poison: Callable[[pytest.MonkeyPatch], None],
) -> None:
    """The guard promised "fail CLOSED and never raise"; only the first half was true.

    Every ambient read was defensive about a MISSING attribute and about none of them
    answering by RAISING. A broken or hostile LiteLLM global therefore escaped as an
    ordinary ``RuntimeError``, which the chat route renders as a generic 502
    ``provider_error`` — telling the operator the upstream provider failed when in fact
    the gateway could not certify its own runtime.

    INVARIANT: unreadable is unsafe. The refusal is the SAME sanitized, non-retryable
    503 every other unsafe state produces, and it still lands before any client is
    constructed and before any credential leaves the body.
    """
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.delenv("EXPERIMENTAL_OPENAI_BASE_LLM_HTTP_HANDLER", raising=False)
    monkeypatch.setattr(litellm, "secret_manager_client", None)
    monkeypatch.setattr(litellm, "model_alias_map", {})
    monkeypatch.setattr(litellm, "headers", None)
    poison(monkeypatch)

    def forbidden_client(**_kwargs: Any) -> AsyncOpenAI:
        raise AssertionError("an unreadable runtime reached client construction")

    monkeypatch.setattr(plugin_module, "AsyncOpenAI", forbidden_client)

    with pytest.raises(HTTPException) as raised:
        await PLUGIN.chat_completion(
            {
                "model": "openai/gpt-5.6-sol",
                "messages": [],
                "api_key": _SELECTED_KEY,
                "api_base": "https://api.openai.com/v1",
            }
        )

    assert raised.value.status_code == 503
    assert raised.value.detail == {
        "code": "unsafe_openai_environment",
        "provider": "openai",
        "message": "direct OpenAI dispatch is unavailable",
    }
    assert is_retryable_status(raised.value) is False
