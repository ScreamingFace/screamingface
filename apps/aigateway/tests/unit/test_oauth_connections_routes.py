from __future__ import annotations

import base64
import json
import time
from datetime import UTC
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from aigateway.core.credential_strategy_cache import credential_strategy_cache
from aigateway.core.oauth.store import credential_key_for
from aigateway.core.plugin_base import OAuthConfig
from aigateway.plugins.codex_provider.oauth_config import (
    CODEX_AUTHORIZE_EXTRA_PARAMS,
    CODEX_AUTHORIZE_URL,
    CODEX_CLIENT_ID,
    CODEX_REDIRECT_PATH,
    CODEX_SCOPES,
    CODEX_TOKEN_URL,
)


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _jwt(payload: dict) -> str:
    def encode(value: dict | bytes) -> str:
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(payload)}.{encode(b'sig')}"


def _anthropic_token_factory():
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(
            200,
            json={
                "access_token": "anthropic-access",
                "refresh_token": "anthropic-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
    )
    return lambda: httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


def _codex_token_factory(email: str = "codex@example.com", sub: str = "codex-sub"):
    payload = {
        "sub": sub,
        "email": email,
        "name": "Codex User",
        "exp": int(time.time()) + 3600,
        "https://api.openai.com/auth": {"chatgpt_account_id": "acct-1"},
    }
    token = _jwt(payload)
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(
            200,
            json={
                "access_token": token,
                "refresh_token": "codex-refresh",
                "id_token": token,
                "token_type": "Bearer",
            },
        )
    )
    return lambda: httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


def _gemini_token_factory(email: str = "gemini@example.com", sub: str = "gemini-sub"):
    id_token = _jwt(
        {
            "sub": sub,
            "email": email,
            "name": "Gemini User",
            "exp": int(time.time()) + 3600,
        }
    )
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(
            200,
            json={
                "access_token": "gemini-access",
                "refresh_token": "gemini-refresh",
                "id_token": id_token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
    )
    return lambda: httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


def _failing_token_factory():
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(400, json={"error": "invalid_grant"})
    )
    return lambda: httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


def _transient_refresh_failure_factory():
    """Refresh fails with a non-auth, retryable error (provider 5xx)."""
    transport = httpx.MockTransport(lambda _req: httpx.Response(500, text="upstream boom"))
    return lambda: httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", "/v1/oauth/connections", None),
        ("GET", "/v1/oauth/connections/00000000-0000-0000-0000-000000000001", None),
        ("POST", "/v1/oauth/connections", {"provider": "codex"}),
        ("PATCH", "/v1/oauth/connections/00000000-0000-0000-0000-000000000001", {"label": "x"}),
        ("DELETE", "/v1/oauth/connections/00000000-0000-0000-0000-000000000001", None),
        ("POST", "/v1/oauth/connections/00000000-0000-0000-0000-000000000001/refresh", None),
        ("GET", "/v1/oauth/connections/00000000-0000-0000-0000-000000000001/token", None),
    ],
)
def test_oauth_connection_routes_require_jwt(client, method, path, json_body) -> None:
    resp = client.request(method, path, json=json_body)
    assert resp.status_code == 401


def test_anthropic_connection_requires_label(authenticated_client) -> None:
    resp = authenticated_client.post("/v1/oauth/connections", json={"provider": "anthropic"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "label_required"


@pytest.mark.parametrize(
    "label",
    ["", "bad\nlabel", "\x1b[31mred", "x" * 101],
)
def test_oauth_connection_rejects_unsafe_labels(authenticated_client, label) -> None:
    resp = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": label},
    )

    assert resp.status_code == 422


def test_patch_oauth_connection_rejects_unsafe_label(authenticated_client) -> None:
    resp = authenticated_client.patch(
        "/v1/oauth/connections/00000000-0000-0000-0000-000000000001",
        json={"label": "bad\nlabel"},
    )

    assert resp.status_code == 422


def test_anthropic_connection_uses_request_host_port_for_callback(
    authenticated_client,
) -> None:
    start = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "port-check-anthropic"},
        headers={"host": "127.0.0.1:9106"},
    )

    assert start.status_code == 201
    query = parse_qs(urlparse(start.json()["authorize_url"]).query)
    assert query["redirect_uri"] == ["http://localhost:9106/callback"]


