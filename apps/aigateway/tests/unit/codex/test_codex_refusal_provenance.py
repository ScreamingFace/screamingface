"""The Codex model refusal is typed only from its trusted carrier (OME-1634, PR #1441 review).

FEATURE: Codex through the gateway (ChatGPT-account OAuth).
STORY: as a caller whose ordinary 400 happens to quote the refusal sentence in its
``error.message``, I keep the ordinary 400 — I am not told my account cannot use the model,
and the gateway does not spend a credentialed model-list read on my behalf.

INVARIANT: the backend's TOP-LEVEL ``detail`` is the one authoritative refusal carrier. The
marker sentence anywhere else (``error.message``, or an ``error.message`` that mimics the
detail shape) never re-types the error. When both are present, ``detail`` wins.
INVARIANT: the ``plan`` named in the 403 is a short identifier from the token, else
``unknown`` — never an arbitrary token-declared string.
"""

from __future__ import annotations

import base64
import json
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from aigateway.plugins.codex_provider.auth import plan_type_from_token
from aigateway.plugins.codex_provider.chat_handler import (
    CodexCustomLLM,
    _status_error_from_exception,
)
from aigateway.plugins.codex_provider.plugin import CodexProviderPlugin, _is_model_refusal

_HANDLER = "aigateway.plugins.codex_provider.plugin.get_litellm_codex_handler"
_LIST_READ = "aigateway.plugins.codex_provider.plugin.available_models_for"
_MARKER_IN_MESSAGE = {
    "error": {
        "message": "An unrelated field is not supported when using Codex with a ChatGPT account"
    }
}
_MIMIC_IN_MESSAGE = {
    "error": {"message": '{"detail":"x is not supported when using Codex with a ChatGPT account"}'}
}
_DETAIL = "The 'gpt-5.4' model is not supported when using Codex with a ChatGPT account."


def _handler_answering(status: int, body: dict[str, Any]) -> CodexCustomLLM:
    transport = httpx.MockTransport(lambda _request: httpx.Response(status, json=body))
    return CodexCustomLLM(
        http_client_factory=lambda: httpx.AsyncClient(transport=transport, timeout=5.0)
    )


async def _dispatch(status: int, body: dict[str, Any]) -> tuple[HTTPException, AsyncMock]:
    plugin = CodexProviderPlugin.__new__(CodexProviderPlugin)
    request = {
        "model": "codex/gpt-5.4",
        "messages": [{"role": "user", "content": "hi"}],
        "api_key": "oauth-token",
    }
    list_read = AsyncMock(return_value=None)
    with (
        patch(_HANDLER, return_value=_handler_answering(status, body)),
        patch(_LIST_READ, list_read),
        pytest.raises(HTTPException) as caught,
    ):
        await plugin.chat_completion(request)
    return caught.value, list_read


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [_MARKER_IN_MESSAGE, _MIMIC_IN_MESSAGE])
async def test_marker_in_error_message_is_not_retyped(body: dict[str, Any]) -> None:
    err, list_read = await _dispatch(400, body)
    assert err.status_code == 400
    assert cast("dict[str, Any]", err.detail)["code"] == "provider_error"
    # WHY: a mis-typed refusal also costs a credentialed model-list request.
    list_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_top_level_detail_wins_over_an_unrelated_error_message() -> None:
    body = {"error": {"message": "something else went wrong"}, "detail": _DETAIL}
    err, list_read = await _dispatch(400, body)
    assert err.status_code == 403
    assert cast("dict[str, Any]", err.detail)["code"] == "codex_model_unsupported"
    list_read.assert_awaited_once()


@pytest.mark.parametrize(
    ("body", "typed"),
    [(_MARKER_IN_MESSAGE, False), (_MIMIC_IN_MESSAGE, False), ({"detail": _DETAIL}, True)],
)
def test_status_exception_path_types_only_the_detail_carrier(
    body: dict[str, Any], *, typed: bool
) -> None:
    request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
    response = httpx.Response(400, json=body, request=request)
    exc = httpx.HTTPStatusError("bad", request=request, response=response)
    assert _is_model_refusal(_status_error_from_exception(exc)) is typed


def _jwt(plan: object) -> str:
    def seg(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    claims = {"https://api.openai.com/auth": {"chatgpt_plan_type": plan}}
    return f"{seg({'alg': 'none'})}.{seg(claims)}.sig"


@pytest.mark.parametrize("plan", ["free", "plus", "pro", "team", "enterprise", "edu"])
def test_short_plan_identifiers_are_named(plan: str) -> None:
    assert plan_type_from_token(_jwt(plan)) == plan


@pytest.mark.parametrize(
    "plan",
    ["x" * 415, "internal tier / shard 7f3", "Plus", "plus\n", "-plus"],
    ids=["415-chars", "free-text", "uppercase", "control-char", "leading-dash"],
)
def test_other_plan_claims_are_not_named(plan: str) -> None:
    assert plan_type_from_token(_jwt(plan)) is None
