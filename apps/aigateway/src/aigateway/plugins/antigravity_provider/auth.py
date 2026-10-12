"""Antigravity OAuth strategy + authorization-code exchange.

Mirrors GeminiOAuth (same Google Code Assist token contract) but with the
Antigravity installed-app client/secret/token-url and the "antigravity"
credential namespace (U11 — the same namespace string the connection locator
uses via credential_service_provider()). Token normalization and identity
extraction reuse the core Google Code Assist helpers (findings U5), so there is
no plugin-to-plugin import.

Secret policy (GATE-2 Option A): the public installed-app client secret has a
settings default and may be overridden via ``AIGW_ANTIGRAVITY_CLIENT_SECRET``.
Exchange/refresh defensively reject an empty configured secret. Exchange AND
refresh errors are status-only (U7): we never echo the upstream token-endpoint
response body, which could carry other grant material.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from aigateway.core.credential_blob.store import CredentialBlobStore, ORMStore
from aigateway.core.errors import (
    AuthError,
    CredentialNotFoundError,
    ReauthRequiredError,
    is_reauth_refresh_failure,
)
from aigateway.core.google_code_assist import (
    extract_account_identity,
    normalize_token_response,
)
from aigateway.core.oauth_base import BaseOAuthStrategy

from .settings import ANTIGRAVITY_CLIENT_ID, ANTIGRAVITY_TOKEN_URL

_ACCOUNT = "default"
ANTIGRAVITY_PROFILE_HEADER = "X-AIGW-Antigravity-Profile"
# Matches settings.user_agent default — the proven-working community-spec value
# the live service recognizes (review #3 / architect).
ANTIGRAVITY_USER_AGENT = "antigravity"

# Actionable message when an env override blanks the installed-app secret. Names
# the env var so operators know what to unset/fix; never echoes a value.
_MISSING_SECRET_MESSAGE = (
    "Antigravity OAuth requires a non-empty installed-app client secret. "
    "Unset or fix AIGW_ANTIGRAVITY_CLIENT_SECRET in the AIGateway environment."
)


def credential_service_for(profile_name: str) -> str:
    return f"aigateway:antigravity:{profile_name}"


def _require_secret(client_secret: str | None) -> str:
    if not client_secret:
        raise AuthError(_MISSING_SECRET_MESSAGE)
    return client_secret


class AntigravityOAuth(BaseOAuthStrategy):
    def __init__(
        self,
        profile_name: str,
        *,
        client_secret: str | None,
        client_id: str = ANTIGRAVITY_CLIENT_ID,
        token_url: str = ANTIGRAVITY_TOKEN_URL,
        credential_store: CredentialBlobStore | None = None,
        account: str | None = None,
        http_client_factory=None,
    ) -> None:
        super().__init__(profile_name=profile_name)
        self._client_secret = client_secret
        # client_id + token_url come from the SAME source authorize uses (the
        # plugin threads settings here), so a settings override can't mint a
        # code for one client and refresh against another (review #5).
        self._client_id = client_id
        self._token_url = token_url
        self._store = credential_store or ORMStore()
        self._account = account if account is not None else _ACCOUNT
        self._http_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        )

    def credential_service(self) -> str:
        return credential_service_for(self.profile_name)

    def credential_account(self) -> str:
        return self._account

    async def _read_credential(self) -> dict[str, Any]:
        raw = await self._store.read(self.credential_service(), self.credential_account())
        if raw is None:
            raise CredentialNotFoundError(
                f"No tokens for antigravity profile {self.profile_name!r}. "
                "Re-authenticate via Electron."
            )
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthError(
                f"Token blob for {self.profile_name!r} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(loaded, dict):
            raise AuthError(f"Token blob for {self.profile_name!r} is not a JSON object")
        return normalize_token_response(loaded, loaded)

    def _is_expired(self, creds: dict[str, Any]) -> bool:
        expires_at_ms = creds.get("expires_at_ms")
        if not isinstance(expires_at_ms, int | float) or expires_at_ms <= 0:
            return False
        return time.time() * 1000 >= expires_at_ms - (self.refresh_window_seconds * 1000)

    def _build_headers(self, creds: dict[str, Any]) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {creds['access_token']}",
            "User-Agent": ANTIGRAVITY_USER_AGENT,
            ANTIGRAVITY_PROFILE_HEADER: self.profile_name,
        }

    async def _refresh_credential(self, creds: dict[str, Any]) -> dict[str, Any]:
        body = {
            "grant_type": "refresh_token",
            "refresh_token": creds["refresh_token"],
            "client_id": self._client_id,
            "client_secret": _require_secret(self._client_secret),
        }
        try:
            async with self._http_factory() as client:
                resp = await client.post(
                    self._token_url,
                    data=body,
                    headers={"content-type": "application/x-www-form-urlencoded"},
                )
        except httpx.RequestError as exc:
            raise AuthError(f"Google token endpoint unreachable: {exc}") from exc

        if resp.status_code != 200:
            if is_reauth_refresh_failure(resp.status_code, resp.text):
                raise ReauthRequiredError(
                    f"Refresh token rejected for profile {self.profile_name!r} "
                    f"(HTTP {resp.status_code}). Re-auth required."
                )
            # Status-only (U7): never echo the upstream body.
            raise AuthError(f"Antigravity OAuth refresh failed (HTTP {resp.status_code})")
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise AuthError(f"Antigravity OAuth refresh response not JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise AuthError("Antigravity OAuth refresh response is not a JSON object")

        refreshed = normalize_token_response(data, creds)
        # WHY no write here (OME-1497, G0 §5.3): the strategy base publishes under the guard.
        return refreshed

    async def _write_to_store(self, creds: dict[str, Any]) -> None:
        await self._store.write(
            self.credential_service(), self.credential_account(), json.dumps(creds)
        )


async def exchange_authorization_code(
    code: str,
    code_verifier: str,
    *,
    redirect_uri: str,
    client_secret: str | None,
    client_id: str = ANTIGRAVITY_CLIENT_ID,
    token_url: str = ANTIGRAVITY_TOKEN_URL,
    http_client_factory=None,
) -> dict[str, Any]:
    # client_id + token_url default to the pinned constants but are threaded
    # from settings by the plugin, matching the authorize-URL source (review #5).
    secret = _require_secret(client_secret)
    factory = http_client_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(30.0)))
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": secret,
        "code_verifier": code_verifier,
    }
    try:
        async with factory() as client:
            resp = await client.post(
                token_url,
                data=body,
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
    except httpx.RequestError as exc:
        raise AuthError(f"Antigravity authorization code exchange unreachable: {exc}") from exc

    if resp.status_code != 200:
        # Status-only (U7).
        raise AuthError(f"Antigravity authorization code exchange failed (HTTP {resp.status_code})")
    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise AuthError(f"Antigravity authorization code response not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AuthError("Antigravity authorization code response is not a JSON object")

    creds = normalize_token_response(data)
    identity = await extract_account_identity(creds, http_client_factory=http_client_factory)
    if identity is not None:
        creds["account_identity"] = identity.as_dict()
        label = identity.label()
        if label is not None:
            creds["account_label"] = label
    return creds
