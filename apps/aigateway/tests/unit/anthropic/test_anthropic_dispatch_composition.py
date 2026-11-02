"""Phase 8c (OME-479 §6.3/§9 + SF-244): projection composes with Claude Code attribution.

FEATURE: Anthropic P1 — the DISPATCH side. CHARACTERIZATION: the OME-479 fail-closed
projection pipeline and the SF-244 Claude Code attribution/beta behavior COMPOSE at the
wire without disturbing each other. This locks the composition as a regression guard — no
new production code; the behavior already holds because attribution only rewrites
messages/system while projection only authorizes/relocates params (orthogonal concerns).

STORY: as a subscriber on an OAuth connection, the sampling params I send ride the Claude
Code billing path untouched; as a direct api-key caller, the native top_k I send reaches
Anthropic with NO spoofed billing block against my directly-billed key.

INVARIANT (SF-244 F02): the Claude-Code billing-header system block belongs ONLY on OAuth
(``sk-ant-oat``) traffic — a raw api-key request, EVEN one carrying a projected native
param, must never carry it.
INVARIANT (§6.3): the OAuth attribution rewrites ONLY messages/system, so the projected
params pass through and the SAME installed transform runs — which is why the standard
sampling params are enabled under both auth modes and top_k rides the api-key path.
"""

from __future__ import annotations

import httpx
import pytest

from aigateway.core.auth_types import AuthType
from aigateway.core.parameter_projection import classify_and_project_chat_parameters
from aigateway.core.request_hardening import strip_dispatch_controls
from aigateway.plugins.anthropic_provider.chat_handler import chat_completion
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin

pytestmark = pytest.mark.filterwarnings(
    "ignore:coroutine 'Logging.async_success_handler' was never awaited:RuntimeWarning"
)

_MODEL = "anthropic/claude-haiku-4-5"
_MESSAGES = [{"role": "user", "content": "Reply exactly: ready"}]


class FakeClient:
    # Captures the transformed request body/headers litellm puts on the wire — the
    # §9 last boundary. Same shape as tests/unit/anthropic/test_chat_handler.py.
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(
        self,
        url,
        *,
        headers=None,
        json=None,
        data=None,
        timeout=None,
        logging_obj=None,
        **_kwargs,
    ) -> httpx.Response:
        self.calls.append({"url": url, "headers": headers, "json": json, "data": data})
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5",
                "content": [{"type": "text", "text": "ready"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 7, "output_tokens": 3},
            },
        )


def _prepared(caller_body: dict, *, auth_mode: AuthType) -> dict:
    # The route pipeline (routes/chat.py), minus profile defaults: strip provider
    # controls → fail-closed classify/project → prepare_chat_body. The credential is
    # injected AFTER prepare (mirrored by the callers below), never as a caller param.
    plugin = AnthropicProviderPlugin()
    projected = classify_and_project_chat_parameters(
        plugin.strip_provider_dispatch_controls(strip_dispatch_controls(caller_body)),
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=auth_mode),
        auth_mode=auth_mode,
    )
    return plugin.prepare_chat_body(projected)


@pytest.mark.asyncio
async def test_projected_sampling_params_ride_the_oauth_attribution_path_to_the_wire() -> None:
    # OAuth: the projected sampling params AND the Claude Code billing/beta behavior
    # BOTH reach the wire — projection did not displace attribution, attribution did
    # not drop the params.
    client = FakeClient()
    body = _prepared(
        {
            "model": _MODEL,
            "messages": _MESSAGES,
            "temperature": 0.5,
            "max_tokens": 20,
            "top_p": 0.9,
        },
        auth_mode="oauth",
    )
    body.update({"api_key": "sk-ant-oat01-test", "client": client, "no-log": True})

    await chat_completion(body)

    sent = client.calls[-1]
    wire = sent["json"]
    # projected sampling params intact on the wire
    assert wire["temperature"] == 0.5
    assert wire["max_tokens"] == 20
    assert wire["top_p"] == 0.9
    # SF-244 attribution intact: billing-header system block + oauth beta header
    assert wire["system"][0]["text"].startswith("x-anthropic-billing-header:")
    headers = {str(k).lower(): v for k, v in (sent["headers"] or {}).items()}
    assert "oauth" in str(headers.get("anthropic-beta", ""))
    assert headers.get("authorization") == "Bearer sk-ant-oat01-test"


@pytest.mark.asyncio
async def test_api_key_native_top_k_reaches_wire_without_billing_header() -> None:
    # api-key: the projected NATIVE top_k reaches the wire, and — because the key is
    # not sk-ant-oat — NO Claude-Code billing block is injected (SF-244 F02 preserved
    # even in the presence of a projected native param).
    client = FakeClient()
    body = _prepared(
        {"model": _MODEL, "messages": _MESSAGES, "provider_params": {"top_k": 40}},
        auth_mode="api_key",
    )
    body.update({"api_key": "sk-ant-api03-raw-key", "client": client, "no-log": True})

    await chat_completion(body)

    sent = client.calls[-1]
    assert sent["json"]["top_k"] == 40
    assert "x-anthropic-billing-header" not in str(sent["json"])
    headers = {str(k).lower(): v for k, v in (sent["headers"] or {}).items()}
    assert headers["x-api-key"] == "sk-ant-api03-raw-key"
    assert "authorization" not in headers


@pytest.mark.asyncio
async def test_caller_oauth_header_cannot_replace_the_gateway_api_key() -> None:
    # INVARIANT: LiteLLM treats this exact lowercase/prefix combination as an
    # Anthropic OAuth credential. It must be gone before the installed transform.
    client = FakeClient()
    body = _prepared(
        {
            "model": _MODEL,
            "messages": _MESSAGES,
            "extra_headers": {"authorization": "Bearer sk-ant-oat01-attacker"},
        },
        auth_mode="api_key",
    )
    body.update({"api_key": "sk-ant-api03-gateway", "client": client, "no-log": True})

    await chat_completion(body)

    headers = {str(key).lower(): value for key, value in client.calls[-1]["headers"].items()}
    assert headers["x-api-key"] == "sk-ant-api03-gateway"
    assert "authorization" not in headers
