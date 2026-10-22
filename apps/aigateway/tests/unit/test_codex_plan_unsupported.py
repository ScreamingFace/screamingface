"""A Codex plan refusal reaches the caller as a typed 403 naming the plan (OME-1634).

FEATURE: Codex through the gateway (ChatGPT-account OAuth).
STORY: as a caller whose ChatGPT sign-in is on a plan without Codex, I am told that the
plan is the problem — not handed a 400 that reads like my request was malformed.

INVARIANT: only the plan refusal (upstream 400 + its marker text) is re-typed; every
other Codex error keeps today's status and `provider_error` detail. The new detail is
gateway-authored and never carries upstream text.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from litellm.llms.custom_llm import CustomLLMError

from aigateway.core.provider_error_text import plugin_error_message
from aigateway.plugins.codex_provider.plugin import CodexProviderPlugin

_HANDLER = "aigateway.plugins.codex_provider.plugin.get_litellm_codex_handler"
_REFUSAL = (
    "Codex upstream request failed with status 400: "
    '{"detail":"The \'gpt-5.4\' model is not supported when using Codex with a ChatGPT account."}'
)


def _jwt(auth_claims: dict[str, Any] | None) -> str:
    def seg(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    payload: dict[str, Any] = {"sub": "u"}
    if auth_claims is not None:
        payload["https://api.openai.com/auth"] = auth_claims
    return f"{seg({'alg': 'none'})}.{seg(payload)}.sig"


class _Raising:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def acompletion(self, **_kwargs: Any) -> Any:
        raise self._exc


async def _dispatch(exc: Exception, api_key: str) -> HTTPException:
    plugin = CodexProviderPlugin.__new__(CodexProviderPlugin)
    body = {"model": "codex/gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    body["api_key"] = api_key
    with patch(_HANDLER, return_value=_Raising(exc)), pytest.raises(HTTPException) as caught:
        await plugin.chat_completion(body)
    return caught.value


@pytest.mark.asyncio
async def test_plan_refusal_becomes_typed_403_naming_the_plan() -> None:
    err = await _dispatch(
        CustomLLMError(status_code=400, message=_REFUSAL), _jwt({"chatgpt_plan_type": "free"})
    )
    assert err.status_code == 403
    assert err.detail == {
        "code": "codex_model_unsupported",
        "provider": "codex",
        "model": "codex/gpt-5.4",
        "plan": "free",
        "message": (
            "Codex does not serve codex/gpt-5.4 to this ChatGPT account (plan: free). "
            "Pick a model the account lists, or sign in with a ChatGPT plan that includes it."
        ),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [_jwt(None), _jwt({"chatgpt_plan_type": 7}), "not-a-jwt"])
async def test_plan_is_unknown_when_the_token_does_not_say(api_key: str) -> None:
    err = await _dispatch(CustomLLMError(status_code=400, message=_REFUSAL), api_key)
    assert err.status_code == 403
    detail = err.detail
    assert isinstance(detail, dict)
    assert detail.get("plan") == "unknown"


@pytest.mark.asyncio
async def test_typed_detail_carries_no_upstream_text() -> None:
    err = await _dispatch(
        CustomLLMError(status_code=400, message=_REFUSAL), _jwt({"chatgpt_plan_type": "free"})
    )
    assert "upstream" not in json.dumps(err.detail)
    assert "gpt-5.4' model" not in json.dumps(err.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "message"),
    [
        (400, "Codex upstream request failed with status 400: bad input"),
        (429, "Codex upstream request failed with status 429"),
        (502, "Codex upstream did not complete response"),
        # INVARIANT: the marker text alone is not enough — the status must be 400 too.
        (500, _REFUSAL),
    ],
)
async def test_other_codex_errors_are_unchanged(status: int, message: str) -> None:
    api_key = _jwt({"chatgpt_plan_type": "free"})
    err = await _dispatch(CustomLLMError(status_code=status, message=message), api_key)
    assert err.status_code == status
    # WHY the screen: "unchanged" means main's OME-1136 provider_error mapping, which relays
    # the message through the plugin screen.
    assert err.detail == {
        "code": "provider_error",
        "message": plugin_error_message(message, status=status, forbidden=(api_key,)),
    }


def test_plan_refusal_does_not_mark_the_credential_errored() -> None:
    # WHY: the credential is valid; the plan is not. Marking it would force a re-auth that
    # cannot help unless the user picks a different account or upgrades.
    plugin = CodexProviderPlugin.__new__(CodexProviderPlugin)
    assert plugin.should_mark_credential_error_on_dispatch_status(403) is False
