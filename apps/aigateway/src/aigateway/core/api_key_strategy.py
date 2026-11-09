"""Per-connection DB-backed API-key credential strategy.

Implements the :class:`CredentialStrategy` port directly rather than
subclassing :class:`~aigateway.core.oauth_base.BaseOAuthStrategy`: API keys
have no expiry or refresh contract, so inheriting the OAuth template method
would drag in dead contract. Reads go to the store on every call — strategies
are constructed per request, so there is no cross-request cache to manage.

Core stays provider-agnostic: each provider plugin instantiates this class
with its own credential ``service``/``account`` strings and a
``header_builder`` that maps the raw key to the provider's auth header(s).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .credential_blob.store import ORMStore
from .errors import AuthError, CredentialNotFoundError
from .plugin_base import CredentialStrategy

if TYPE_CHECKING:
    from collections.abc import Callable

    from .credential_blob.store import CredentialBlobStore

API_KEY_AUTH_TYPE = "api_key"


class ApiKeyStrategy(CredentialStrategy):
    """Serve provider auth headers from a stored raw API key."""

    def __init__(
        self,
        credential_name: str,
        *,
        service: str,
        account: str,
        header_builder: Callable[[str], dict[str, str]],
        credential_store: CredentialBlobStore | None = None,
    ) -> None:
        self.credential_name = credential_name
        self._service = service
        self._account = account
        self._header_builder = header_builder
        self._store = credential_store or ORMStore()

    def credential_service(self) -> str:
        return self._service

    def credential_account(self) -> str:
        return self._account

    async def get_authorization_header(self) -> dict[str, str]:
        return self._header_builder(await self._read_api_key())

    async def persist_credentials(self, credentials: dict[str, Any]) -> None:
        api_key = credentials.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            raise AuthError("API-key credentials must include a non-empty 'api_key'")
        blob = {"auth_type": API_KEY_AUTH_TYPE, "api_key": api_key}
        await self._store.write(self._service, self._account, json.dumps(blob))

    async def delete_credentials(self) -> None:
        await self._store.delete(self._service, self._account)

    async def refresh_credentials(self) -> None:
        """Raw API keys cannot be refreshed, only replaced — but a refresh
        must not report success for a connection whose blob is gone or corrupt
        (SF-244 audit F09), so re-validate that a well-formed key exists."""
        await self._read_api_key()

    async def _read_api_key(self) -> str:
        raw = await self._store.read(self._service, self._account)
        if raw is None:
            raise CredentialNotFoundError(
                f"No API key stored for {self.credential_name!r}. "
                "Set or replace the key for this connection."
            )
        try:
            creds = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthError(
                f"API-key blob for {self.credential_name!r} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(creds, dict) or creds.get("auth_type") != API_KEY_AUTH_TYPE:
            raise AuthError(
                f"Credential blob for {self.credential_name!r} is not an API-key blob; "
                "re-set the key or re-authenticate via OAuth."
            )
        api_key = creds.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            raise AuthError(f"API-key blob for {self.credential_name!r} missing 'api_key'")
        return api_key
