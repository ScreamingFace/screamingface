"""Embedded-vs-transport retry provenance (OME-428 CODE-2, plan D7/D9).

An error embedded in an already-returned HTTP-200 body means the upstream call
happened (and may already be billed): the gateway must NOT dispatch again —
exactly one upstream call, and no invented Retry-After for embedded JSON.
Actual transport 429/503 failures keep the shared overload-retry loop and
surface the provider's validated ``Retry-After`` on the final response.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from litellm.exceptions import RateLimitError, ServiceUnavailableError

from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_KEY = "sk-or-v1-retry"
_MODEL = "openrouter/anthropic/claude-fable-5"


@pytest.fixture()
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


@pytest.fixture()
def fast_retries(authenticated_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero out backoff/jitter so any retry loop runs instantly; the retry
    COUNT (the behavior under test) is unaffected."""
    settings = authenticated_client.app.state.settings
    monkeypatch.setattr(settings, "retry_backoff_base_seconds", 0.0)
    monkeypatch.setattr(settings, "retry_jitter_seconds", 0.0)


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


def _counting_payload_acompletion(payload: dict, calls: dict):
    async def fake_acompletion(**_kwargs):
        calls["n"] += 1
        return SimpleNamespace(model_dump=lambda: payload)

    return fake_acompletion


def _counting_raising_acompletion(make_exc, calls: dict):
    async def fake_acompletion(**_kwargs):
        calls["n"] += 1
        raise make_exc()

    return fake_acompletion


# --- Embedded errors: the upstream call already happened — never dispatch again ---


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [(429, "rate_limited"), (503, "provider_unavailable"), (529, "provider_unavailable")],
)
def test_embedded_overload_status_makes_exactly_one_upstream_call(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    authenticated_client,
    status: int,
    expected_code: str,
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")

    calls = {"n": 0}
    payload = {
        "id": f"gen-e{status}",
        "choices": [],
        "error": {"code": status, "message": "upstream overload"},
    }
    with patch("litellm.acompletion", _counting_payload_acompletion(payload, calls)):
        resp = _post_chat(authenticated_client)

    # INVARIANT (corrected findings): an error discovered after a response has
    # returned may not trigger another upstream call — exactly one dispatch.
    assert calls["n"] == 1
    assert resp.status_code == status
    assert resp.json()["detail"]["code"] == expected_code
    # The embedded-error schema was not shown to carry Retry-After; the
    # gateway must not invent one.
    assert "retry-after" not in resp.headers
    assert _active_labels(authenticated_client, account_id) == ["work-or"]


def test_embedded_401_makes_one_call_and_invalidates_effective_connection(
    enabled_openrouter, fast_retries, credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")

    calls = {"n": 0}
    payload = {"id": "gen-e401", "choices": [], "error": {"code": 401, "message": "bad key"}}
    with patch("litellm.acompletion", _counting_payload_acompletion(payload, calls)):
        resp = _post_chat(authenticated_client)

    assert calls["n"] == 1
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "auth_required"
    # D9 local: the effective connection flips to error.
    assert _active_labels(authenticated_client, account_id) == []


# --- Transport failures: the shared retry loop + validated Retry-After survive ---


# WHY (third-review blockers C + F): a REAL litellm-1.87.0 OpenRouter transport
# error exposes the wire ``Retry-After`` on ``exc.litellm_response_headers`` (its
# ``response.headers`` is empty) and carries an ``httpx.HTTPError`` cause. The
# cause is the positive transport proof; headers alone are metadata, not
# provenance. These fixtures were hardened to that real shape (owner-ratified
# 2026-07-20): the retry-count and Retry-After assertions below are unchanged.
def _with_wire_headers(exc, retry_after: str):
    exc.litellm_response_headers = {"retry-after": retry_after}
    status = exc.status_code
    request = httpx.Request("POST", "https://openrouter.ai/api/v1")
    exc.__cause__ = httpx.HTTPStatusError(
        str(status),
        request=request,
        response=httpx.Response(status, request=request),
    )
    return exc


def _transport_429() -> RateLimitError:
    return _with_wire_headers(
        RateLimitError(
            message="limited",
            llm_provider="openrouter",
            model=_MODEL,
            response=httpx.Response(
                429, request=httpx.Request("POST", "https://openrouter.ai/api/v1")
            ),
        ),
        "0",
    )


def _transport_503() -> ServiceUnavailableError:
    return _with_wire_headers(
        ServiceUnavailableError(
            message="overloaded",
            llm_provider="openrouter",
            model=_MODEL,
            response=httpx.Response(
                503, request=httpx.Request("POST", "https://openrouter.ai/api/v1")
            ),
        ),
        "0",
    )


def _ambiguous_overload() -> RateLimitError:
    """A 429-looking error with NO ``litellm_response_headers`` and NO cause
    chain: provenance is unprovable. This is the shape a synthetic/hand-built
    exception (or a future litellm variant) takes — the fail-closed policy
    (blocker F) must treat it as non-retryable, never as transport."""
    return RateLimitError(
        message="ambiguous",
        llm_provider="openrouter",
        model=_MODEL,
        response=httpx.Response(429, request=httpx.Request("POST", "https://openrouter.ai/api/v1")),
    )


@pytest.mark.parametrize(("status", "make_exc"), [(429, _transport_429), (503, _transport_503)])
def test_transport_overload_keeps_shared_retries_and_validated_retry_after(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    authenticated_client,
    status: int,
    make_exc,
) -> None:
    """A real transport 429/503 (litellm exception from a failed wire call) must
    keep the full shared retry budget and surface the provider's validated
    Retry-After hint on the final response — CODE-2 narrows retry only by
    provenance, never for genuine transport failures."""
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")
    settings = authenticated_client.app.state.settings

    calls = {"n": 0}
    with patch("litellm.acompletion", _counting_raising_acompletion(make_exc, calls)):
        resp = _post_chat(authenticated_client)

    assert calls["n"] == 1 + settings.retry_max_attempts
    assert resp.status_code == status
    # The provider's integer Retry-After survives validation end-to-end
    # (surfaced from litellm_response_headers — blocker C).
    assert resp.headers["retry-after"] == "0"
    assert _active_labels(authenticated_client, account_id) == ["work-or"]


def test_ambiguous_provenance_is_non_retryable_and_sanitized(
    enabled_openrouter, fast_retries, credential_blobs, authenticated_client
) -> None:
    """An overload-looking error with no PROVABLE transport provenance (no
    litellm_response_headers, no cause chain) is treated as a non-retryable
    body error: exactly one dispatch, a sanitized 502, and no fabricated
    Retry-After. Fail-closed policy (blocker F) — a future litellm shape can
    never be silently retried into an amplified upstream call."""
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")

    calls = {"n": 0}
    with patch("litellm.acompletion", _counting_raising_acompletion(_ambiguous_overload, calls)):
        resp = _post_chat(authenticated_client)

    assert calls["n"] == 1  # NOT retried
    assert resp.status_code == 502  # converter_error_status -> None -> sanitized 502
    assert resp.json()["detail"]["code"] == "provider_error"
    assert "retry-after" not in resp.headers
    assert _active_labels(authenticated_client, account_id) == ["work-or"]
