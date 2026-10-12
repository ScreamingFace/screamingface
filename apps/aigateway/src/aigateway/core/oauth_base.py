"""Template-method base for OAuth-backed credential strategies.

Owns the shared *credential* flow only: in-memory cache, double-checked
locking with an asyncio.Lock, and proactive refresh inside the lock. Provider
plugins implement four hooks: read, is_expired, refresh, build_headers (plus
an optional header_override for hybrid api-key paths).

This base does NOT detect auth failures. Upstream HTTP auth failures are a
transport concern handled in the chat route (`routes/chat.py`):
`_dispatch_failure_response` consults the provider plugin's
`should_mark_profile_error_on_dispatch_status` (`core/plugin_base.py`; anthropic
401, gemini/antigravity 401+403, base default never) and evicts the SHARED
strategy instance from the process-wide `CredentialStrategyCache`
(`core/credential_strategy_cache.py`) via its `evict()`. Credential read/refresh
errors raised before dispatch are also handled in the chat route's
`_inject_credentials` path. Eviction lives there, not here, because the cache
holds the one instance shared across a fan-out; `invalidate()` on this object
clears only its own `_cached`, not the shared entry the next request would reuse.

CONTRACT MIRROR (SF-335): this OAuth base mirrors the OAuth base in the SF
server (plugins/llm_base/oauth_base.py) *by contract, not by code*: NO shared
module, NO cross-app import. Keep in sync: refresh_window_seconds == 60;
refresh fires when (expiry - now) <= refresh_window_seconds; double-checked
asyncio.Lock single-flight; drop the cached strategy on an upstream auth
failure. If you change refresh_window_seconds here, change it in the other app.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

from .errors import RefreshSuperseded
from .plugin_base import CredentialStrategy

if TYPE_CHECKING:
    from .credential_blob.store import CredentialBlobStore

# WHY bounded: a writer rewriting the credential on every read must not spin a request forever.
_LOAD_ATTEMPTS = 3


class RefreshPublication(Protocol):
    """Where a refreshed token is published (OME-1497, G0 §5.3) — the port the app binds.

    `capture` observes the stored credential; the strategy takes it around its own read, so the
    observation names exactly the credential it holds. `publish` runs after the provider round
    trip, calls `write` only while that observation still holds (raising `RefreshSuperseded`
    otherwise) and returns the observation of what it wrote. Refresh is not an ownership change:
    neither may advance it.
    """

    async def capture(self) -> object: ...

    async def publish(self, captured: object, write: Callable[[], Awaitable[None]]) -> object: ...


class _DirectPublication:
    """Today's unguarded write — for a strategy built outside the app's guarded sites."""

    async def capture(self) -> object:
        return None

    async def publish(self, captured: object, write: Callable[[], Awaitable[None]]) -> object:
        del captured
        await write()
        return None


class BaseOAuthStrategy(CredentialStrategy):
    """Cached, locked, proactively-refreshed OAuth strategy.

    `refresh_window_seconds` controls how long before actual expiry a
    refresh kicks in. 60s matches what Claude Code, Codex CLI, and Gemini
    CLI all do.
    """

    refresh_window_seconds: int = 60
    _store: CredentialBlobStore

    def __init__(self, profile_name: str) -> None:
        self.profile_name = profile_name
        self._cached: dict | None = None
        # WHY beside `_cached`: the observation of the stored credential `_cached` came from; a
        # refresh publishes only while the store still holds exactly that credential. It is
        # meaningful only with `_cached` — every path that drops the cache re-takes it in `_load`,
        # and `persist_credentials` leaves an observation its own write has already outdated, so
        # a refresh of persisted tokens without a reload loses rather than overwrites.
        self._observed: object = None
        self._lock = asyncio.Lock()
        self._publication: RefreshPublication = _DirectPublication()

    def bind_refresh_publication(self, publication: RefreshPublication) -> None:
        """Route every later refresh through `publication` (the app binds its owner guard)."""
        self._publication = publication

    async def _load(self) -> dict[str, Any]:
        """Read the stored credential together with the observation of it; call under `_lock`.

        # INVARIANT (OME-1497, G0 §5.3): the observation brackets the read — equal before and
        # after, so it names the credential that was read and not one written a moment later. A
        # credential that keeps changing under the read is not refreshed at all.
        """
        for _ in range(_LOAD_ATTEMPTS):
            before = await self._publication.capture()
            creds = await self._read_credential()
            if await self._publication.capture() == before:
                self._observed = before
                return creds
        raise RefreshSuperseded("the stored credential kept changing while it was read")

    async def _refresh_and_publish(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Fetch outside any transaction, then publish under the guard; call under `_lock`.

        # INVARIANT (OME-1497, G0 §5.3): the publication checks the observation taken when
        # `creds` were read (`_load`) or last published — never one taken at refresh time, which
        # would bless a credential rewritten after `creds` were cached. A lost publication drops
        # the cache: the fetched tokens belong to a credential the store no longer holds.
        """
        captured = self._observed
        refreshed = await self._refresh_credential(creds)

        async def write() -> None:
            await self._write_to_store(refreshed)

        try:
            self._observed = await self._publication.publish(captured, write)
        except RefreshSuperseded:
            self._cached = None
            raise
        return refreshed

    async def get_token_with_expiry(self) -> tuple[str, int, bool]:
        """Return (access_token, expires_at_ms, refreshed), refreshing if needed.

        ``refreshed`` is True when an upstream refresh actually occurred, so the
        caller can update connection refresh metadata. Used by GET
        /v1/oauth/connections/{id}/token. All three providers (anthropic, codex,
        gemini) normalize creds to {access_token, expires_at_ms} in
        _read_credential / _refresh_credential, so a base-class implementation
        is correct for every concrete subclass.
        """
        refreshed = False
        async with self._lock:
            if self._cached is None:
                self._cached = await self._load()
            if self._is_expired(self._cached):
                self._cached = await self._refresh_and_publish(self._cached)
                refreshed = True
        return self._cached["access_token"], int(self._cached["expires_at_ms"]), refreshed

    async def get_authorization_header(self) -> dict[str, str]:
        override = self._header_override()
        if override is not None:
            return override

        if self._cached is not None and not self._is_expired(self._cached):
            return self._build_headers(self._cached)

        async with self._lock:
            if self._cached is None:
                self._cached = await self._load()
            if self._is_expired(self._cached):
                self._cached = await self._refresh_and_publish(self._cached)

        return self._build_headers(self._cached)

    async def invalidate(self) -> None:
        self._cached = None

    async def refresh(self) -> None:
        async with self._lock:
            if self._cached is None:
                self._cached = await self._load()
            self._cached = await self._refresh_and_publish(self._cached)

    async def persist_credentials(self, credentials: dict[str, Any]) -> None:
        """Store a credential blob after callback's code-for-token exchange."""
        self._cached = credentials
        await self._write_to_store(credentials)

    async def delete_credentials(self) -> None:
        self._cached = None
        await self._store.delete(self.credential_service(), self.credential_account())

    async def refresh_credentials(self) -> None:
        await self.refresh()

    @abstractmethod
    def credential_service(self) -> str:
        """Credential blob `service` string for this profile's tokens."""

    @abstractmethod
    def credential_account(self) -> str:
        """Credential blob `account` string for this profile's tokens."""

    @abstractmethod
    async def _write_to_store(self, creds: dict[str, Any]) -> None:
        """Persist `creds` to the credential blob store."""

    def _header_override(self) -> dict[str, str] | None:
        """Override to short-circuit OAuth (e.g. when an API-key env var is set)."""
        return None

    @abstractmethod
    async def _read_credential(self) -> dict[str, Any]: ...

    @abstractmethod
    def _is_expired(self, creds: dict[str, Any]) -> bool: ...

    @abstractmethod
    async def _refresh_credential(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Fetch and normalize refreshed tokens — network only, never a store write (§5.3)."""

    @abstractmethod
    def _build_headers(self, creds: dict[str, Any]) -> dict[str, str]: ...
