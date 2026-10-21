"""Dispatch-path hardening for the Hugging Face provider (SF-345).

These lock the request-local invariants against litellm upgrades:
- the pinned ``api_base`` short-circuits litellm's env-keyed provider-mapping fetch
  (spying the call-site symbol, not ``common_utils``, because
  ``chat/transformation.py`` imports the name into its own module namespace);
- the injected per-request key wins over litellm's ``OPENAI_API_KEY`` /
  ``litellm.api_key`` / ``litellm.openai_key`` fallbacks, and the gateway never
  reaches those fallbacks (HF is not chatless);
- the prepared body (api_base + gateway key) is what actually reaches
  ``litellm.acompletion`` on both the sync and streaming paths.
"""

from __future__ import annotations

from unittest import mock

import litellm
import litellm.llms.huggingface.chat.transformation as hf_transformation
import pytest
from litellm.llms.huggingface.chat.transformation import HuggingFaceChatConfig

from aigateway.plugins.huggingface_provider.plugin import PLUGIN

_ROUTER = "https://router.huggingface.co/v1"
_MODEL = "huggingface/deepseek-ai/DeepSeek-R1:novita"


def test_pinned_api_base_short_circuits_provider_mapping() -> None:
    # Spy the CALL-SITE binding: transformation.py does
    # `from ..common_utils import _fetch_inference_provider_mapping`, so patching
    # common_utils alone would not be observed by transform_request. (getattr keeps
    # the dynamic access to litellm's private helper off pyright's private-import radar.)
    getattr(hf_transformation, "_fetch_inference_provider_mapping").cache_clear()
    cfg = HuggingFaceChatConfig()
    with mock.patch.object(hf_transformation, "_fetch_inference_provider_mapping") as spy:
        out = cfg.transform_request(
            model="deepseek-ai/DeepSeek-R1:novita",  # post-'huggingface/'-strip form
            messages=[{"role": "user", "content": "hi"}],
            optional_params={},
            litellm_params={"api_base": _ROUTER},
            headers={},
        )
    spy.assert_not_called()
    # Model is passed through verbatim (no env-keyed remap to a providerId).
    assert out["model"] == "deepseek-ai/DeepSeek-R1:novita"


def test_complete_url_is_unified_router() -> None:
    url = HuggingFaceChatConfig().get_complete_url(
        api_base=_ROUTER,
        api_key="hf_x",
        model="deepseek-ai/DeepSeek-R1:novita",
        optional_params={},
        litellm_params={},
    )
    assert url == "https://router.huggingface.co/v1/chat/completions"


def test_injected_key_wins_over_openai_env_poison(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-POISON")
    monkeypatch.setattr(litellm, "api_key", None, raising=False)
    monkeypatch.setattr(litellm, "openai_key", None, raising=False)
    # The gateway passes the stored HF key as the per-request api_key; it must win.
    assert HuggingFaceChatConfig.get_api_key("hf_stored") == "hf_stored"


def test_get_api_key_falls_back_to_openai_env_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Documents the dangerous fallback: with NO per-request key, litellm would use
    # OPENAI_API_KEY as the HF bearer. The gateway never hits this — it always
    # injects the stored key, and HF is not chatless (see test below).
    monkeypatch.setenv("OPENAI_API_KEY", "sk-POISON")
    monkeypatch.setattr(litellm, "api_key", None, raising=False)
    monkeypatch.setattr(litellm, "openai_key", None, raising=False)
    assert HuggingFaceChatConfig.get_api_key(None) == "sk-POISON"


def test_plugin_disallows_keyless_dispatch() -> None:
    # No stored profile/connection => the chat route 404s before dispatch, so the
    # env-key fallback above is never reachable through the gateway.
    assert PLUGIN.allows_chatless_credential() is False


@pytest.mark.asyncio
async def test_chat_completion_forwards_prepared_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    # Mirror the route: prepare the body (injects api_base + strips caller auth),
    # then inject the stored key exactly as routes/chat.py _inject_credentials does.
    body = PLUGIN.prepare_chat_body(
        {"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]}
    )
    body["api_key"] = "hf_stored"

    result = await PLUGIN.chat_completion(body)

    assert result == {"ok": True}
    assert captured["model"] == _MODEL
    assert captured["api_base"] == _ROUTER
    assert captured["api_key"] == "hf_stored"


@pytest.mark.asyncio
async def test_chat_completion_stream_yields_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream():
        yield "chunk-1"
        yield "chunk-2"

    async def fake_acompletion(**kwargs):
        assert kwargs["api_base"] == _ROUTER
        assert kwargs["api_key"] == "hf_stored"
        return fake_stream()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    body = PLUGIN.prepare_chat_body({"model": _MODEL, "messages": [], "stream": True})
    body["api_key"] = "hf_stored"

    chunks = [chunk async for chunk in PLUGIN.chat_completion_stream(body)]

    assert chunks == ["chunk-1", "chunk-2"]
