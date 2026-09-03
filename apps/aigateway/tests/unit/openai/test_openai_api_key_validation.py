"""Two-stage, bounded direct OpenAI API-key validation."""

from __future__ import annotations

import json
from collections.abc import Iterable

import httpx
import pytest

from aigateway.core.api_key_validation import ApiKeyValidationStage, ApiKeyValidationState
from aigateway.plugins.openai_provider.api_key_validation import OpenAIApiKeyValidator
from aigateway.plugins.openai_provider.plugin import OpenAIProviderPlugin
from aigateway.plugins.openai_provider.settings import OpenAIPluginSettings

_KEY = "sk-synthetic-openai-validation-key"


def _validator(
    responses: Iterable[httpx.Response],
    *,
    settings: OpenAIPluginSettings | None = None,
) -> tuple[OpenAIApiKeyValidator, list[httpx.Request]]:
    queued = list(responses)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return queued.pop(0)

    return (
        OpenAIApiKeyValidator(
            settings=settings or OpenAIPluginSettings(),
            transport=httpx.MockTransport(handler),
        ),
        requests,
    )


@pytest.mark.asyncio
async def test_validation_authenticates_then_proves_chat_readiness() -> None:
    validator, requests = _validator(
        [
            httpx.Response(200, json={"object": "list", "data": []}),
            httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            ),
        ]
    )

    result = await validator.validate(_KEY)

    assert result.state is ApiKeyValidationState.VALID
    assert result.stage is ApiKeyValidationStage.READINESS
    assert result.probe_model == "openai/gpt-5-nano"
    assert [str(request.url) for request in requests] == [
        "https://api.openai.com/v1/models",
        "https://api.openai.com/v1/chat/completions",
    ]
    assert all(request.headers["authorization"] == f"Bearer {_KEY}" for request in requests)
    assert json.loads(requests[1].content) == {
        "model": "gpt-5-nano",
        "max_completion_tokens": 16,
        "stream": False,
        "messages": [{"role": "user", "content": "ping"}],
    }
    assert _KEY not in repr(result)


@pytest.mark.asyncio
async def test_length_limited_reasoning_response_with_empty_content_is_ready() -> None:
    validator, _requests = _validator(
        [
            httpx.Response(200, json={"object": "list", "data": []}),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"role": "assistant", "content": ""},
                        }
                    ]
                },
            ),
        ]
    )

    result = await validator.validate(_KEY)

    assert result.state is ApiKeyValidationState.VALID
    assert result.stage is ApiKeyValidationStage.READINESS


