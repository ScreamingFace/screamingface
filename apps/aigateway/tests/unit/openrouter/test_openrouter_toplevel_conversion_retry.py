"""Top-level HTTP-200 body errors that litellm raises DURING conversion
(OME-428 Checkpoint A, second-review FINDING A).

litellm 1.87.0 does not return a ``ModelResponse`` when a nominal HTTP-200 body
carries a meaningful top-level ``error`` — it *raises* while converting the body
(``RateLimitError``/``ServiceUnavailableError``/``APIError``/``AuthenticationError``
/``BadRequestError`` by status). The upstream call already completed and may be
billed, so — exactly like an error found by scanning a returned payload — it must
be non-retryable (exactly one upstream POST) and fully sanitized. The plugin's
post-return ``_find_embedded_error`` scanner structurally cannot see this because
no payload is ever returned; the interception must happen where the raise occurs.

These tests drive REAL ``litellm.acompletion`` (no acompletion stub) with a
mocked wire (``httpx.AsyncClient.send``) so the litellm-1.87.0 converter-raise
behavior is exercised end-to-end through the gateway retry loop and route.

INVARIANT: an error derived from a nominal HTTP-200 payload is non-retryable —
exactly one dispatch — and no raw provider text reaches the client, logs, or
persisted error state.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import litellm
import pytest

from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.provenance import ErrorProvenance, classify_provenance
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_KEY = "sk-or-v1-conv"
_MODEL = "openrouter/anthropic/claude-fable-5"
# Raw provider text that must NEVER surface to the client / logs / persisted state.
_SECRET = "SECRET-provider-detail-do-not-leak"


@pytest.fixture()
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


@pytest.fixture()
def fast_retries(authenticated_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero backoff/jitter so any retry loop runs instantly; the retry COUNT
    (the behavior under test) is unaffected."""
    settings = authenticated_client.app.state.settings
    monkeypatch.setattr(settings, "retry_backoff_base_seconds", 0.0)
    monkeypatch.setattr(settings, "retry_jitter_seconds", 0.0)


@contextmanager
def _server_errors_as_responses(client) -> Iterator[None]:
    """Surface unhandled server exceptions as 500 responses instead of raising,
    so a test can assert the *current* broken behavior (e.g. int('not-a-status')
    → ValueError → 500) turns into a controlled status after the fix."""
    transport = getattr(client, "_transport")
    previous = transport.raise_server_exceptions
    transport.raise_server_exceptions = False
    try:
        yield
    finally:
        transport.raise_server_exceptions = previous


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


def _wire_response(status: int, body: dict[str, Any], retry_after: str | None = None):
    headers = {"content-type": "application/json"}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    return httpx.Response(
        status_code=status,
        headers=headers,
        content=json.dumps(body).encode(),
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )


