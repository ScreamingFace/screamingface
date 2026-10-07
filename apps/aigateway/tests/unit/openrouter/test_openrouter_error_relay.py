"""OME-1136: a rejected OpenRouter call relays the provider's sanitized explanation.

Drives REAL ``litellm.acompletion`` over a mocked wire (``httpx.AsyncClient.send``), so the
litellm-1.87 exception shapes — a synthetic empty ``exc.response``, the wire body only on the
chained ``httpx.HTTPStatusError`` — are the ones under test, not a hand-built stand-in.

FEATURE (OME-1136): the report names the cause of a rejected model call.
INVARIANT: the relay is ADDITIVE (`upstream_status`, `upstream_message`, composed `message`);
the code taxonomy and retry behaviour are unchanged; an unusable body leaves the response
byte-identical to before; 401/429 never relay; nothing relayed reaches a log line or the
credential's persisted error state.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings
from aigateway.routes import chat_dispatch

_KEY = "sk-or-v1-relay"
_MODEL = "openrouter/openai/gpt-6-astra"
_TEMPERATURE = "Unsupported parameter: 'temperature' is not supported with this model."
_CONTRACT = (
    Path(__file__).resolve().parents[2] / "fixtures/provider_error_relay/relayed_detail.json"
)


@pytest.fixture()
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


@pytest.fixture()
def fast_retries(authenticated_client, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = authenticated_client.app.state.settings
    monkeypatch.setattr(settings, "retry_backoff_base_seconds", 0.0)
    monkeypatch.setattr(settings, "retry_jitter_seconds", 0.0)


@pytest.fixture()
def connection(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    valid_api_key_readiness,
    authenticated_client,
) -> Any:
    resp = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "work-or", "api_key": _KEY},
    )
    assert resp.status_code == 201, resp.text
    return authenticated_client


def _wire(monkeypatch: pytest.MonkeyPatch, status: int, content: bytes, calls: dict) -> None:
    async def fake_send(self, request, *args, **kwargs):  # noqa: ANN001
        if request.method == "POST":
            calls["n"] += 1
        return httpx.Response(
            status_code=status,
            headers={"content-type": "application/json"},
            content=content,
            request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)


def _error_body(message: Any, code: int | None = None, **metadata: Any) -> bytes:
    error: dict[str, Any] = {"message": message}
    if code is not None:
        error["code"] = code
    if metadata:
        error["metadata"] = metadata
    return json.dumps({"error": error}).encode()


def _post(client) -> httpx.Response:
    return client.post(
        "/v1/chat/completions",
        json={"model": _MODEL, "messages": [{"role": "user", "content": "hi"}], "temperature": 0.0},
    )


# --- case 1: the relay itself ----------------------------------------------------------


def test_unsupported_parameter_400_relays_the_provider_text(connection, monkeypatch) -> None:
    calls = {"n": 0}
    _wire(monkeypatch, 400, _error_body(_TEMPERATURE, 400), calls)

    resp = _post(connection)

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail == {
        "code": "bad_request",
        "message": f"The upstream provider rejected the request (400): {_TEMPERATURE}",
        "upstream_status": 400,
        "upstream_message": _TEMPERATURE,
    }
    # The engine contract test (apps/screamingface-engine) consumes exactly this detail.
    assert detail == json.loads(_CONTRACT.read_text(encoding="utf-8"))
    assert len(detail["message"]) <= 200


# --- case 2: the OpenRouter wrapper ----------------------------------------------------


def test_account_gate_403_relays_metadata_raw(connection, monkeypatch) -> None:
    raw = json.dumps({"error": {"message": "This model requires age verification"}})
    body = _error_body("Provider returned error", 403, raw=raw, provider_name="Meta")
    _wire(monkeypatch, 403, body, {"n": 0})

    resp = _post(connection)

    assert resp.status_code == 403
    assert resp.json()["detail"] == {
        "code": "provider_error",
        "message": (
            "The upstream provider returned an error (403): This model requires age verification"
        ),
        "upstream_status": 403,
        "upstream_message": "This model requires age verification",
    }


@pytest.mark.parametrize(
    ("status", "code", "generic"),
    [
        (402, "insufficient_credits", "The upstream provider reported insufficient credits"),
        (404, "provider_error", "The upstream provider returned an error"),
    ],
)
def test_every_relay_code_relays(connection, monkeypatch, status, code, generic) -> None:
    _wire(monkeypatch, status, _error_body("Account balance too low", status), {"n": 0})

    detail = _post(connection).json()["detail"]

    assert detail["code"] == code
    assert detail["message"] == f"{generic} ({status}): Account balance too low"
    assert detail["upstream_status"] == status


# --- case 3: an error embedded in an HTTP-200 body --------------------------------------


def test_converter_raised_embedded_error_relays_and_stays_single_dispatch(
    connection, monkeypatch
) -> None:
    calls = {"n": 0}
    _wire(monkeypatch, 200, _error_body(_TEMPERATURE, 400), calls)

    resp = _post(connection)

    assert calls["n"] == 1  # non-retryable: the upstream call already happened
    assert resp.status_code == 400
    assert resp.json()["detail"] == {
        "code": "bad_request",
        "message": f"OpenRouter reported a provider error (400): {_TEMPERATURE}",
        "upstream_status": 400,
        "upstream_message": _TEMPERATURE,
    }


def test_scanned_embedded_error_relays(connection) -> None:
    from types import SimpleNamespace

    payload = {
        "id": "gen-1",
        "choices": [{"index": 0, "error": {"code": 402, "message": "Insufficient credits"}}],
    }

    async def fake_acompletion(**_kwargs):
        return SimpleNamespace(model_dump=lambda: payload)

    with patch("litellm.acompletion", fake_acompletion):
        resp = _post(connection)

    assert resp.status_code == 402
    assert resp.json()["detail"] == {
        "code": "insufficient_credits",
        "message": (
            "The upstream provider reported insufficient credits (402): Insufficient credits"
        ),
        "upstream_status": 402,
        "upstream_message": "Insufficient credits",
    }


# --- case 4: an unusable body leaves the response byte-identical ------------------------


@pytest.mark.parametrize(
    "content",
    [
        b"<html>502 Bad Gateway</html>",
        b"{not json",
        json.dumps(["an", "array"]).encode(),
        _error_body("x" * (16 * 1024), 400),
        _error_body("Provider returned error", 400, raw="not json"),
    ],
    ids=["html", "invalid-json", "json-array", "over-16KiB", "raw-not-json"],
)
def test_garbage_body_keeps_the_legacy_detail(connection, monkeypatch, content) -> None:
    _wire(monkeypatch, 400, content, {"n": 0})

    resp = _post(connection)

    assert resp.status_code == 400
    assert resp.json()["detail"] == {
        "code": "bad_request",
        "message": "The upstream provider rejected the request.",
    }


# --- case 5: the poisoned body ----------------------------------------------------------

_HEX = "ab12" * 16
_PROMPT = "please summarise my private medical history " * 7
_SECRETS = (
    f"sk-or-v1-{_HEX}",
    "abc-secret-value",
    "internal.openrouter",
    "ops@openai.com",
    "org-AbCdEf123456",
    "/var/run/secrets",
    "private medical history",
    "flagged prompt text",
)


def _poisoned(*, with_key_assignment: bool) -> bytes:
    message = (
        f"Bearer sk-or-v1-{_HEX} rejected; "
        "see https://internal.openrouter/x?token=abc-secret-value "
        f"mail ops@openai.com org org-AbCdEf123456 path /var/run/secrets/kube "
        f"echo '{_PROMPT}' ‮bidi‍"
    )
    if with_key_assignment:
        message = "api_key=abc-secret-value " + message
    return _error_body(message, 400, flagged_input="flagged prompt text", reasons=["x"])


@pytest.mark.parametrize("with_key_assignment", [False, True])
def test_poisoned_body_leaks_nothing_to_client_or_logs(
    connection, monkeypatch, caplog, with_key_assignment
) -> None:
    _wire(monkeypatch, 400, _poisoned(with_key_assignment=with_key_assignment), {"n": 0})

    with caplog.at_level(logging.DEBUG, logger="aigateway"):
        resp = _post(connection)

    assert resp.status_code == 400
    for secret in _SECRETS:
        assert secret not in resp.text
        assert secret not in caplog.text
    assert "‮" not in resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "bad_request"
    if with_key_assignment:
        # Gate 1: the engine would withhold it, so the gateway does — generic, no new keys.
        assert detail == {
            "code": "bad_request",
            "message": "The upstream provider rejected the request.",
        }
    else:
        assert detail["upstream_message"].startswith("[redacted] rejected; see [url] mail [email]")
    # INVARIANT (OME-968): the terminal record stays class-name-only.
    assert "upstream_message" not in caplog.text
    assert "[redacted]" not in caplog.text


def test_the_calls_own_credential_withholds_the_relay(connection, monkeypatch) -> None:
    # `x` + the key: no word boundary, so no redaction rule matches — only Gate 2 can catch it.
    _wire(monkeypatch, 400, _error_body(f"bad key x{_KEY} for this account", 400), {"n": 0})

    resp = _post(connection)

    assert _KEY not in resp.text
    assert resp.json()["detail"] == {
        "code": "bad_request",
        "message": "The upstream provider rejected the request.",
    }


# --- case 7: 401 and 429 never relay ------------------------------------------------------


@pytest.mark.parametrize(("status", "code"), [(401, "auth_required"), (429, "rate_limited")])
def test_auth_and_rate_limit_never_relay(connection, monkeypatch, status, code) -> None:
    recorded: list[Any] = []
    real = chat_dispatch.provider_access_for

    class _Spy:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        async def record_dispatch_failure(self, target, status_code, detail, *, plugin):
            recorded.append(detail)
            return await self._inner.record_dispatch_failure(
                target, status_code, detail, plugin=plugin
            )

    monkeypatch.setattr(chat_dispatch, "provider_access_for", lambda app: _Spy(real(app)))
    _wire(monkeypatch, status, _error_body("A perfectly benign explanation", status), {"n": 0})

    resp = _post(connection)

    assert resp.status_code == status
    detail = resp.json()["detail"]
    assert detail["code"] == code
    assert "upstream_message" not in detail
    assert "upstream_status" not in detail
    assert "benign explanation" not in resp.text
    for persisted in recorded:
        assert "benign explanation" not in json.dumps(persisted)
    if status == 401:
        assert recorded, "a 401 must still reach the credential-marking path"
