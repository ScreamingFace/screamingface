"""Owner-gated direct OpenAI API-key readiness smoke (OME-864).

Skipped unless AIGW_LIVE=1 and OPENAI_API_KEY are both present. Requests can
consume quota; the credential is passed only to production validation/dispatch
paths and is never included in assertions.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from aigateway.core.api_key_validation import ApiKeyValidationStage, ApiKeyValidationState
from aigateway.plugins.openai_provider.api_key_validation import OpenAIApiKeyValidator
from aigateway.plugins.openai_provider.plugin import PLUGIN
from aigateway.plugins.openai_provider.settings import OpenAIPluginSettings

pytestmark = pytest.mark.live


def _live_enabled() -> bool:
    return os.environ.get("AIGW_LIVE") == "1"


def _seed_sweep_enabled() -> bool:
    return _live_enabled() and os.environ.get("AIGW_LIVE_OPENAI_SEED_SWEEP") == "1"


def _live_openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        pytest.skip("Live OpenAI test requires OPENAI_API_KEY")
    assert key is not None
    return key


@pytest.mark.skipif(not _live_enabled(), reason="AIGW_LIVE=1 not set")
@pytest.mark.asyncio
async def test_openai_api_key_reaches_reasoning_model_readiness() -> None:
    result = await OpenAIApiKeyValidator(settings=OpenAIPluginSettings()).validate(
        _live_openai_key()
    )

    # INVARIANT: a key is persistable only after the configured model produces
    # a structurally valid Chat Completions response, not after listing models.
    assert result.state is ApiKeyValidationState.VALID
    assert result.stage is ApiKeyValidationStage.READINESS
    assert result.probe_model == "openai/gpt-5-nano"


@pytest.mark.skipif(
    not _seed_sweep_enabled(),
    reason="AIGW_LIVE=1 and AIGW_LIVE_OPENAI_SEED_SWEEP=1 not set",
)
@pytest.mark.asyncio
async def test_every_openai_seed_reaches_chat_completions() -> None:
    api_key = _live_openai_key()

    for model in OpenAIPluginSettings().default_models:
        body = PLUGIN.prepare_chat_body(
            {
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 16,
            }
        )
        body["api_key"] = api_key

        result = await PLUGIN.chat_completion(body)
        await asyncio.sleep(0.05)

        assert result["object"] == "chat.completion", model
        assert isinstance(result.get("choices"), list), model


@pytest.mark.skipif(not _live_enabled(), reason="AIGW_LIVE=1 not set")
def test_openai_key_completes_through_gateway_route(authenticated_client: TestClient) -> None:
    api_key = _live_openai_key()
    created = authenticated_client.put(
        "/v1/auth/openai/profiles/default/api-key",
        json={"api_key": api_key},
    )
    assert created.status_code == 200, created.text
    assert api_key not in created.text

    response = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-5.6-luna",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 16,
        },
    )

    assert response.status_code == 200, response.text
    assert api_key not in response.text
    assert response.json()["object"] == "chat.completion"
    assert response.headers["X-AIGW-Cache"] == "bypass"