def test_anthropic_connection_uses_public_url_for_callback(authenticated_client) -> None:
    authenticated_client.app.state.settings.public_url = "https://aigateway.example.com"

    start = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "public-anthropic"},
    )

    assert start.status_code == 201
    query = parse_qs(urlparse(start.json()["authorize_url"]).query)
    assert query["redirect_uri"] == ["https://aigateway.example.com/callback"]


def test_anthropic_connection_accepts_redirect_uri_override(authenticated_client) -> None:
    redirect_uri = "http://localhost:9105/callback"

    start = authenticated_client.post(
        "/v1/oauth/connections",
        json={
            "provider": "anthropic",
            "label": "override-anthropic",
            "redirect_uri": redirect_uri,
        },
    )

    assert start.status_code == 201
    query = parse_qs(urlparse(start.json()["authorize_url"]).query)
    assert query["redirect_uri"] == [redirect_uri]
    pending = authenticated_client.app.state.pending_auth.peek(start.json()["state"])
    assert pending.redirect_uri == redirect_uri


def test_anthropic_connection_redirect_uri_override_wins_over_public_url(
    authenticated_client,
) -> None:
    authenticated_client.app.state.settings.public_url = "https://aigateway.example.com"
    redirect_uri = "http://localhost:9105/callback"

    start = authenticated_client.post(
        "/v1/oauth/connections",
        json={
            "provider": "anthropic",
            "label": "override-public-anthropic",
            "redirect_uri": redirect_uri,
        },
    )

    assert start.status_code == 201
    query = parse_qs(urlparse(start.json()["authorize_url"]).query)
    assert query["redirect_uri"] == [redirect_uri]


def test_codex_connection_rejects_unconfigured_redirect_override_port(
    authenticated_client,
) -> None:
    start = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "codex", "redirect_uri": "http://localhost:9105/auth/callback"},
    )

    assert start.status_code == 400
    assert start.json()["detail"]["code"] == "invalid_redirect_uri"


def test_anthropic_connection_lifecycle_and_label_conflict(
    authenticated_client, credential_blobs
) -> None:
    account_id = _account_id(authenticated_client)
    authenticated_client.app.state.anthropic_http_factory = _anthropic_token_factory()

    start = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "work-anthropic"},
    )
    assert start.status_code == 201
    state = start.json()["state"]
    connection_id = start.json()["connection_id"]
    assert urlparse(start.json()["authorize_url"]).scheme == "https"

    cb = authenticated_client.get("/callback", params={"code": "code", "state": state})
    assert cb.status_code == 200

    detail = authenticated_client.get(f"/v1/oauth/connections/{connection_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "active"
    assert body["label"] == "work-anthropic"
    assert body["account"] is None
    assert (
        body["credential_locator"]["service"] == f"aigateway:anthropic:{account_id}:{connection_id}"
    )
    assert credential_blobs.read(body["credential_locator"]["service"], "default") is not None

    duplicate_label = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "work-anthropic"},
    )
    assert duplicate_label.status_code == 409
    assert duplicate_label.json()["detail"]["code"] == "label_conflict"


