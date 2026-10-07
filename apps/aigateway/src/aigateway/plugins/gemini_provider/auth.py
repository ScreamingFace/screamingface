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

# Same-contract Google Code Assist token/identity helpers were extracted to
# aigateway.core.google_code_assist (findings U5) so a second Google provider
# (antigravity) can reuse them without a plugin-to-plugin import. Imported here
# only for this module's own use; gemini's other callers import them from core
# directly (no plugin-level re-export).
from aigateway.core.google_code_assist import (
    extract_account_identity,
    normalize_token_response,
)
from aigateway.core.oauth_base import BaseOAuthStrategy

from .oauth_config import GEMINI_CLIENT_ID, GEMINI_CLIENT_SECRET, GEMINI_TOKEN_URL

_ACCOUNT = "default"
GEMINI_PROFILE_HEADER = "X-AIGW-Gemini-Profile"
GEMINI_USER_AGENT = "GeminiCLI/0.42.0/gemini-2.5-flash (aigateway)"

# Single source of truth for headers the gateway owns: stripped from caller
# bodies in prepare_chat_body AND filtered from upstream forwards in the chat
# handler. The gateway-owned x-goog-api-key invariant depends on this set
# being shared, not duplicated (SF-244 audit F23).
CLIENT_AUTH_HEADER_NAMES = frozenset(
    {
        "authorization",
        "content-type",
        "x-aigw-gemini-profile",
        "x-goog-api-key",
        "x-goog-user-project",
    }
)


def credential_service_for(profile_name: str) -> str:
    return f"aigateway:gemini:{profile_name}"


class GeminiOAuth(BaseOAuthStrategy):
    def __init__(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
        account: str | None = None,
        http_client_factory=None,
    ) -> None:
        super().__init__(profile_name=profile_name)
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
                f"No tokens for gemini profile {self.profile_name!r}. Re-authenticate via Electron."
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
            "User-Agent": GEMINI_USER_AGENT,
            GEMINI_PROFILE_HEADER: self.profile_name,
        }

    async def _refresh_credential(self, creds: dict[str, Any]) -> dict[str, Any]:
        body = {
            "grant_type": "refresh_token",
            "refresh_token": creds["refresh_token"],
            "client_id": GEMINI_CLIENT_ID,
            "client_secret": GEMINI_CLIENT_SECRET,
        }
        try:
            async with self._http_factory() as client:
                resp = await client.post(
                    GEMINI_TOKEN_URL,
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
            raise AuthError(
                f"Google OAuth refresh failed status {resp.status_code}: {resp.text[:500]}"
            )
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise AuthError(f"Google OAuth refresh response not JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise AuthError("Google OAuth refresh response is not a JSON object")

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
    http_client_factory=None,
) -> dict[str, Any]:
    factory = http_client_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(30.0)))
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": GEMINI_CLIENT_ID,
        "client_secret": GEMINI_CLIENT_SECRET,
        "code_verifier": code_verifier,
    }
    try:
        async with factory() as client:
            resp = await client.post(
                GEMINI_TOKEN_URL,
                data=body,
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
    except httpx.RequestError as exc:
        raise AuthError(f"Google authorization code exchange unreachable: {exc}") from exc

    if resp.status_code != 200:
        raise AuthError(f"Google authorization code exchange failed (HTTP {resp.status_code})")
    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise AuthError(f"Google authorization code response not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AuthError("Google authorization code response is not a JSON object")

    creds = normalize_token_response(data)
    identity = await extract_account_identity(creds, http_client_factory=http_client_factory)
    if identity is not None:
        creds["account_identity"] = identity.as_dict()
        label = identity.label()
        if label is not None:
            creds["account_label"] = label
    return creds
