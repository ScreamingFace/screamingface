"""Each provider-owned inference transport counts its sends (contract C7).

# FEATURE: Router Recipe extension Unit 5.1, test-plan §4 item 8 — one fake send through every
# `plugin_http` family: local, OpenAI, Gemini, Codex and Antigravity. The remote endpoint is proven
# through the real app in `tests/unit/remote_endpoint/test_app_upstream_attempts.py`.
# INVARIANT: each plugin builds its client exactly as production does; only the default HTTPX
# transport is replaced, so a client built without the observer would send uncounted.
# INVARIANT: project setup and OAuth calls are not inference sends and are not counted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from litellm.types.utils import ModelResponse

from aigateway.core.parameter_discovery import RawResponse
from aigateway.core.upstream_attempts import UpstreamAttempts, bound_attempts
from aigateway.plugins.antigravity_provider.auth import ANTIGRAVITY_PROFILE_HEADER
from aigateway.plugins.antigravity_provider.chat_handler import AntigravityCustomLLM
from aigateway.plugins.antigravity_provider.settings import AntigravityPluginSettings
from aigateway.plugins.codex_provider.chat_handler import CodexCustomLLM
from aigateway.plugins.gemini_provider.auth import GEMINI_PROFILE_HEADER
from aigateway.plugins.gemini_provider.chat_handler import GeminiCustomLLM
from aigateway.plugins.local_provider.plugin import LocalProviderPlugin
from aigateway.plugins.local_provider.settings import LocalPluginSettings
from aigateway.plugins.openai_provider.plugin import OpenAIProviderPlugin

from .litellm_seam import OPENAI_COMPLETION, quiet_litellm

Responder = Callable[[httpx.Request], httpx.Response]


class DefaultTransport:
    """Every client built with the default HTTPX transport sends here."""

    def __init__(self) -> None:
        self.sent: list[httpx.Request] = []
        self.respond: Responder = lambda _request: httpx.Response(500)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        self.sent.append(request)
        return self.respond(request)


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> DefaultTransport:
    fake = DefaultTransport()

    async def handle_async_request(
        transport: httpx.AsyncHTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        del transport
        return await fake.handle(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_async_request)
    quiet_litellm(monkeypatch)
    return fake


def _verbs(sent: list[httpx.Request]) -> list[str]:
    return [request.url.path.rsplit(":", 1)[-1] for request in sent]


def _custom_llm_call(**overrides: Any) -> dict[str, Any]:
    call: dict[str, Any] = {
        "messages": [{"role": "user", "content": "ping"}],
        "api_base": None,
        "custom_prompt_dict": {},
        "model_response": ModelResponse(),
        "print_verbose": lambda *_args, **_kwargs: None,
        "encoding": None,
        "logging_obj": None,
        "optional_params": {},
    }
    return {**call, **overrides}


def _gemini_answer(text: str = "pong") -> dict[str, Any]:
    return {
        "candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
    }


def _setup_or(answer: dict[str, Any]) -> Responder:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":loadCodeAssist"):
            return httpx.Response(200, json={"cloudaicompanionProject": "project-1"})
        return httpx.Response(200, json=answer)

    return respond


@pytest.mark.asyncio
async def test_local_counts_its_one_send(wire: DefaultTransport) -> None:
    wire.respond = lambda _request: httpx.Response(200, json=OPENAI_COMPLETION)

    class Discovery:
        async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
            del url, timeout_s, max_bytes
            body = json.dumps({"object": "list", "data": [{"id": "fixture:model"}]})
            return RawResponse(status=200, content_type="application/json", body=body)

    plugin = LocalProviderPlugin(LocalPluginSettings(enabled=True))
    await plugin.discover_live_models(client=Discovery())
    body = plugin.prepare_chat_body(
        {"model": "local/fixture:model", "messages": [{"role": "user", "content": "ping"}]}
    )
    counter = UpstreamAttempts()
    with bound_attempts(counter):
        await plugin.chat_completion(body)

    assert (len(wire.sent), counter.count) == (1, 1)


@pytest.mark.asyncio
async def test_openai_counts_its_one_send(wire: DefaultTransport) -> None:
    wire.respond = lambda _request: httpx.Response(200, json=OPENAI_COMPLETION)
    plugin = OpenAIProviderPlugin()
    body = plugin.prepare_chat_body(
        {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "ping"}]}
    )
    counter = UpstreamAttempts()
    with bound_attempts(counter):
        await plugin.chat_completion({**body, "api_key": "sk-test"})

    assert (len(wire.sent), counter.count) == (1, 1)


@pytest.mark.asyncio
async def test_gemini_counts_the_api_key_send(
    wire: DefaultTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    wire.respond = lambda _request: httpx.Response(200, json=_gemini_answer())
    counter = UpstreamAttempts()
    with bound_attempts(counter):
        await GeminiCustomLLM().acompletion(
            **_custom_llm_call(model="gemini-cli/gemini-2.5-flash", api_key=None)
        )

    assert (_verbs(wire.sent), counter.count) == (["generateContent"], 1)


@pytest.mark.asyncio
async def test_gemini_counts_the_oauth_inference_send_and_not_its_setup(
    wire: DefaultTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    wire.respond = _setup_or({"response": _gemini_answer()})
    counter = UpstreamAttempts()
    with bound_attempts(counter):
        await GeminiCustomLLM().acompletion(
            **_custom_llm_call(
                model="gemini-cli/gemini-2.5-flash",
                api_key="ya29.oauth",
                headers={GEMINI_PROFILE_HEADER: "acct:default"},
            )
        )

    assert (_verbs(wire.sent), counter.count) == (["loadCodeAssist", "generateContent"], 1)


@pytest.mark.asyncio
async def test_codex_counts_its_one_send(wire: DefaultTransport) -> None:
    completed = {
        "type": "response.completed",
        "response": {
            "id": "resp_1",
            "created_at": 1,
            "model": "gpt-5.4-mini",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "pong"}],
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    }
    sse = f"event: response.completed\ndata: {json.dumps(completed)}\n\ndata: [DONE]\n\n"
    wire.respond = lambda _request: httpx.Response(
        200, text=sse, headers={"content-type": "text/event-stream"}
    )
    counter = UpstreamAttempts()
    with bound_attempts(counter):
        await CodexCustomLLM().acompletion(
            **_custom_llm_call(model="codex/gpt-5.4-mini", api_key="oauth-token")
        )

    assert (len(wire.sent), counter.count) == (1, 1)


@pytest.mark.asyncio
async def test_antigravity_counts_the_inference_send_and_not_its_setup(
    wire: DefaultTransport,
) -> None:
    wire.respond = _setup_or({"response": _gemini_answer()})
    counter = UpstreamAttempts()
    with bound_attempts(counter):
        await AntigravityCustomLLM(settings=AntigravityPluginSettings()).acompletion(
            **_custom_llm_call(
                model="antigravity/gemini-3-flash",
                api_key="ya29.oauth",
                headers={ANTIGRAVITY_PROFILE_HEADER: "acct:default"},
            )
        )

    assert (_verbs(wire.sent), counter.count) == (["loadCodeAssist", "generateContent"], 1)


@pytest.mark.asyncio
async def test_antigravity_counts_each_host_it_tries(wire: DefaultTransport) -> None:
    settings = AntigravityPluginSettings()
    assert settings.code_assist_fallback_endpoint != settings.code_assist_endpoint
    primary = httpx.URL(settings.code_assist_endpoint).host
    setup = _setup_or({"response": _gemini_answer()})

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":generateContent") and request.url.host == primary:
            return httpx.Response(503, json={"error": {"message": "down"}})
        return setup(request)

    wire.respond = respond
    counter = UpstreamAttempts()
    with bound_attempts(counter):
        await AntigravityCustomLLM(settings=settings).acompletion(
            **_custom_llm_call(
                model="antigravity/gemini-3-flash",
                api_key="ya29.oauth",
                headers={ANTIGRAVITY_PROFILE_HEADER: "acct:default"},
            )
        )

    assert _verbs(wire.sent) == ["loadCodeAssist", "generateContent", "generateContent"]
    assert counter.count == 2