def test_gemini_connection_uses_canonical_credential_locator(
    authenticated_client,
    credential_blobs,
) -> None:
    account_id = _account_id(authenticated_client)
    setattr(authenticated_client.app.state, "gemini-cli_http_factory", _gemini_token_factory())

    start = authenticated_client.post("/v1/oauth/connections", json={"provider": "gemini-cli"})
    assert start.status_code == 201
    state = start.json()["state"]
    connection_id = start.json()["connection_id"]
    query = parse_qs(urlparse(start.json()["authorize_url"]).query)
    assert query["redirect_uri"] == ["http://localhost:9105/oauth2callback"]

    callback = authenticated_client.get("/oauth2callback", params={"code": "code", "state": state})
    assert callback.status_code == 200

    detail = authenticated_client.get(f"/v1/oauth/connections/{connection_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["provider"] == "gemini-cli"
    assert body["status"] == "active"
    assert body["label"] == "gemini@example.com"
    assert body["credential_locator"] == {
        "service": f"aigateway:gemini:{account_id}:{connection_id}",
        "account": "default",
    }
    assert credential_blobs.read(body["credential_locator"]["service"], "default") is not None
    assert (
        credential_blobs.read(f"aigateway:gemini-cli:{account_id}:{connection_id}", "default")
        is None
    )

    assert authenticated_client.delete(f"/v1/oauth/connections/{connection_id}").status_code == 204
    assert credential_blobs.read(body["credential_locator"]["service"], "default") is None


def test_anthropic_connection_can_reconnect_after_delete(authenticated_client) -> None:
    authenticated_client.app.state.anthropic_http_factory = _anthropic_token_factory()

    first = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "reconnect-anthropic"},
    )
    assert first.status_code == 201
    first_id = first.json()["connection_id"]
    assert (
        authenticated_client.get(
            "/callback", params={"code": "first", "state": first.json()["state"]}
        ).status_code
        == 200
    )
    assert authenticated_client.delete(f"/v1/oauth/connections/{first_id}").status_code == 204
    assert [
        item["id"]
        for item in authenticated_client.get(
            "/v1/oauth/connections", params={"provider": "anthropic"}
        ).json()["connections"]
    ] == []
    assert [
        item["id"]
        for item in authenticated_client.get(
            "/v1/oauth/connections", params={"provider": "anthropic", "status": "revoked"}
        ).json()["connections"]
    ] == [first_id]

    second = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "reconnect-anthropic"},
    )
    assert second.status_code == 201
    second_id = second.json()["connection_id"]
    assert second_id != first_id
    assert (
        authenticated_client.get(
            "/callback", params={"code": "second", "state": second.json()["state"]}
        ).status_code
        == 200
    )

    detail = authenticated_client.get(f"/v1/oauth/connections/{second_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "active"

    assert authenticated_client.delete(f"/v1/oauth/connections/{second_id}").status_code == 204
    third = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "reconnect-anthropic"},
    )
    assert third.status_code == 201
    assert (
        authenticated_client.get(
            "/callback", params={"code": "third", "state": third.json()["state"]}
        ).status_code
        == 200
    )


def test_failed_anthropic_connection_can_retry_same_label(authenticated_client) -> None:
    authenticated_client.app.state.anthropic_http_factory = _failing_token_factory()
    failed = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "retry-anthropic"},
    )
    assert failed.status_code == 201
    callback = authenticated_client.get(
        "/callback", params={"code": "fail", "state": failed.json()["state"]}
    )
    assert callback.status_code == 500

    authenticated_client.app.state.anthropic_http_factory = _anthropic_token_factory()
    retry = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "retry-anthropic"},
    )
    assert retry.status_code == 201
    assert (
        authenticated_client.get(
            "/callback", params={"code": "ok", "state": retry.json()["state"]}
        ).status_code
        == 200
    )


def test_refresh_error_releases_label_for_reauth(authenticated_client, credential_blobs) -> None:
    authenticated_client.app.state.anthropic_http_factory = _anthropic_token_factory()
    start = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "refresh-error-anthropic"},
    )
    assert start.status_code == 201
    connection_id = start.json()["connection_id"]
    assert (
        authenticated_client.get(
            "/callback", params={"code": "first", "state": start.json()["state"]}
        ).status_code
        == 200
    )
    connection = authenticated_client.get(f"/v1/oauth/connections/{connection_id}").json()
    credential_blobs.delete(connection["credential_locator"]["service"], "default")

    refresh = authenticated_client.post(f"/v1/oauth/connections/{connection_id}/refresh")
    assert refresh.status_code == 401
    patch = authenticated_client.patch(
        f"/v1/oauth/connections/{connection_id}",
        json={"label": "refresh-error-anthropic"},
    )
    assert patch.status_code == 409
    assert patch.json()["detail"]["code"] == "connection_not_active"
    retry_refresh = authenticated_client.post(f"/v1/oauth/connections/{connection_id}/refresh")
    assert retry_refresh.status_code == 409
    assert retry_refresh.json()["detail"]["code"] == "connection_not_active"

    retry = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "refresh-error-anthropic"},
    )
    assert retry.status_code == 201
    assert (
        authenticated_client.get(
            "/callback", params={"code": "second", "state": retry.json()["state"]}
        ).status_code
        == 200
    )


