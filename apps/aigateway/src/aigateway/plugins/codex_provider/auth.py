from __future__ import annotations

import base64
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
from aigateway.core.oauth_base import BaseOAuthStrategy

from .oauth_config import CODEX_CLIENT_ID, CODEX_REFRESH_SCOPE, CODEX_TOKEN_URL

_ACCOUNT = "default"
_JWT_AUTH_CLAIMS_KEY = "https://api.openai.com/auth"


def credential_service_for(profile_name: str) -> str:
    return f"aigateway:codex:{profile_name}"


def _decode_jwt_claims(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _auth_claims(token: str | None) -> dict[str, Any]:
    claims = _decode_jwt_claims(token)
    nested = claims.get(_JWT_AUTH_CLAIMS_KEY)
    return nested if isinstance(nested, dict) else {}


def _expires_at_ms_from_token(token: str | None) -> int | None:
    exp = _decode_jwt_claims(token).get("exp")
    if isinstance(exp, int | float):
        return int(float(exp) * 1000)
    return None


def _account_id_from_tokens(access_token: str | None, id_token: str | None) -> str | None:
    for token in (id_token, access_token):
        account_id = _auth_claims(token).get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return None


def account_label_from_credentials(creds: dict[str, Any]) -> str | None:
    id_claims = _decode_jwt_claims(creds.get("id_token"))
    for key in ("email", "name"):
        value = id_claims.get(key)
        if isinstance(value, str) and value:
            return value
    account_id = creds.get("account_id") or _account_id_from_tokens(
        creds.get("access_token"), creds.get("id_token")
    )
    if isinstance(account_id, str) and account_id:
        return account_id
    subject = id_claims.get("sub")
    return subject if isinstance(subject, str) and subject else None


def _normalize_token_response(data: dict[str, Any], previous: dict[str, Any] | None = None) -> dict:
    previous = previous or {}
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise AuthError("OAuth response missing 'access_token'")

    refresh_token = data.get("refresh_token") or previous.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise AuthError("OAuth response missing 'refresh_token'")

    id_token = data.get("id_token") or previous.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise AuthError("OAuth response missing 'id_token'")

    raw_expires_at_ms = data.get("expires_at_ms", previous.get("expires_at_ms"))
    expires_at_ms = int(raw_expires_at_ms) if isinstance(raw_expires_at_ms, int | float) else None
    if expires_at_ms is None:
        raw_expires_at = data.get("expires_at") or previous.get("expires_at")
        if isinstance(raw_expires_at, int | float):
            expires_at_ms = int(float(raw_expires_at) * 1000)
    expires_at_ms = expires_at_ms or _expires_at_ms_from_token(access_token)
    expires_at_ms = expires_at_ms or _expires_at_ms_from_token(id_token)
    expires_in = data.get("expires_in")
    if expires_at_ms is None and isinstance(expires_in, int | float | str):
        try:
            expires_at_ms = int((time.time() + int(expires_in)) * 1000)
        except (TypeError, ValueError):
            expires_at_ms = None

    creds = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "token_type": data.get("token_type", previous.get("token_type", "Bearer")),
    }
    if expires_at_ms is not None:
        creds["expires_at_ms"] = expires_at_ms
    account_id = _account_id_from_tokens(access_token, id_token) or previous.get("account_id")
    if account_id:
        creds["account_id"] = account_id
    return creds


class CodexOAuth(BaseOAuthStrategy):
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

    async def _read_credential(self) -> dict:
        raw = await self._store.read(self.credential_service(), self.credential_account())
        if raw is None:
            raise CredentialNotFoundError(
                f"No tokens for codex profile {self.profile_name!r}. Re-authenticate via Electron."
            )
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthError(
                f"Token blob for {self.profile_name!r} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(loaded, dict):
            raise AuthError(f"Token blob for {self.profile_name!r} is not a JSON object")
        return _normalize_token_response(loaded, loaded)

    def _is_expired(self, creds: dict) -> bool:
        expires_at_ms = creds.get("expires_at_ms")
        if not isinstance(expires_at_ms, int | float) or expires_at_ms <= 0:
            expires_at_ms = _expires_at_ms_from_token(creds.get("access_token"))
        if expires_at_ms is None:
            return False
        return time.time() * 1000 >= expires_at_ms - (self.refresh_window_seconds * 1000)

    def _build_headers(self, creds: dict) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {creds['access_token']}"}
        account_id = creds.get("account_id")
        if isinstance(account_id, str) and account_id:
            headers["ChatGPT-Account-Id"] = account_id
        return headers

    async def _refresh_credential(self, creds: dict) -> dict:
        body = {
            "client_id": CODEX_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": creds["refresh_token"],
            "scope": CODEX_REFRESH_SCOPE,
        }
        try:
            async with self._http_factory() as client:
                resp = await client.post(
                    CODEX_TOKEN_URL,
                    data=body,
                    headers={"content-type": "application/x-www-form-urlencoded"},
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
        if not isinstance(data, dict):
            raise AuthError("OAuth refresh response is not a JSON object")

        refreshed = _normalize_token_response(data, creds)
        # WHY no write here (OME-1497, G0 §5.3): the strategy base publishes under the guard.
        return refreshed

    async def _write_to_store(self, creds: dict) -> None:
        await self._store.write(
            self.credential_service(), self.credential_account(), json.dumps(creds)
        )


async def exchange_authorization_code(
    code: str,
    code_verifier: str,
    *,
    redirect_uri: str,
    http_client_factory=None,
) -> dict:
    factory = http_client_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(30.0)))
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": CODEX_CLIENT_ID,
        "code_verifier": code_verifier,
    }
    try:
        async with factory() as client:
            resp = await client.post(
                CODEX_TOKEN_URL,
                data=body,
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
    except httpx.RequestError as exc:
        raise AuthError(f"Authorization code exchange endpoint unreachable: {exc}") from exc

    if resp.status_code != 200:
        raise AuthError(f"Authorization code exchange failed (HTTP {resp.status_code})")
    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise AuthError(f"Authorization code response not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AuthError("Authorization code response is not a JSON object")
    return _normalize_token_response(data)
