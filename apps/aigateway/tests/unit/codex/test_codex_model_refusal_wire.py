"""The Codex model refusal survives the OME-1136 body screen, from the wire (OME-1634).

FEATURE: Codex through the gateway (ChatGPT-account OAuth).
STORY: as a caller refused a Codex model, I get the typed 403 even though the backend puts its
refusal in a top-level ``detail`` the generic error screen never reads.

INVARIANT: only the refusal sentence is recognised in ``detail``; any other ``detail`` text
stays withheld (the OME-1136 allowlist is unchanged for everything else).
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from aigateway.plugins.codex_provider.chat_handler import CodexCustomLLM
from aigateway.plugins.codex_provider.plugin import CodexProviderPlugin

_HANDLER = "aigateway.plugins.codex_provider.plugin.get_litellm_codex_handler"
_REFUSAL_BODY = {
    "detail": "The 'gpt-5.4' model is not supported when using Codex with a ChatGPT account."
}


def _handler_answering(status: int, body: dict[str, Any]) -> CodexCustomLLM:
    transport = httpx.MockTransport(lambda _request: httpx.Response(status, json=body))
    return CodexCustomLLM(
        http_client_factory=lambda: httpx.AsyncClient(transport=transport, timeout=5.0)
    )


async def _dispatch(status: int, body: dict[str, Any]) -> HTTPException:
    plugin = CodexProviderPlugin.__new__(CodexProviderPlugin)
    request = {
        "model": "codex/gpt-5.4",
        "messages": [{"role": "user", "content": "hi"}],
        "api_key": "oauth-token",
    }
    with (
        patch(_HANDLER, return_value=_handler_answering(status, body)),
        pytest.raises(HTTPException) as caught,
    ):
        await plugin.chat_completion(request)
    return caught.value


@pytest.mark.asyncio
async def test_wire_refusal_becomes_the_typed_403() -> None:
    err = await _dispatch(400, _REFUSAL_BODY)
    assert err.status_code == 403
    detail = cast("dict[str, Any]", err.detail)
    assert detail["code"] == "codex_model_unsupported"
    assert detail["plan"] == "unknown"


@pytest.mark.asyncio
async def test_other_detail_text_stays_withheld() -> None:
    err = await _dispatch(400, {"detail": "internal shard 7f3 rejected tenant acme"})
    assert err.status_code == 400
    detail = cast("dict[str, Any]", err.detail)
    assert detail["code"] == "provider_error"
    assert "shard" not in str(detail)


@pytest.mark.asyncio
async def test_refusal_sentence_on_another_status_is_not_typed() -> None:
    err = await _dispatch(403, _REFUSAL_BODY)
    assert err.status_code == 403
    assert cast("dict[str, Any]", err.detail)["code"] == "provider_error"