def test_refresh_connection_refreshes_the_shared_cached_strategy(
    authenticated_client, credential_blobs
) -> None:
    # SF-323: manual refresh must resolve its strategy from the SAME app-scoped
    # cache as chat/token dispatch, so a concurrent chat/token single-flights on
    # ONE lock instead of building a private fresh strategy with its own lock.
    # Pre-seed a sentinel under the connection's cache key: the route must refresh
    # THAT instance, then evict it so later dispatch rebuilds from persisted creds.
    connection_id = _connect_anthropic(authenticated_client, "refresh-shared-cache")
    account_id = _account_id(authenticated_client)
    _ = credential_blobs

    class _SentinelStrategy:
        def __init__(self) -> None:
            self.refresh_calls = 0

        async def refresh_credentials(self) -> None:
            self.refresh_calls += 1

    cache = credential_strategy_cache(authenticated_client.app)
    key = credential_key_for(account_id, connection_id)
    sentinel = _SentinelStrategy()
    cache.get_or_create(
        provider="anthropic", auth_type="oauth", credential_name=key, build=lambda: sentinel
    )

    resp = authenticated_client.post(f"/v1/oauth/connections/{connection_id}/refresh")
    assert resp.status_code == 200
    # Refreshed the shared cached instance (the fix), not a fresh build (the bug).
    assert sentinel.refresh_calls == 1
    # ...and evicted afterwards, so a subsequent chat/token rebuilds from the store.
    rebuilt = cache.get_or_create(
        provider="anthropic",
        auth_type="oauth",
        credential_name=key,
        build=lambda: _SentinelStrategy(),
    )
    assert rebuilt is not sentinel


def test_patch_connection_label_conflict_returns_409(authenticated_client) -> None:
    authenticated_client.app.state.anthropic_http_factory = _anthropic_token_factory()

    # WHY each flow completes before the next starts (OME-1497, G0 §5.3): a native OAuth start is
    # an ownership change, so a second start before the first callback supersedes the first flow.
    first = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "first-anthropic"},
    )
    assert first.status_code == 201
    assert (
        authenticated_client.get(
            "/callback", params={"code": "first", "state": first.json()["state"]}
        ).status_code
        == 200
    )
    second = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "second-anthropic"},
    )
    assert second.status_code == 201
    assert (
        authenticated_client.get(
            "/callback", params={"code": "second", "state": second.json()["state"]}
        ).status_code
        == 200
    )

    conflict = authenticated_client.patch(
        f"/v1/oauth/connections/{second.json()['connection_id']}",
        json={"label": "first-anthropic"},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "label_conflict"


def test_codex_duplicate_connection_returns_existing(
    authenticated_client, credential_blobs, monkeypatch
) -> None:
    account_id = _account_id(authenticated_client)
    authenticated_client.app.state.codex_http_factory = _codex_token_factory()
    monkeypatch.setattr(
        authenticated_client.app.state.providers.get("codex"),
        "oauth_config",
        lambda: OAuthConfig(
            authorize_url=CODEX_AUTHORIZE_URL,
            token_url=CODEX_TOKEN_URL,
            client_id=CODEX_CLIENT_ID,
            scopes=CODEX_SCOPES,
            redirect_path=CODEX_REDIRECT_PATH,
            extra_authorize_params=CODEX_AUTHORIZE_EXTRA_PARAMS,
            loopback_redirect_ports=None,
        ),
    )

    first = authenticated_client.post("/v1/oauth/connections", json={"provider": "codex"})
    assert first.status_code == 201
    first_id = first.json()["connection_id"]
    assert (
        authenticated_client.get(
            "/auth/callback", params={"code": "first", "state": first.json()["state"]}
        ).status_code
        == 200
    )

    second = authenticated_client.post("/v1/oauth/connections", json={"provider": "codex"})
    assert second.status_code == 201
    second_id = second.json()["connection_id"]
    assert (
        authenticated_client.get(
            "/auth/callback", params={"code": "second", "state": second.json()["state"]}
        ).status_code
        == 200
    )

    reused = authenticated_client.get(f"/v1/oauth/connections/{second_id}")
    assert reused.status_code == 200
    body = reused.json()
    assert body["id"] == first_id
    assert body["is_duplicate"] is True

    active = authenticated_client.get(
        "/v1/oauth/connections", params={"provider": "codex", "status": "active"}
    )
    assert [item["id"] for item in active.json()["connections"]] == [first_id]
    assert credential_blobs.read(f"aigateway:codex:{account_id}:{second_id}", "default") is None


def test_connection_lookup_is_account_scoped(
    authenticated_client, provisioned_user_factory
) -> None:
    start = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "admin-anthropic"},
    )
    assert start.status_code == 201
    connection_id = start.json()["connection_id"]

    provisioned_user_factory("bob", "bob-pass1")
    login = authenticated_client.post(
        "/v1/auth/login", json={"username": "bob", "password": "bob-pass1"}
    )
    authenticated_client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})

    assert authenticated_client.get(f"/v1/oauth/connections/{connection_id}").status_code == 404
    assert (
        authenticated_client.patch(
            f"/v1/oauth/connections/{connection_id}", json={"label": "x"}
        ).status_code
        == 404
    )
    assert authenticated_client.delete(f"/v1/oauth/connections/{connection_id}").status_code == 404


