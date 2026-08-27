"""The verified OpenRouter OpenAPI slice, shared by the tests that read it.

WHY a module rather than a copy in each file: this is a slice of the REAL document
measured on 2026-07-28, and its value is that it was not invented. Two drifting
copies would quietly become two different documents, and the test that catches a
wrong component name would start passing against a fixture nobody checked.

AIDEV-NOTE: names keep their leading underscore so every test body that moved here
from ``test_openrouter_openapi_endpoint_source`` reads byte-for-byte as it did.
"""

from __future__ import annotations

import json
from typing import Any

from aigateway.core.chat_parameters import ProviderParameterObservation
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    RawResponse,
)
from aigateway.plugins.openrouter_provider.discovery import CHAT_REQUEST_SCHEMA

_UPSTREAM = "google/gemini-2.0-flash-001"
_MODEL = f"openrouter/{_UPSTREAM}"

# Slice of the VERIFIED live document (fetched and measured 2026-07-28). Every shape
# below is copied from it, not invented: the ``["number", "null"]`` type unions, the
# prose-only ranges, the ``anyOf`` on stop, the enum-plus-null on service_tier, and
# `route`'s deprecation hidden one `$ref` hop away in ``DeprecatedRoute``.
_OPENAPI: dict[str, Any] = {
    "openapi": "3.1.0",
    "components": {
        "schemas": {
            CHAT_REQUEST_SCHEMA: {
                "type": "object",
                "required": ["messages"],
                "properties": {
                    "model": {"$ref": "#/components/schemas/ModelName"},
                    "messages": {"type": "array"},
                    "stream": {"type": "boolean", "default": False},
                    "temperature": {
                        "description": "Sampling temperature (0-2)",
                        "format": "double",
                        "type": ["number", "null"],
                    },
                    "top_k": {"type": ["integer", "null"]},
                    "seed": {"type": ["integer", "null"]},
                    "stop": {
                        "anyOf": [
                            {"type": "string"},
                            {"items": {"type": "string"}, "maxItems": 4, "type": "array"},
                            {"type": "null"},
                        ],
                        "description": "Stop sequences (up to 4)",
                    },
                    "service_tier": {
                        "enum": ["auto", "default", "flex", None],
                        "type": ["string", "null"],
                    },
                    "tool_choice": {"$ref": "#/components/schemas/ChatToolChoice"},
                    "response_format": {
                        "description": "Response format configuration",
                        "discriminator": {"propertyName": "type"},
                        "oneOf": [{"$ref": "#/components/schemas/ChatFormatJsonObject"}],
                    },
                    "route": {"$ref": "#/components/schemas/DeprecatedRoute"},
                    "max_tokens": {
                        "description": "Maximum tokens (deprecated, use max_completion_tokens).",
                        "type": ["integer", "null"],
                    },
                },
            },
            "ModelName": {"type": "string"},
            "DeprecatedRoute": {
                "deprecated": True,
                "enum": ["fallback", "sort", None],
                "type": ["string", "null"],
                "x-speakeasy-deprecation-message": "Use providers.sort.partition instead",
            },
            "ChatToolChoice": {
                "anyOf": [
                    {"enum": ["none"], "type": "string"},
                    {"enum": ["auto"], "type": "string"},
                    {"$ref": "#/components/schemas/ChatNamedToolChoice"},
                ]
            },
            "ChatNamedToolChoice": {"type": "object"},
            "ChatFormatJsonObject": {"type": "object"},
        }
    },
}

_CATALOG = {
    "data": [
        {
            "id": _UPSTREAM,
            "supported_parameters": ["temperature", "max_tokens", "seed", "top_k"],
        }
    ]
}


def _by_path(obs: tuple[ProviderParameterObservation, ...]) -> dict[str, Any]:
    return {o.request_path: o for o in obs}


class _RoutingClient(DiscoveryHttpClient):
    """Canned JSON per URL; records the URL and bounds of every dial."""

    def __init__(self, bodies: dict[str, Any], *, fail: str | None = None) -> None:
        self._bodies = bodies
        self._fail = fail
        self.seen: list[tuple[str, float, int]] = []

    @property
    def calls(self) -> list[str]:
        return [url for url, _timeout, _max_bytes in self.seen]

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.seen.append((url, timeout_s, max_bytes))
        if self._fail == url:
            raise DiscoveryError("unreachable")
        if url not in self._bodies:
            # OME-972: LOUD on an unrouted URL. A KeyError here is caught by the
            # model catalog's foreign-exception guard and converted into a quiet
            # seed fallback, so a suite that accidentally starts dialing a new
            # document (e.g. the live model catalog) would keep passing for the
            # wrong reason. AssertionError propagates through every guard.
            raise AssertionError(f"canned client has no body for {url!r} — unexpected dial")
        return RawResponse(
            status=200, content_type="application/json", body=json.dumps(self._bodies[url])
        )
