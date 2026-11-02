from __future__ import annotations

import copy

MODEL = "openrouter/openai/gpt-5.5"

SUMMARY = {
    "id": MODEL,
    "object": "model",
    "owned_by": "openrouter",
    "supported_parameters": ["max_tokens", "temperature"],
    "supported_tools": ["function"],
    "unsupported_parameter_behavior": "reject",
    "parameter_contract_url": "/v1/model-parameters?model=openrouter%2Fopenai%2Fgpt-5.5",
}

DETAILS = {
    "schema_version": 1,
    "contract_id": "pc_fixture",
    "model": {
        "id": MODEL,
        "gateway_provider": "openrouter",
        "upstream_id": "openai/gpt-5.5",
    },
    "context": {
        "scope": "account_connection",
        "auth_mode": "api_key",
        "revision": "ctx_fixture",
        "source_revision": "openrouter-models-v1",
    },
    "parameters": {
        "max_tokens": {
            "request_path": "max_tokens",
            "schema": {"type": "integer", "minimum": 1},
            "provider": {
                "support": "supported",
                "source": "openrouter-model-catalog",
                "stale": False,
                "deprecated": False,
            },
            "gateway": {
                "status": "enabled",
                "projection": "direct",
                "cache_behavior": "bypass",
                "applicable_auth_modes": ["api_key"],
            },
        },
        "temperature": {
            "request_path": "temperature",
            "schema": {"type": "number", "minimum": 0, "maximum": 2},
            "provider": {
                "support": "supported",
                "source": "openrouter-model-catalog",
                "stale": False,
                "deprecated": False,
            },
            "gateway": {
                "status": "enabled",
                "projection": "direct",
                "cache_behavior": "bypass",
                "applicable_auth_modes": ["api_key"],
            },
        },
        "reasoning_effort": {
            "request_path": "reasoning_effort",
            "schema": {"type": "string", "enum": ["low", "medium", "high"]},
            "provider": {
                "support": "unknown",
                "source": "gateway-local",
                "stale": False,
                "deprecated": None,
            },
            "gateway": {
                "status": "disabled",
                "reason": "not available under this auth mode",
                "cache_behavior": "bypass",
                "applicable_auth_modes": ["oauth"],
            },
        },
    },
    "tools": {"function": {"provider_support": "supported", "gateway_status": "enabled"}},
    "transport": {
        "stream": {
            "provider_support": "unknown",
            "gateway_status": "disabled",
            "reason": "streaming is disabled",
        }
    },
    "freshness": {
        "observed_at": "2026-08-05T10:00:00Z",
        "expires_at": "2026-08-05T10:05:00Z",
        "stale": False,
        "degraded": False,
    },
}


def details(model: str) -> dict[str, object]:
    """Return a complete fixture contract rewritten for one canonical Model id."""

    value = copy.deepcopy(DETAILS)
    provider, upstream = model.split("/", 1)
    value["model"] = {
        "id": model,
        "gateway_provider": provider,
        "upstream_id": upstream,
    }
    return value
