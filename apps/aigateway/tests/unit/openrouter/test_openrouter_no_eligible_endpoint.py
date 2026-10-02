"""OME-651: what strict routing BUYS — an explicit, sanitized refusal.

FEATURE: gateway-owned OpenRouter strict routing. Because the gateway pins
``provider.require_parameters``, OpenRouter refuses a request no endpoint can
serve in full rather than silently dropping the parameter. This file covers the
caller-visible half of that bargain: the refusal reaches the caller as a refusal.

INVARIANT: the refusal is never laundered into a success. It arrives in two
shapes — a transport error, and an error object embedded in an HTTP 200 body —
and both must surface as 404. A gateway that read only the HTTP status would
hand back a "successful" completion with no choices, which is the silent discard
in a new costume.
INVARIANT: the provider's raw text and any named internal endpoint stay OUT of
the response. The caller learns that the request was refused, not who refused it.

The policy itself — that it is present on every dispatch, that a caller cannot
override it, and its final-wire-JSON proof — lives in
``test_openrouter_strict_routing``.

AIDEV-NOTE: the harness below is a verbatim copy of that module's, except that
``_raising_acompletion`` and ``_returning_acompletion`` MOVED here rather than
being copied — nothing in the policy module uses them.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from litellm.exceptions import NotFoundError

from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_KEY = "sk-or-v1-strict"
_MODEL = "openrouter/anthropic/claude-fable-5"
_MESSAGES: list[Any] = [{"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def _api_key_validation_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # Explicit test double (per tests/unit/conftest.py AIDEV-NOTE): key readiness
    # is not what strict routing exercises.
    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(_self, _plugin, _provider, _api_key) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


@pytest.fixture()
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


def _create_connection(client) -> None:
    resp = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "work-openrouter", "api_key": _KEY},
    )
    assert resp.status_code == 201, resp.text


def _raising_acompletion(exc: Exception):
    async def fake_acompletion(**_kwargs):
        raise exc

    return fake_acompletion


def _returning_acompletion(payload: dict):
    async def fake_acompletion(**_kwargs):
        return SimpleNamespace(model_dump=lambda: payload)

    return fake_acompletion


def _post_chat(client, body: dict[str, Any] | None = None):
    payload = {"model": _MODEL, "messages": list(_MESSAGES), **(body or {})}
    return client.post("/v1/chat/completions", json=payload)


# --------------------------------------------------------------------------
# no eligible endpoint → an explicit, sanitized refusal
# --------------------------------------------------------------------------


_WIRE_REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1")


def _as_transport(exc: Exception, *, wire_status: int) -> Exception:
    # Mirrors the provenance a real litellm OpenRouter transport failure carries
    # (chained httpx.HTTPStatusError + surfaced wire headers), so the fail-closed
    # classifier reads it as transport rather than as an ambiguous 502.
    response = httpx.Response(wire_status, request=_WIRE_REQUEST)
    exc.__cause__ = httpx.HTTPStatusError(
        f"{wire_status}", request=_WIRE_REQUEST, response=response
    )
    exc.litellm_response_headers = dict(response.headers)  # type: ignore[attr-defined]
    return exc


def test_no_eligible_endpoint_transport_error_surfaces_sanitized_never_a_success(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # This is the OUTCOME strictness buys: when no endpoint declares support for
    # every supplied parameter, OpenRouter refuses with 404 rather than serving a
    # request that would have dropped the parameter. The gateway must pass that
    # refusal through explicitly — the raw provider text and any named internal
    # endpoint stay out of the response.
    _create_connection(authenticated_client)
    exc = _as_transport(
        NotFoundError(
            message=(
                "No endpoints found that support all parameters: top_k. "
                "Tried provider secret-internal-router."
            ),
            llm_provider="openrouter",
            model=_MODEL,
            response=httpx.Response(404, request=_WIRE_REQUEST),
        ),
        wire_status=404,
    )
    with patch("litellm.acompletion", _raising_acompletion(exc)):
        resp = _post_chat(authenticated_client, {"provider_params": {"top_k": 40}})

    assert resp.status_code == 404, resp.text
    assert resp.status_code != 200
    assert "secret-internal-router" not in resp.text
    assert "No endpoints found" not in resp.text


def test_no_eligible_endpoint_embedded_in_a_200_body_surfaces_sanitized(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # The second shape of the same refusal: OpenRouter answers HTTP 200 with a
    # top-level error object. A gateway that only checked the HTTP status would hand
    # the caller a "successful" completion with no choices — the silent discard in a
    # new costume. The embedded error must win.
    _create_connection(authenticated_client)
    payload = {
        "id": "gen-strict",
        "choices": [],
        "error": {
            "code": 404,
            "message": "No endpoints found that support all parameters: n",
            "metadata": {"provider_name": "secret-internal-router"},
        },
    }
    with patch("litellm.acompletion", _returning_acompletion(payload)):
        resp = _post_chat(authenticated_client, {"n": 2})

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "provider_error"
    # OME-1136: the provider message is relayed only sanitized.
    assert (
        resp.json()["detail"]["upstream_message"]
        == "No endpoints found that support all parameters: n"
    )
    assert "secret-internal-router" not in resp.text
