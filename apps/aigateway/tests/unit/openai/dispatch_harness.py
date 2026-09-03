"""The no-network harness the direct-OpenAI dispatch suites share.

WHY a module rather than a fixture in one suite: four cohesive suites drive the SAME
outbound request and must all observe it the same way — the fail-closed suite
(``test_openai_dispatch``), the wire characterization (``test_openai_dispatch_wire``), the
projection/dispatch coupling proof (``test_openai_dispatch_controls``) and the ambient
modifier's asymmetry (``test_openai_runtime_modifier``). One harness is what makes their
observations comparable; a copy per suite would let them drift apart silently.

INVARIANT: no network. ``capture_client_factory`` installs an ``httpx.MockTransport``, so
a test that reaches a real socket is a bug in the test, not a slow test.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from aigateway.plugins.openai_provider import plugin as plugin_module

SELECTED_KEY = "sk-synthetic-selected-account-key"


def completion_response(model: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def capture_client_factory(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[list[AsyncOpenAI], list[dict[str, Any]], httpx.AsyncClient]:
    """Patch in a mock-transport client and record every constructor call.

    Returns the constructed clients, the kwargs each was built with, and the single shared
    ``httpx.AsyncClient`` — three views of the same dispatch, because the suites need
    different ones: the wire wants the transport, the coupling proof wants the kwargs.
    """
    clients: list[AsyncOpenAI] = []
    constructor_kwargs: list[dict[str, Any]] = []
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
    )

    def factory(**kwargs: Any) -> AsyncOpenAI:
        constructor_kwargs.append(dict(kwargs))
        client = AsyncOpenAI(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(plugin_module, "_openai_http_client", lambda: http_client)
    monkeypatch.setattr(plugin_module, "AsyncOpenAI", factory)
    return clients, constructor_kwargs, http_client