def _counting_wire(make_response, calls: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the httpx send used by litellm so REAL litellm.acompletion runs and
    the litellm-1.87.0 converter-raise path is exercised. Counts POST dispatches."""

    async def fake_send(self, request, *args, **kwargs):  # noqa: ANN001
        if request.method == "POST":
            calls["n"] += 1
        return make_response()

    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)


def _top_level_error(status: int | str | None, message: str) -> dict[str, Any]:
    error: dict[str, Any] = {"message": message}
    if status is not None:
        error["code"] = status
    return {"error": error}


# --- FINDING A: converter-raised overload statuses make EXACTLY ONE dispatch ---


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [(429, "rate_limited"), (503, "provider_unavailable"), (529, "provider_unavailable")],
)
def test_toplevel_overload_converts_to_single_dispatch(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    expected_code: str,
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")

    calls = {"n": 0}
    _counting_wire(
        lambda: _wire_response(200, _top_level_error(status, _SECRET)), calls, monkeypatch
    )
    resp = _post_chat(authenticated_client)

    # INVARIANT (FINDING A): a top-level error in a nominal HTTP-200 body is
    # non-retryable — litellm already consumed the (billable) upstream call.
    # Current code retries it (1 + retry_max_attempts dispatches) → amplification.
    assert calls["n"] == 1
    assert resp.status_code == status
    assert resp.json()["detail"]["code"] == expected_code
    # No Retry-After invented for an in-body error (no validated transport hint).
    assert "retry-after" not in resp.headers
    # Raw provider text must never reach the client.
    assert _SECRET not in resp.text
    assert _active_labels(authenticated_client, account_id) == ["work-or"]


def test_toplevel_auth_error_single_dispatch_sanitized_and_scoped(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")
    _create_connection(authenticated_client, "backup-or")

    calls = {"n": 0}
    _counting_wire(lambda: _wire_response(200, _top_level_error(401, _SECRET)), calls, monkeypatch)
    resp = _post_chat(authenticated_client, profile="work-or")

    assert calls["n"] == 1
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "auth_required"
    # Gateway-authored message only — the raw provider text (which for a 401 is
    # also persisted into connection error state) must never leak.
    assert _SECRET not in resp.text
    # D9 local: only the selected connection flips to error.
    assert _active_labels(authenticated_client, account_id) == ["backup-or"]


def test_toplevel_malformed_status_sanitized_to_502_never_500(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_connection(authenticated_client, "work-or")

    calls = {"n": 0}
    # litellm maps a non-numeric top-level code to APIError(status_code='not-a-status').
    # Current _litellm_http_exception does int('not-a-status') → ValueError → HTTP 500.
    _counting_wire(
        lambda: _wire_response(200, _top_level_error("not-a-status", _SECRET)), calls, monkeypatch
    )
    with _server_errors_as_responses(authenticated_client):
        resp = _post_chat(authenticated_client)

    assert calls["n"] == 1
    assert resp.status_code == 502
    assert resp.status_code != 500
    assert resp.json()["detail"]["code"] == "provider_error"
    assert _SECRET not in resp.text


@pytest.mark.parametrize(
    ("status", "expected_status", "expected_code"),
    [
        (400, 400, "bad_request"),
        (402, 402, "insufficient_credits"),
        (403, 403, "provider_error"),
        (408, 408, "provider_error"),
        (500, 500, "provider_unavailable"),
        (502, 502, "provider_unavailable"),
    ],
)
def test_toplevel_billing_and_client_statuses_single_dispatch_sanitized(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    expected_status: int,
    expected_code: str,
) -> None:
    _create_connection(authenticated_client, "work-or")

    calls = {"n": 0}
    _counting_wire(
        lambda: _wire_response(200, _top_level_error(status, _SECRET)), calls, monkeypatch
    )
    resp = _post_chat(authenticated_client)

    assert calls["n"] == 1
    assert resp.status_code == expected_status
    assert resp.json()["detail"]["code"] == expected_code
    assert _SECRET not in resp.text


def test_toplevel_402_surfaces_a_dedicated_insufficient_credits_message(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-927: OpenRouter reports out-of-credits as a top-level ``payment_required``
    error embedded in a nominal HTTP-200 body (this module's own docstring) — the
    exact shape the ticket's lead example describes. Pin the client-facing wording
    through THIS path specifically, since it is a separate status→code mapping
    (``_embedded_error_exception``) from the generic transport-exception one
    covered in ``test_litellm_http_exception_sanitize.py``.

    FEATURE: insufficient-credits surfacing.
    """
    _create_connection(authenticated_client, "work-or")

    calls = {"n": 0}
    _counting_wire(lambda: _wire_response(200, _top_level_error(402, _SECRET)), calls, monkeypatch)
    resp = _post_chat(authenticated_client)

    assert calls["n"] == 1
    assert resp.status_code == 402
    detail = resp.json()["detail"]
    assert detail["code"] == "insufficient_credits"
    assert detail["message"] == "The upstream provider reported insufficient credits."
    assert _SECRET not in resp.text


def test_toplevel_statusless_is_sanitized_and_single_dispatch(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A status-less top-level error maps to EXACTLY a sanitized 502
    ``provider_error`` (blocker D), no raw text leak, exactly one dispatch.

    # WHY: the OUTER exception is BadRequestError(400) for BOTH a status-less
    # body and an explicit code=400 — but the CONVERTER-CONTEXT status (the
    # chained exception's status_code) distinguishes them: status-less carries
    # litellm 1.87.0's 422 "no derivable status" default, explicit-400 carries
    # 400. converter_error_status reads the context and folds 422 -> None -> 502,
    # so a status-less body no longer masquerades as a client 400."""
    _create_connection(authenticated_client, "work-or")

    calls = {"n": 0}
    _counting_wire(lambda: _wire_response(200, _top_level_error(None, _SECRET)), calls, monkeypatch)
    with _server_errors_as_responses(authenticated_client):
        resp = _post_chat(authenticated_client)

    assert calls["n"] == 1
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "provider_error"
    assert _SECRET not in resp.text


def test_toplevel_explicit_422_folds_to_sanitized_502(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit embedded ``code: 422`` folds to a sanitized 502 (blocker D,
    owner-ratified).

    # WHY: 422 is litellm 1.87.0's "no derivable status" default AND is not a
    # documented OpenRouter error code, so at the converter-raise boundary an
    # explicit 422 is indistinguishable from a status-less body. Rather than
    # surface a status OpenRouter never sends, both fold to 502 provider_error.
    # (Distinguishable explicit statuses — 400/402/429/500/503 — are preserved.)"""
    _create_connection(authenticated_client, "work-or")

    calls = {"n": 0}
    _counting_wire(lambda: _wire_response(200, _top_level_error(422, _SECRET)), calls, monkeypatch)
    with _server_errors_as_responses(authenticated_client):
        resp = _post_chat(authenticated_client)

    assert calls["n"] == 1
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "provider_error"
    assert _SECRET not in resp.text


# --- CONTROL: genuine transport failures keep the shared retry budget ---


@pytest.mark.parametrize("status", [429, 503])
def test_transport_overload_still_retries_full_budget(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    """A real non-2xx wire failure (litellm raises WITH populated
    ``litellm_response_headers`` and an httpx cause) must retain the full shared
    retry budget — the FINDING A fix narrows retry only for converter-origin
    errors, never for genuine transport failures."""
    _create_connection(authenticated_client, "work-or")
    settings = authenticated_client.app.state.settings

    calls = {"n": 0}
    _counting_wire(
        lambda: _wire_response(status, {"error": {"code": status, "message": "real transport"}}),
        calls,
        monkeypatch,
    )
    resp = _post_chat(authenticated_client)

    assert calls["n"] == 1 + settings.retry_max_attempts
    assert resp.status_code == status


# --- PREMISE PIN: guard the litellm-1.87.0 provenance shape the fix relies on ---


def test_litellm_1_87_converter_raise_provenance_shape() -> None:
    """Pin the litellm-1.87.0 behavior the provenance discriminator depends on,
    so a future litellm upgrade that changes it fails LOUDLY here rather than
    silently mis-routing converter-origin errors as retryable transport.

    Converter-origin (HTTP-200 body): ``litellm_response_headers is None`` and a
    chained bare-Exception context with no ``httpx.HTTPError`` in the chain.
    Genuine transport (non-2xx wire): ``litellm_response_headers`` is populated."""

    async def _raise(make_response) -> Exception:
        async def fake_send(self, request, *args, **kwargs):  # noqa: ANN001
            return make_response()

        import unittest.mock

        with unittest.mock.patch.object(httpx.AsyncClient, "send", fake_send):
            try:
                await litellm.acompletion(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "hi"}],
                    api_key="sk-or-v1-pin",
                    api_base="https://openrouter.ai/api/v1",
                )
            except Exception as exc:  # noqa: BLE001
                return exc
        raise AssertionError("litellm did not raise")

    import asyncio

    converter = asyncio.run(_raise(lambda: _wire_response(200, _top_level_error(429, "x"))))
    transport = asyncio.run(
        _raise(lambda: _wire_response(429, {"error": {"code": 429, "message": "x"}}, "7"))
    )

    # Converter-origin: no wire headers, chained bare Exception, no httpx error.
    assert getattr(converter, "litellm_response_headers", None) is None
    assert converter.__context__ is not None or converter.__cause__ is not None
    chain = []
    cur: BaseException | None = converter.__cause__ or converter.__context__
    while cur is not None and cur not in chain:
        chain.append(cur)
        cur = cur.__cause__ or cur.__context__
    assert not any(isinstance(link, httpx.HTTPError) for link in chain)

    assert classify_provenance(converter) is ErrorProvenance.BODY

    # Transport: litellm attaches wire headers and chains an httpx error.
    assert getattr(transport, "litellm_response_headers", None) is not None
    assert classify_provenance(transport) is ErrorProvenance.TRANSPORT
