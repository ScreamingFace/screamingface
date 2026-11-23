"""A real LiteLLM dispatch whose physical sends land on a fake transport (contract C7).

# WHY the transport and nothing else: patching `AsyncHTTPHandler._create_async_transport` keeps
# every other client property real, so LiteLLM's hidden resend and its replacement client run
# exactly as in production. The same seam the accounting handler tests use.
# WHY `refuse_unobserved_client`: LiteLLM falls back to its own cached client when it ignores the
# `client` it was given; failing that fallback is what proves a provider honours the injection.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import litellm
import pytest
from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

Responder = Callable[[httpx.Request], httpx.Response]

HF_MODEL = "huggingface/deepseek-ai/DeepSeek-R1:novita"
OLLAMA_MODEL = "ollama/llama3.2:1b"
OLLAMA_HOST = "http://ollama.example:11434"

OPENAI_COMPLETION: dict[str, Any] = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "m",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}
ANTHROPIC_MESSAGE: dict[str, Any] = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-3-haiku-20240307",
    "content": [{"type": "text", "text": "ok"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 1, "output_tokens": 1},
}
OLLAMA_CHAT: dict[str, Any] = {
    "model": "llama3.2:1b",
    "created_at": "2026-01-01T00:00:00Z",
    "message": {"role": "assistant", "content": "ok"},
    "done": True,
    "done_reason": "stop",
    "prompt_eval_count": 1,
    "eval_count": 1,
}


class FakeTransport:
    """Every client LiteLLM builds sends here; ``sent`` holds each physical request."""

    def __init__(self) -> None:
        self.sent: list[httpx.Request] = []
        self.respond: Responder = lambda _request: httpx.Response(500)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        return self.respond(request)


def install_fake_transport(monkeypatch: pytest.MonkeyPatch) -> FakeTransport:
    fake = FakeTransport()

    def transport(
        ssl_context: Any = None, ssl_verify: Any = None, shared_session: Any = None
    ) -> httpx.MockTransport:
        del ssl_context, ssl_verify, shared_session
        return httpx.MockTransport(fake.handle)

    monkeypatch.setattr(AsyncHTTPHandler, "_create_async_transport", staticmethod(transport))
    return fake


def refuse_unobserved_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("LiteLLM ignored the injected client")

    for owner in (
        "litellm.llms.custom_httpx.llm_http_handler",
        "litellm.llms.anthropic.chat.handler",
    ):
        monkeypatch.setattr(f"{owner}.get_async_httpx_client", refuse)


def quiet_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    """No callback, alias, fallback or background logging may add or reroute a send."""
    for field in (
        "pre_call_rules",
        "post_call_rules",
        "callbacks",
        "input_callback",
        "success_callback",
        "failure_callback",
        "_async_input_callback",
        "_async_success_callback",
        "_async_failure_callback",
    ):
        monkeypatch.setattr(litellm, field, [], raising=False)
    monkeypatch.setattr(litellm, "model_fallbacks", None, raising=False)
    monkeypatch.setattr(litellm, "model_alias_map", {}, raising=False)

    def discard(async_coroutine: Any) -> None:
        async_coroutine.close()

    monkeypatch.setattr(GLOBAL_LOGGING_WORKER, "ensure_initialized_and_enqueue", discard)


def connect_error_then(payload: dict[str, Any]) -> Responder:
    """The first send fails to connect; LiteLLM's hidden resend gets ``payload``."""
    calls = {"n": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=payload)

    return respond
