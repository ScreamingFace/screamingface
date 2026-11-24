"""Every LiteLLM chat provider honours the injected observed client (contract C7 stop condition).

# FEATURE: Router Recipe extension Unit 5.1 — `X-AIGW-Upstream-Attempts` counts physical sends;
# for a LiteLLM provider those sends happen inside LiteLLM, so the count exists only when LiteLLM
# sends through the client the Gateway injected.
# INVARIANT: a provider that ignored the injected client would fail `refuse_unobserved_client`;
# that is the C7 stop condition, never a count of `0`.
# INVARIANT: the count needs no usage-accounting collector; none is bound in these tests.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from aigateway.core.plugin_base import ProviderPluginBase
from aigateway.core.upstream_attempts import UpstreamAttempts, bound_attempts, record_send
from aigateway.core.usage_accounting.hooks import (
    AccountingAsyncHTTPHandler,
    build_accounting_handler,
    build_attempt_handler,
)
from aigateway.core.usage_accounting.signals import active_collector
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin
from aigateway.plugins.huggingface_provider.plugin import HuggingFaceProviderPlugin
from aigateway.plugins.ollama_provider.plugin import OllamaProviderPlugin
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin

from .litellm_seam import (
    ANTHROPIC_MESSAGE,
    HF_MODEL,
    OLLAMA_CHAT,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OPENAI_COMPLETION,
    connect_error_then,
    install_fake_transport,
    quiet_litellm,
    refuse_unobserved_client,
)

PROVIDERS = {
    "huggingface": (HuggingFaceProviderPlugin, HF_MODEL, OPENAI_COMPLETION),
    "ollama": (OllamaProviderPlugin, OLLAMA_MODEL, OLLAMA_CHAT),
    "anthropic": (AnthropicProviderPlugin, "anthropic/claude-3-haiku-20240307", ANTHROPIC_MESSAGE),
    "openrouter": (OpenRouterProviderPlugin, "openrouter/openai/gpt-4o-mini", OPENAI_COMPLETION),
}


@pytest.fixture
def seam(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("OLLAMA_HOST", OLLAMA_HOST)
    quiet_litellm(monkeypatch)
    refuse_unobserved_client(monkeypatch)
    return install_fake_transport(monkeypatch)


async def _dispatch(plugin: ProviderPluginBase, model: str, client: Any) -> None:
    body = plugin.prepare_chat_body(
        {"model": model, "messages": [{"role": "user", "content": "hello"}], "max_tokens": 1}
    )
    body.setdefault("api_base", "https://provider.example/v1")
    await plugin.chat_completion({**body, "api_key": "test-key", "client": client})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "factory"),
    [("attempt", build_attempt_handler), ("accounting", build_accounting_handler)],
)
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_one_send_through_the_injected_client_is_one_attempt(
    seam: Any, provider: str, name: str, factory: Any
) -> None:
    plugin_cls, model, payload = PROVIDERS[provider]
    seam.respond = lambda _request: httpx.Response(200, json=payload)
    handler = factory()
    counter = UpstreamAttempts()
    try:
        with bound_attempts(counter):
            assert active_collector() is None
            await _dispatch(plugin_cls(), model, handler)
    finally:
        await handler.close()

    assert len(seam.sent) == 1, name
    assert counter.count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_litellm_s_hidden_resend_is_a_second_attempt(seam: Any, provider: str) -> None:
    plugin_cls, model, payload = PROVIDERS[provider]
    seam.respond = connect_error_then(payload)
    handler = build_attempt_handler()
    counter = UpstreamAttempts()
    try:
        with bound_attempts(counter):
            await _dispatch(plugin_cls(), model, handler)
    finally:
        await handler.close()

    assert len(seam.sent) == 2, "LiteLLM no longer resends after a connect error; premise changed"
    assert counter.count == 2


@pytest.mark.asyncio
async def test_a_send_outside_any_bound_counter_counts_nowhere(seam: Any) -> None:
    seam.respond = lambda _request: httpx.Response(200, json=OPENAI_COMPLETION)
    handler = build_attempt_handler()
    counter = UpstreamAttempts()
    try:
        await _dispatch(HuggingFaceProviderPlugin(), HF_MODEL, handler)
    finally:
        await handler.close()

    assert (len(seam.sent), counter.count) == (1, 0)


@pytest.mark.asyncio
async def test_the_attempt_handler_is_the_accounting_class_with_only_the_attempt_hook() -> None:
    # WHY the same class: LiteLLM's replacement client and its pinned TLS come from one place.
    handler = build_attempt_handler()
    replacement = handler.create_client(timeout=None, event_hooks=None)
    try:
        assert type(handler) is AccountingAsyncHTTPHandler
        hooks = handler.client.event_hooks
        assert hooks == {"request": [record_send], "response": []}
        assert replacement.event_hooks == hooks
    finally:
        await replacement.aclose()
        await handler.close()


@pytest.mark.asyncio
async def test_the_accounting_handler_counts_before_it_looks_for_a_collector() -> None:
    handler = build_accounting_handler()
    counter = UpstreamAttempts()
    try:
        request = httpx.Request("POST", "https://provider.example/v1/chat/completions")
        with bound_attempts(counter):
            for hook in handler.client.event_hooks["request"]:
                await hook(request)
    finally:
        await handler.close()

    assert (active_collector(), counter.count) == (None, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_without_an_injected_client_litellm_reaches_for_its_own(
    seam: Any, provider: str
) -> None:
    # WHY: the control for every test above. It proves `refuse_unobserved_client` guards the path
    # this provider would take with no injection, so a passing test above is a real observation.
    plugin_cls, model, payload = PROVIDERS[provider]
    seam.respond = lambda _request: httpx.Response(200, json=payload)
    counter = UpstreamAttempts()
    with bound_attempts(counter), pytest.raises(Exception) as raised:
        await _dispatch(plugin_cls(), model, None)

    # OpenRouter maps every provider failure to a sanitized 502; the refusal is in its chain.
    chain: list[BaseException] = []
    error: BaseException | None = raised.value
    while error is not None and len(chain) < 10:
        chain.append(error)
        error = error.__cause__ or error.__context__
    assert any("ignored the injected client" in str(link) for link in chain)
    assert (seam.sent, counter.count) == ([], 0)
