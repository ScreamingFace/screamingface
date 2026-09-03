"""OpenRouter local BYOK error policy (OME-428 Phase 4, plan D9/D10).

Pins: a dispatch 401 invalidates ONLY the selected account connection;
402/403/408/429/5xx never invalidate a valid key; embedded errors inside a
nominal HTTP-200 body surface as sanitized gateway errors (numeric status
through the sanitizer, malformed/status-less -> 502, raw provider
message/metadata discarded); and native usage/cost/generation metadata
survives untouched (D10 — URL4 per-leaf telemetry depends on it).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from litellm.exceptions import (
    APIError,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    UnprocessableEntityError,
)

from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_KEY = "sk-or-v1-err"
_MODEL = "openrouter/anthropic/claude-fable-5"


@pytest.fixture()
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _create_connection(client, label: str) -> None:
    resp = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": label, "api_key": _KEY},
    )
    assert resp.status_code == 201, resp.text


def _active_labels(client, account_id: str) -> list[str]:
    async def _list() -> list[str]:
        connections = await OAuthConnectionStore().list(
            account_id, provider="openrouter", status="active"
        )
        return sorted(connection.label for connection in connections)

    return client.portal.call(_list)


def _post_chat(client, *, profile: str | None = None):
    headers = {"X-Profile": profile} if profile is not None else {}
    return client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )


def _raising_acompletion(exc: Exception):
    async def fake_acompletion(**_kwargs):
        raise exc

    return fake_acompletion


def _returning_acompletion(payload: dict):
    async def fake_acompletion(**_kwargs):
        return SimpleNamespace(model_dump=lambda: payload)

    return fake_acompletion


_WIRE_REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1")


def _as_transport(exc: Exception, *, wire_status: int | None) -> Exception:
    """Attach the provenance signals a REAL litellm OpenRouter transport failure
    carries, so the fail-closed classifier PROVES transport and the error keeps
    its true status + invalidation policy.

    # WHY (third-review blocker F, owner-ratified 2026-07-20): litellm wraps a
    # genuine wire failure by chaining ``httpx.HTTPStatusError`` (reachable via
    # Python's ``__cause__`` chain — the classifier walks ``__cause__``/
    # ``__context__``) AND, when a response exists, surfacing the wire headers on
    # ``litellm_response_headers``. Both signals are attached — not one alone.
    # A litellm exception built directly in a test carries NEITHER, so without
    # this it would read as ambiguous -> sanitized 502; that is a unit-test
    # artifact, never a production shape (real transport always carries both).
    """
    if wire_status is not None:
        response = httpx.Response(wire_status, request=_WIRE_REQUEST)
        exc.__cause__ = httpx.HTTPStatusError(
            f"{wire_status}", request=_WIRE_REQUEST, response=response
        )
        exc.litellm_response_headers = dict(response.headers)  # type: ignore[attr-defined]
    else:
        # A client-side timeout/connect error chains an httpx transport error but
        # has no wire response, so no response headers exist to surface.
        exc.__cause__ = httpx.ReadTimeout("timed out", request=_WIRE_REQUEST)
    return exc


# --- D9 local: 401 invalidates only the selected connection ---


def test_dispatch_401_marks_only_selected_connection(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")
    _create_connection(authenticated_client, "backup-or")

    exc = _as_transport(
        AuthenticationError(
            message="Invalid credentials",
            llm_provider="openrouter",
            model=_MODEL,
        ),
        wire_status=401,
    )
    with patch("litellm.acompletion", _raising_acompletion(exc)):
        resp = _post_chat(authenticated_client, profile="work-or")

    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "auth_required"
    # Only the selected connection flipped to error; the other stays usable.
    assert _active_labels(authenticated_client, account_id) == ["backup-or"]


@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        (
            _as_transport(
                APIError(
                    status_code=402,
                    message="Payment Required",
                    llm_provider="openrouter",
                    model=_MODEL,
                ),
                wire_status=402,
            ),
            402,
        ),
        (
            _as_transport(
                APIError(
                    status_code=403,
                    message="Forbidden",
                    llm_provider="openrouter",
                    model=_MODEL,
                ),
                wire_status=403,
            ),
            403,
        ),
        (
            _as_transport(
                PermissionDeniedError(
                    message="Forbidden",
                    llm_provider="openrouter",
                    model=_MODEL,
                    response=httpx.Response(403, request=_WIRE_REQUEST),
                ),
                wire_status=403,
            ),
            403,
        ),
        (
            _as_transport(
                NotFoundError(
                    message="Not Found",
                    llm_provider="openrouter",
                    model=_MODEL,
                    response=httpx.Response(404, request=_WIRE_REQUEST),
                ),
                wire_status=404,
            ),
            404,
        ),
        (
            _as_transport(
                UnprocessableEntityError(
                    message="Unprocessable Entity",
                    llm_provider="openrouter",
                    model=_MODEL,
                    response=httpx.Response(422, request=_WIRE_REQUEST),
                ),
                wire_status=422,
            ),
            422,
        ),
        (
            _as_transport(
                InternalServerError(
                    message="Internal Server Error",
                    llm_provider="openrouter",
                    model=_MODEL,
                    response=httpx.Response(500, request=_WIRE_REQUEST),
                ),
                wire_status=500,
            ),
            500,
        ),
        (
            _as_transport(
                Timeout(message="timed out", model=_MODEL, llm_provider="openrouter"),
                wire_status=None,
            ),
            408,
        ),
        (
            _as_transport(
                RateLimitError(
                    message="limited",
                    llm_provider="openrouter",
                    model=_MODEL,
                    response=httpx.Response(429, request=_WIRE_REQUEST),
                ),
                wire_status=429,
            ),
            429,
        ),
        (
            _as_transport(
                ServiceUnavailableError(
                    message="overloaded",
                    llm_provider="openrouter",
                    model=_MODEL,
                    response=httpx.Response(503, request=_WIRE_REQUEST),
                ),
                wire_status=503,
            ),
            503,
        ),
    ],
)
def test_non_401_failures_never_invalidate_the_key(
    enabled_openrouter, credential_blobs, authenticated_client, exc: Exception, expected_status: int
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")

    with (
        patch("litellm.acompletion", _raising_acompletion(exc)),
        patch("aigateway.core.retry.asyncio.sleep", new_callable=AsyncMock),
    ):
        resp = _post_chat(authenticated_client)

    assert resp.status_code == expected_status
    assert _active_labels(authenticated_client, account_id) == ["work-or"]


def test_signalless_ambiguous_exception_is_non_retryable_sanitized_502(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    """A litellm exception with NO provenance signals — no ``__cause__``/
    ``__context__`` chain and no ``litellm_response_headers`` — is unprovable.
    The fail-closed classifier (blocker F) treats it as a non-retryable body
    error: exactly ONE dispatch, a sanitized 502 ``provider_error``, no
    fabricated Retry-After, and no credential invalidation — even though its
    status LOOKS like a retryable 429. This is the shape a future litellm
    variant could take; it must never be silently retried into an amplified,
    already-billed upstream call. Contrast the transport fixtures above, which
    carry the wire signals ``_as_transport`` attaches."""
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")

    # 429-looking, but built directly: no chain and no litellm_response_headers.
    exc = RateLimitError(
        message="ambiguous",
        llm_provider="openrouter",
        model=_MODEL,
        response=httpx.Response(429, request=_WIRE_REQUEST),
    )
    calls = {"n": 0}

    async def _counting(**_kwargs):
        calls["n"] += 1
        raise exc

    with (
        patch("litellm.acompletion", _counting),
        patch("aigateway.core.retry.asyncio.sleep", new_callable=AsyncMock),
    ):
        resp = _post_chat(authenticated_client)

    assert calls["n"] == 1  # NOT retried despite a 429-looking status
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "provider_error"
    assert "retry-after" not in resp.headers
    assert _active_labels(authenticated_client, account_id) == ["work-or"]


def test_arbitrary_chained_status_is_ambiguous_502_without_invalidation(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")
    context = Exception("unrelated")
    context.status_code = 401  # type: ignore[attr-defined]
    outer = RuntimeError("unclassified")
    outer.__cause__ = context
    calls = {"n": 0}

    async def _counting(**_kwargs):
        calls["n"] += 1
        raise outer

    with patch("litellm.acompletion", _counting):
        resp = _post_chat(authenticated_client)

    assert calls["n"] == 1
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "provider_error"
    assert _active_labels(authenticated_client, account_id) == ["work-or"]


# --- D9: embedded HTTP-200 errors are sanitized, numeric status preserved ---


def test_embedded_top_level_error_is_sanitized_and_does_not_invalidate(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")

    payload = {
        "id": "gen-1",
        "choices": [],
        "error": {
            "code": 402,
            "message": "Insufficient credits: topping up at https://internal",
            "metadata": {"provider_name": "secret-internal-router"},
        },
    }
    with patch("litellm.acompletion", _returning_acompletion(payload)):
        resp = _post_chat(authenticated_client)

    assert resp.status_code == 402
    # OME-927: a 402 gets its own dedicated code/message instead of the generic
    # "provider_error" fallback, so the client can tell the caller to top up.
    assert resp.json()["detail"]["code"] == "insufficient_credits"
    assert (
        resp.json()["detail"]["message"] == "The upstream provider reported insufficient credits."
    )
    # Raw provider message/metadata is discarded, never echoed.
    assert "Insufficient credits" not in resp.text
    assert "secret-internal-router" not in resp.text
    assert _active_labels(authenticated_client, account_id) == ["work-or"]


def test_embedded_401_error_marks_the_selected_connection(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")

    payload = {"id": "gen-2", "choices": [], "error": {"code": 401, "message": "User not found."}}
    with patch("litellm.acompletion", _returning_acompletion(payload)):
        resp = _post_chat(authenticated_client)

    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "auth_required"
    assert "User not found" not in resp.text
    assert _active_labels(authenticated_client, account_id) == []


def test_embedded_choice_error_with_native_finish_reason_maps_status(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    """LiteLLM 1.87.0 maps native finish_reason "error" to "stop"; the gateway
    must still surface the failure instead of rendering it as success."""
    _create_connection(authenticated_client, "work-or")

    payload = {
        "id": "gen-3",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": ""},
                "provider_specific_fields": {"native_finish_reason": "error"},
                "error": {"code": 502, "message": "Provider returned error: upstream boom"},
            }
        ],
    }
    with patch("litellm.acompletion", _returning_acompletion(payload)):
        resp = _post_chat(authenticated_client)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "provider_unavailable"
    assert "upstream boom" not in resp.text


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "gen-4", "choices": [], "error": {"message": "boom without status"}},
        {"id": "gen-5", "choices": [], "error": {"code": "not-a-status", "message": "boom"}},
        {"id": "gen-6", "choices": [], "error": "opaque failure string"},
        {
            "id": "gen-7",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": ""},
                    "provider_specific_fields": {"native_finish_reason": "error"},
                }
            ],
        },
    ],
)
def test_embedded_statusless_or_malformed_errors_map_to_502(
    enabled_openrouter, credential_blobs, authenticated_client, payload: dict
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")

    with patch("litellm.acompletion", _returning_acompletion(payload)):
        resp = _post_chat(authenticated_client)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "provider_error"
    assert "boom" not in resp.text
    assert _active_labels(authenticated_client, account_id) == ["work-or"]


# --- D10: native usage/cost/metadata pass through untouched ---


def test_native_usage_cost_and_metadata_preserved(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client, "work-or")

    payload = {
        "id": "gen-or-123456",
        "model": "anthropic/claude-fable-5",
        "provider": "Anthropic",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "hello"},
                "provider_specific_fields": {"native_finish_reason": "end_turn"},
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cost": 0.00021,
            "cost_details": {"upstream_inference_cost": 0.0002},
            "is_byok": True,
        },
    }
    with patch("litellm.acompletion", _returning_acompletion(payload)):
        resp = _post_chat(authenticated_client)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.pop("_aigw")["usage_accounting"]["schema"] == "aigw.chat_usage_accounting"
    assert body == payload
