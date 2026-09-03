"""OME-884 — the projection/dispatch coupling, proven in BOTH directions.

FEATURE: one global exact-request cache (OME-305). The key is only trustworthy while
"the key describes what dispatch sends" holds by construction rather than by review. Two
directions are needed and neither implies the other:

  forward  — every control the projection reports must actually reach the wire, or a row
             is keyed as if the gateway did something it did not do;
  backward — every gateway-added dispatch kwarg must appear in the projection, or the wire
             carries something the key never saw and two different requests share a row.

INVARIANT under test: the gateway-owned control set is exactly
``gateway_dispatch_controls()`` plus the request-local client, the caller can neither add
to it nor override it, and the API key never becomes key material.

Scope of THIS file: the coupling and the request-local client. The literal HTTP bytes live
in ``test_openai_dispatch_wire.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import litellm
import pytest

from aigateway.plugins.openai_provider.plugin import PLUGIN

# Bound to the original private names so every relocated test body below reads unchanged.
from .dispatch_harness import SELECTED_KEY as _SELECTED_KEY
from .dispatch_harness import capture_client_factory as _capture_client_factory
from .dispatch_harness import completion_response as _completion_response


def test_prepare_chat_body_keeps_only_gateway_owned_origin() -> None:
    prepared = PLUGIN.prepare_chat_body(
        {
            "model": "openai/gpt-5.6-sol",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 7,
            "api_key": "caller-key",
            "api_base": "https://caller.invalid/v1",
            "base_url": "https://caller.invalid/v1",
            "headers": {"Authorization": "caller"},
            "extra_headers": {"X-Custom": "caller"},
            "fallbacks": ["attacker/model"],
            "model_list": [{"model_name": "attacker/model"}],
            "callbacks": ["caller"],
            "success_callback": ["caller"],
            "failure_callback": ["caller"],
            "custom_llm_provider": "attacker",
            "azure": True,
            "text_completion": True,
        }
    )

    assert prepared == {
        "model": "openai/gpt-5.6-sol",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 7,
        "api_base": "https://api.openai.com/v1",
    }


@pytest.mark.asyncio
async def test_dispatch_sends_exactly_the_controls_the_cache_key_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The coupling that makes "the key describes what dispatch sends" checkable.

    INVARIANT: ``gateway_dispatch_controls()`` has exactly two readers — the projection
    and ``chat_completion``. This asserts the second one actually applies the table, so
    a control added to the wire cannot quietly stay out of the key.

    Captured at the ``litellm.acompletion`` boundary rather than at the HTTP wire on
    purpose: these are LiteLLM CONTROLS, most of which never appear as payload fields.
    The final wire is a separate observation layer with its own tests.
    """
    captured: list[dict[str, Any]] = []
    real_acompletion = litellm.acompletion

    async def capturing(**kwargs: Any) -> Any:
        captured.append(dict(kwargs))
        return await real_acompletion(**kwargs)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_response("gpt-5.6-sol"))

    _capture_client_factory(monkeypatch, handler)
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(litellm, "headers", None)
    monkeypatch.setattr(litellm, "acompletion", capturing)

    body = PLUGIN.prepare_chat_body(
        {"model": "openai/gpt-5.6-sol", "messages": [{"role": "user", "content": "ping"}]}
    )
    body["api_key"] = _SELECTED_KEY
    await PLUGIN.chat_completion(body)
    await asyncio.sleep(0.05)

    projected = PLUGIN.global_cache_projection(
        {"model": "openai/gpt-5.6-sol", "messages": [{"role": "user", "content": "ping"}]}
    )
    assert isinstance(projected, dict)
    prepared = projected["prepared"]
    assert len(captured) == 1
    for field, value in prepared.items():
        assert captured[0][field] == value, field
    # The caller's key is NOT among them: it is transport, injected into the client and
    # deliberately absent from both the projected controls and the acompletion kwargs.
    assert "api_key" not in captured[0]
    assert "api_key" not in prepared


# --- OME-884 review cycle 2: the coupling holds in BOTH directions -------------


@pytest.mark.asyncio
async def test_no_gateway_added_dispatch_kwarg_escapes_the_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The companion to the forward check — and the half that actually has teeth.

    Its sibling above proves ``prepared`` is a SUBSET of the ``acompletion`` kwargs, which
    a maintainer cannot break by ADDING to the wire. This proves the reverse inclusion, so
    the two together pin set EQUALITY. Without it, a future
    ``dispatch_body["something"] = ...`` written beside the shared
    ``.update(gateway_dispatch_controls())`` would change what OpenAI receives, leave the
    cache key untouched, and keep the entire suite green — silently reintroducing exactly
    the wrong-hit class ``GLOBAL_CACHE_ADAPTER_REVISION`` exists to prevent.

    INVARIANT: every ``acompletion`` kwarg is one of three things — a field the CALLER
    sent, a control the PROJECTION reports, or the transport ``client``. There is no
    fourth category, because a fourth category is by definition output-affecting state the
    key cannot see.
    """
    captured: list[dict[str, Any]] = []
    real_acompletion = litellm.acompletion

    async def capturing(**kwargs: Any) -> Any:
        captured.append(dict(kwargs))
        return await real_acompletion(**kwargs)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_response("gpt-5.6-sol"))

    clients, _constructor_kwargs, _http_client = _capture_client_factory(monkeypatch, handler)
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(litellm, "headers", None)
    monkeypatch.setattr(litellm, "acompletion", capturing)

    caller_body = {
        "model": "openai/gpt-5.6-sol",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 11,
    }
    body = PLUGIN.prepare_chat_body(dict(caller_body))
    body["api_key"] = _SELECTED_KEY
    await PLUGIN.chat_completion(body)
    await asyncio.sleep(0.05)

    projected = PLUGIN.global_cache_projection(dict(caller_body))
    assert isinstance(projected, dict)
    prepared = projected["prepared"]

    # Built from the three legitimate sources, never from the captured call itself — the
    # test must not be able to absorb a new kwarg by construction.
    expected = {key: value for key, value in body.items() if key != "api_key"}
    expected.update(prepared)
    assert len(captured) == 1
    assert set(captured[0]) == set(expected) | {"client"}, (
        "a dispatch kwarg exists that is neither caller-sent nor projected: "
        f"{sorted(set(captured[0]) - set(expected) - {'client'})}"
    )
    for key, value in expected.items():
        assert captured[0][key] == value, key
    assert captured[0]["client"] is clients[0]
    assert "api_key" not in captured[0]
