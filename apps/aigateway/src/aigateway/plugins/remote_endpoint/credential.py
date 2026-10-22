"""A stored key, bound to the origin of the endpoint it was validated on.

# FEATURE: hosted BYOM — an endpoint ID is a durable credential identity, while its origin is
# configuration that a restart can change.
# INVARIANT: a key is served only for the origin recorded beside it in its encrypted blob. A blob
# for another origin, or for none, reads as a missing key: the route refuses with `auth_required`
# and sends nothing, and the admin's normal replacement, validated on the current origin, rebinds.
# WHY in the blob and not in the key namespace: the pair's locator stays the provider ID, so admin
# replacement and DELETE still find the pair after a move; only dispatch is fenced.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from aigateway.core.api_key_strategy import API_KEY_AUTH_TYPE, ApiKeyStrategy
from aigateway.core.credential_blob import CredentialBlobStore
from aigateway.core.errors import AuthError, CredentialNotFoundError


class OriginBoundApiKeyStrategy(ApiKeyStrategy):
    def __init__(
        self,
        profile_name: str,
        *,
        origin: str,
        service: str,
        account: str,
        header_builder: Callable[[str], dict[str, str]],
        credential_store: CredentialBlobStore | None = None,
    ) -> None:
        super().__init__(
            profile_name,
            service=service,
            account=account,
            header_builder=header_builder,
            credential_store=credential_store,
        )
        self._origin = origin

    async def persist_credentials(self, credentials: dict[str, Any]) -> None:
        api_key = credentials.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            raise AuthError("API-key credentials must include a non-empty 'api_key'")
        blob = {"auth_type": API_KEY_AUTH_TYPE, "api_key": api_key, "origin": self._origin}
        await self._store.write(self._service, self._account, json.dumps(blob))

    async def _read_api_key(self) -> str:
        # INVARIANT: ONE read. Checking the origin on one read and taking the key from another
        # would let a concurrent replacement pair this origin's check with a different key.
        raw = await self._store.read(self._service, self._account)
        try:
            blob = json.loads(raw) if raw is not None else None
        except json.JSONDecodeError:
            blob = None
        api_key = blob.get("api_key") if isinstance(blob, dict) else None
        if (
            isinstance(blob, dict)
            and blob.get("auth_type") == API_KEY_AUTH_TYPE
            and blob.get("origin") == self._origin
            and isinstance(api_key, str)
            and api_key
        ):
            return api_key
        # WHY "missing", never AuthError: an AuthError marks the Connection errored, but a key
        # stored for another origin is not a rejected key. If that origin comes back, the key
        # serves again. The message names no origin: the configured origins are private.
        raise CredentialNotFoundError(
            f"No API key stored for {self.profile_name!r} matches this endpoint. "
            "Replace the key for this connection."
        )