def test_token_endpoint_returns_access_token_and_expires_at(
    authenticated_client, credential_blobs
) -> None:
    authenticated_client.app.state.anthropic_http_factory = _anthropic_token_factory()
    start = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "tok-work"},
    )
    assert start.status_code == 201
    connection_id = start.json()["connection_id"]
    cb = authenticated_client.get(
        "/callback", params={"code": "code", "state": start.json()["state"]}
    )
    assert cb.status_code == 200
    _ = credential_blobs  # blob store populated by callback

    resp = authenticated_client.get(f"/v1/oauth/connections/{connection_id}/token")
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "anthropic-access"
    assert "expires_at" in body
    # ISO-8601 UTC string parses; expiry is ~1h ahead (token factory: expires_in=3600).
    from datetime import datetime

    parsed = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    delta = (parsed - datetime.now(UTC)).total_seconds()
    assert 0 < delta < 3700


def test_token_endpoint_returns_404_for_unknown_connection(authenticated_client) -> None:
    resp = authenticated_client.get(
        "/v1/oauth/connections/00000000-0000-0000-0000-000000000099/token"
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "connection_not_found"


def test_token_endpoint_returns_409_for_revoked_connection(
    authenticated_client, credential_blobs
) -> None:
    authenticated_client.app.state.anthropic_http_factory = _anthropic_token_factory()
    start = authenticated_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "tok-revoked"},
    )
    connection_id = start.json()["connection_id"]
    authenticated_client.get("/callback", params={"code": "code", "state": start.json()["state"]})
    assert authenticated_client.delete(f"/v1/oauth/connections/{connection_id}").status_code == 204
    _ = credential_blobs

    resp = authenticated_client.get(f"/v1/oauth/connections/{connection_id}/token")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "connection_not_active"


def _force_immediate_refresh(credential_blobs, client, connection_id) -> None:
    """Rewind the stored credential's expiry so the next /token forces a refresh."""
    locator = client.get(f"/v1/oauth/connections/{connection_id}").json()["credential_locator"]
    creds = json.loads(credential_blobs.read(locator["service"], "default"))
    creds["expires_at_ms"] = int(time.time() * 1000) - 1000
    credential_blobs.write(locator["service"], "default", json.dumps(creds))


def _connect_anthropic(client, label: str) -> str:
    client.app.state.anthropic_http_factory = _anthropic_token_factory()
    start = client.post("/v1/oauth/connections", json={"provider": "anthropic", "label": label})
    connection_id = start.json()["connection_id"]
    client.get("/callback", params={"code": "code", "state": start.json()["state"]})
    return connection_id


