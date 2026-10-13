"""Anthropic OAuth strategy keyed by an account-scoped credential name."""

from __future__ import annotations

import json
import logging
import time

import httpx

from aigateway.core.credential_blob.store import CredentialBlobStore, ORMStore
from aigateway.core.errors import (
    AuthError,
    CredentialNotFoundError,
    ReauthRequiredError,
    is_reauth_refresh_failure,
)
from aigateway.core.oauth_base import BaseOAuthStrategy

from .settings import AnthropicPluginSettings

logger = logging.getLogger(__name__)


def credential_service_for(profile_name: str) -> str:
    return f"aigateway:anthropic:{profile_name}"


class AnthropicOAuth(BaseOAuthStrategy):
    def __init__(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
        settings: AnthropicPluginSettings | None = None,
        account: str | None = None,
        http_client_factory=None,
    ) -> None:
        super().__init__(profile_name=profile_name)
        self._settings = settings or AnthropicPluginSettings()
        self._store = credential_store or ORMStore()
        self._account = account if account is not None else self._settings.keychain_account
        self._http_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        )

    def credential_service(self) -> str:
        return credential_service_for(self.profile_name)

    def credential_account(self) -> str:
        return self._account

    async def _read_credential(self) -> dict:
        raw = await self._store.read(self.credential_service(), self.credential_account())
        if raw is None:
            raise CredentialNotFoundError(
                f"No tokens for anthropic profile {self.profile_name!r}. "
                "Re-authenticate via Electron."
            )
        try:
            creds = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthError(
                f"Token blob for {self.profile_name!r} is not valid JSON: {exc}"
            ) from exc
        for key in ("access_token", "refresh_token", "expires_at_ms"):
            if key not in creds:
                raise AuthError(f"Token blob missing required field {key!r}")
        return creds

    def _is_expired(self, creds: dict) -> bool:
        return time.time() * 1000 >= creds["expires_at_ms"] - (self.refresh_window_seconds * 1000)

    def _build_headers(self, creds: dict) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {creds['access_token']}",
            "anthropic-version": self._settings.api_version,
            "anthropic-beta": self._settings.beta,
        }

    async def _refresh_credential(self, creds: dict) -> dict:
        body = {
            "grant_type": "refresh_token",
            "refresh_token": creds["refresh_token"],
            "client_id": self._settings.client_id,
            "scope": " ".join(self._settings.refresh_scopes),
        }
        try:
            async with self._http_factory() as client:
                resp = await client.post(
                    self._settings.token_url,
                    json=body,
                    headers={"content-type": "application/json"},
                )
        except httpx.RequestError as exc:
            raise AuthError(f"Refresh endpoint unreachable: {exc}") from exc

        if resp.status_code != 200:
            if is_reauth_refresh_failure(resp.status_code, resp.text):
                raise ReauthRequiredError(
                    f"Refresh token rejected for profile {self.profile_name!r} "
                    f"(HTTP {resp.status_code}). Re-auth required."
                )
            raise AuthError(f"OAuth refresh failed status {resp.status_code}: {resp.text[:500]}")
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise AuthError(f"OAuth refresh response not JSON: {exc}") from exc

        # WHY no write here (OME-1497, G0 §5.3): the strategy base publishes under the guard.
        return self._convert_refresh_response(data)

    def _convert_refresh_response(self, data: dict) -> dict:
        for required in ("access_token", "refresh_token", "expires_in"):
            if required not in data:
                raise AuthError(f"OAuth refresh response missing {required!r}")
        return {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at_ms": int((time.time() + int(data["expires_in"])) * 1000),
            "token_type": data.get("token_type", "Bearer"),
        }

    async def _write_to_store(self, creds: dict) -> None:
        await self._store.write(
            self.credential_service(), self.credential_account(), json.dumps(creds)
        )


async def exchange_authorization_code(
    code: str,
    code_verifier: str,
    *,
    redirect_uri: str | None = None,
    state: str | None = None,
    http_client_factory=None,
    settings: AnthropicPluginSettings | None = None,
) -> dict:
    """Exchange an authorization code for tokens. Used by the OAuth callback handler.

    Body shape and content-type verified from the Claude Code source
    (services/oauth/client.ts -> exchangeCodeForTokens). The token endpoint
    expects JSON with ``state`` included alongside the standard OAuth fields.
    Anthropic returns ``{type:invalid_request_error,message:'Invalid request format'}``
    when ``state`` is missing or content-type is form-urlencoded.

    ``redirect_uri`` must match the one sent to ``/authorize`` (RFC 6749).
    """
    config = settings or AnthropicPluginSettings()
    factory = http_client_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(30.0)))
    body: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "client_id": config.client_id,
    }
    if redirect_uri:
        body["redirect_uri"] = redirect_uri
    if state:
        body["state"] = state
    async with factory() as client:
        resp = await client.post(
            config.token_url,
            json=body,
            headers={"content-type": "application/json"},
        )
    if resp.status_code != 200:
        # Log the full request/response detail for diagnosing OAuth failures.
        # Token endpoint errors are usually wrong content-type, missing
        # redirect_uri match, or scope/grant_type mismatches — the body tells
        # us which.
        logger.error(
            "Anthropic token exchange failed: status=%d url=%s sent_keys=%s response=%s",
            resp.status_code,
            config.token_url,
            sorted(body.keys()),
            resp.text[:1000],
        )
        raise AuthError(
            f"Authorization code exchange failed (HTTP {resp.status_code}): {resp.text[:500]}"
        )
    data = resp.json()
    for required in ("access_token", "refresh_token", "expires_in"):
        if required not in data:
            raise AuthError(f"Authorization code response missing {required!r}")
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at_ms": int((time.time() + int(data["expires_in"])) * 1000),
        "token_type": data.get("token_type", "Bearer"),
    }