@pytest.mark.parametrize("stage", list(ApiKeyValidationStage))
@pytest.mark.asyncio
async def test_exact_invalid_key_tuple_is_actionable(
    stage: ApiKeyValidationStage,
) -> None:
    responses = []
    if stage is ApiKeyValidationStage.READINESS:
        responses.append(httpx.Response(200, json={"object": "list", "data": []}))
    responses.append(
        httpx.Response(
            401,
            json={
                "error": {
                    "message": _KEY,
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        )
    )
    validator, requests = _validator(responses)

    result = await validator.validate(_KEY)

    assert result.state is ApiKeyValidationState.INVALID
    assert result.stage is stage
    assert len(requests) == (2 if stage is ApiKeyValidationStage.READINESS else 1)
    assert _KEY not in repr(result)


@pytest.mark.parametrize(
    "code",
    [
        "credit_balance_exhausted",
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
        "organization_usage_limit_exceeded",
    ],
)
@pytest.mark.asyncio
async def test_exact_documented_billing_tuples_are_no_quota_on_readiness(code: str) -> None:
    validator, _requests = _validator(
        [
            httpx.Response(200, json={"object": "list", "data": []}),
            httpx.Response(
                429,
                json={
                    "error": {
                        "message": _KEY,
                        "type": "insufficient_quota",
                        "code": code,
                    }
                },
            ),
        ]
    )

    result = await validator.validate(_KEY)

    assert result.state is ApiKeyValidationState.NO_QUOTA
    assert result.stage is ApiKeyValidationStage.READINESS
    assert _KEY not in repr(result)


@pytest.mark.parametrize(
    ("status", "error_type", "code"),
    [
        (429, "insufficient_quota", "insufficient_quota"),
        (429, "requests", "rate_limit_exceeded"),
        (429, None, None),
        (401, "invalid_request_error", "expired_api_key"),
        (403, "permission_error", "permission_denied"),
        (404, "invalid_request_error", "model_not_found"),
    ],
)
@pytest.mark.asyncio
async def test_unapproved_or_ambiguous_error_tuples_are_unavailable(
    status: int,
    error_type: str | None,
    code: str | None,
) -> None:
    validator, _requests = _validator(
        [
            httpx.Response(200, json={"object": "list", "data": []}),
            httpx.Response(
                status,
                headers={"retry-after": "17"},
                json={"error": {"message": _KEY, "type": error_type, "code": code}},
            ),
        ]
    )

    result = await validator.validate(_KEY)

    assert result.state is ApiKeyValidationState.UNAVAILABLE
    assert result.stage is ApiKeyValidationStage.READINESS
    assert result.retry_after_seconds is None
    assert _KEY not in repr(result)


@pytest.mark.asyncio
async def test_authentication_failure_stops_before_readiness() -> None:
    validator, requests = _validator([httpx.Response(200, json={"object": "list", "data": {}})])

    result = await validator.validate(_KEY)

    assert result.state is ApiKeyValidationState.UNAVAILABLE
    assert result.stage is ApiKeyValidationStage.AUTHENTICATION
    assert len(requests) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"error": {}}]},
        {"choices": [{"message": "not-an-object"}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"role": "assistant"}}]},
        {
            "error": {"type": "invalid_request_error", "code": "invalid_api_key"},
            "choices": [{"message": {"content": "not-success"}}],
        },
    ],
)
@pytest.mark.asyncio
async def test_malformed_http_200_readiness_never_authorizes_persistence(payload: dict) -> None:
    validator, _requests = _validator(
        [
            httpx.Response(200, json={"object": "list", "data": []}),
            httpx.Response(200, json=payload),
        ]
    )

    result = await validator.validate(_KEY)

    assert result.state is ApiKeyValidationState.UNAVAILABLE
    assert result.stage is ApiKeyValidationStage.READINESS


@pytest.mark.asyncio
async def test_a_validation_model_outside_the_bootstrap_catalog_is_probed_normally() -> None:
    """OME-884 (authorized contract change): publication does not govern readiness.

    OME-864 required the readiness model to appear in ``default_models`` and reported
    ``MISCONFIGURED`` otherwise — which meant an operator who unpublished a model from
    the ``/v1/models`` catalog silently broke API-key validation for every profile,
    without having touched anything about validation. ``default_models`` is the
    bootstrap catalog; which models are PUBLISHED is not a fact about which model may
    be PROBED. Route-valid syntax is still required — see the malformed case below.
    """
    settings = OpenAIPluginSettings(
        default_models=["openai/gpt-5.6-sol"],
        validation_model="openai/gpt-5-nano",
    )
    assert settings.validation_model not in settings.default_models
    validator, requests = _validator(
        [
            httpx.Response(200, json={"object": "list", "data": []}),
            httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            ),
        ],
        settings=settings,
    )

    result = await validator.validate(_KEY)

    assert result.state is ApiKeyValidationState.VALID
    assert result.stage is ApiKeyValidationStage.READINESS
    assert result.probe_model == "openai/gpt-5-nano"
    assert json.loads(requests[1].content)["model"] == "gpt-5-nano"


@pytest.mark.asyncio
async def test_a_malformed_validation_model_is_misconfigured_without_network() -> None:
    # Still a LOCAL misconfiguration, and still refused before a socket is opened: a
    # model id the grammar rejects could never reach OpenAI, so probing with it would
    # only trade a clear operator error for an opaque upstream one.
    settings = OpenAIPluginSettings.model_construct(
        enabled=True,
        default_models=["openai/gpt-5.6-sol"],
        validation_model="openai/gpt 5",
    )
    validator, requests = _validator([], settings=settings)

    result = await validator.validate(_KEY)

    assert result.state is ApiKeyValidationState.MISCONFIGURED
    assert result.stage is None
    assert requests == []


def test_plugin_exposes_operational_validator() -> None:
    assert isinstance(OpenAIProviderPlugin().api_key_validator(), OpenAIApiKeyValidator)