def test_token_endpoint_returns_503_when_upstream_refresh_fails(
    authenticated_client, credential_blobs
) -> None:
    connection_id = _connect_anthropic(authenticated_client, "tok-503")
    _force_immediate_refresh(credential_blobs, authenticated_client, connection_id)
    # Transient provider failure (5xx): the connection should stay active so the
    # caller can retry rather than being forced through a full re-auth.
    authenticated_client.app.state.anthropic_http_factory = _transient_refresh_failure_factory()

    resp = authenticated_client.get(f"/v1/oauth/connections/{connection_id}/token")
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "upstream_refresh_failed"
    # Connection is untouched — still active.
    detail = authenticated_client.get(f"/v1/oauth/connections/{connection_id}").json()
    assert detail["status"] == "active"


def test_token_endpoint_returns_401_and_marks_error_when_refresh_token_revoked(
    authenticated_client, credential_blobs
) -> None:
    connection_id = _connect_anthropic(authenticated_client, "tok-revoked-rt")
    _force_immediate_refresh(credential_blobs, authenticated_client, connection_id)
    # invalid_grant (400) means the refresh token is dead -> re-auth required.
    authenticated_client.app.state.anthropic_http_factory = _failing_token_factory()

    resp = authenticated_client.get(f"/v1/oauth/connections/{connection_id}/token")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "auth_required"
    # Connection is marked errored so the UI/caller knows to prompt re-auth.
    detail = authenticated_client.get(f"/v1/oauth/connections/{connection_id}").json()
    assert detail["status"] == "error"


def test_token_endpoint_updates_last_refreshed_at_after_a_refresh(
    authenticated_client, credential_blobs
) -> None:
    connection_id = _connect_anthropic(authenticated_client, "tok-refreshed")
    before = authenticated_client.get(f"/v1/oauth/connections/{connection_id}").json()[
        "last_refreshed_at"
    ]
    _force_immediate_refresh(credential_blobs, authenticated_client, connection_id)

    resp = authenticated_client.get(f"/v1/oauth/connections/{connection_id}/token")
    assert resp.status_code == 200

    after = authenticated_client.get(f"/v1/oauth/connections/{connection_id}").json()[
        "last_refreshed_at"
    ]
    assert after is not None
    assert after != before


def test_refresh_does_not_resurrect_a_concurrently_revoked_connection(
    authenticated_client, credential_blobs
) -> None:
    """OME-307 H-1 — connection refresh 409s instead of reactivating a revoked row.

    FEATURE: manual OAuth connection refresh with delete/revoke-race safety.
    INVARIANT (OME-307 H-1): the success republish is status-fenced on 'active', so a connection
    revoked (or deleted) during the provider network window makes the refresh return 409 instead
    of flipping it back to active.
    """
    _ = credential_blobs
    connection_id = _connect_anthropic(authenticated_client, "refresh-revoke-race")
    account_id = _account_id(authenticated_client)
    store = authenticated_client.app.state.oauth_connections

    class _RevokingStrategy:
        async def refresh_credentials(self) -> None:
            # A concurrent revoke commits during the provider network window. This runs INSIDE the
            # route on the TestClient portal loop, so the store's Tortoise access stays single-loop.
            conn = await store.get(account_id, connection_id)
            await store.mark_revoked(conn)

    cache = credential_strategy_cache(authenticated_client.app)
    key = credential_key_for(account_id, connection_id)
    cache.get_or_create(
        provider="anthropic",
        auth_type="oauth",
        credential_name=key,
        build=lambda: _RevokingStrategy(),
    )

    resp = authenticated_client.post(f"/v1/oauth/connections/{connection_id}/refresh")

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "connection_conflict"
    # Not resurrected: the revoked row stays inactive, so a follow-up refresh is rejected at the
    # status gate before any strategy runs — proving complete_active did not flip it to 'active'.
    again = authenticated_client.post(f"/v1/oauth/connections/{connection_id}/refresh")
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "connection_not_active"
