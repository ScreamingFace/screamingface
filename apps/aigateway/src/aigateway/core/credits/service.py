"""Caller-scoped credit reads and write-only, inference-bound management credentials."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from . import CreditAmount, CreditProvider, CreditReading, CreditStatus, unavailable

_SERVICE = "provider-credit-management"
_TTL = 300
_MAX_ENTRIES = 256
_MAX_RETRY_DELAY = 1800
_TRANSIENT = frozenset({"lookup_failed", "invalid_response"})


@dataclass(frozen=True)
class _CacheEntry:
    observation: CreditStatus
    refresh_after: float
    failures: int
    scope: tuple[str, str]


class SecretStore(Protocol):
    async def read(self, service: str, account: str) -> str | None: ...
    async def write(self, service: str, account: str, value: str) -> None: ...
    async def delete(self, service: str, account: str) -> None: ...


class ManagementKeyRejected(Exception):
    """The provider did not establish a usable, matching account balance."""


class CreditStoreUnavailable(Exception):
    """A credential-store failure with no secret-bearing cause exposed."""


class CreditService:
    """FEATURE: E5 P3. Bound cache, separate amounts and no inference credential fallback."""

    def __init__(self, store: SecretStore, providers: Mapping[str, CreditProvider]) -> None:
        self._store = store
        self._providers = providers
        self._salt = secrets.token_bytes(32)
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._inflight: dict[str, asyncio.Task[CreditStatus]] = {}

    def supports(self, provider: str) -> bool:
        return provider in self._providers

    async def read(
        self,
        account: str,
        provider: str,
        api_key: str | None,
        *,
        refresh: bool,
        include_account: bool = True,
    ) -> CreditStatus:
        if not self.supports(provider) or api_key is None:
            reason = "unsupported" if not self.supports(provider) else "not_connected"
            return CreditStatus(
                provider=provider, account=unavailable(reason), key=unavailable(reason)
            )
        management, store_failed = None, False
        if include_account:
            try:
                management = await self._management(account, provider, api_key)
            except CreditStoreUnavailable:
                # Keep key allowance readable, with the same request-sharing and retry bounds.
                store_failed = True
        token = hmac.new(
            self._salt,
            json.dumps(
                [account, provider, api_key, management, store_failed, include_account]
            ).encode(),
            "sha256",
        ).hexdigest()
        cached = self._cache.get(token)
        if not refresh and cached is not None and time.monotonic() < cached.refresh_after:
            return cached.observation
        task = self._inflight.get(token)
        if task is None:
            if len(self._inflight) >= _MAX_ENTRIES:
                return CreditStatus(
                    provider=provider,
                    account=unavailable("lookup_failed"),
                    key=unavailable("lookup_failed"),
                )
            task = asyncio.create_task(
                self._observe(
                    (account, provider),
                    api_key,
                    management,
                    token,
                    store_failed=store_failed,
                    include_account=include_account,
                )
            )
            self._inflight[token] = task
            task.add_done_callback(lambda _: self._inflight.pop(token, None))
        # WHY: one disconnected HTTP client must not cancel a lookup another client awaits.
        result = await asyncio.shield(task)
        if not include_account:
            return result
        try:
            current_management = await self._management(account, provider, api_key)
        except CreditStoreUnavailable:
            current_management = None
        if management != current_management:
            self._cache.pop(token, None)
            return CreditStatus(
                provider=provider,
                account=unavailable("lookup_failed"),
                key=result.key,
            )
        return result

    async def _observe(
        self,
        scope: tuple[str, str],
        api_key: str,
        management: str | None,
        token: str,
        *,
        store_failed: bool,
        include_account: bool,
    ) -> CreditStatus:
        provider = scope[1]
        reading = await self._read_provider(provider, api_key, management)
        if not include_account:
            reading = CreditReading(account=unavailable("hosted_unavailable"), key=reading.key)
        elif store_failed:
            reading = CreditReading(account=unavailable("lookup_failed"), key=reading.key)
        previous = self._cache.get(token)
        account, key = reading.account, reading.key
        if previous is not None:
            account = _retain(account, previous.observation.account)
            key = _retain(key, previous.observation.key)
        result = CreditStatus(
            provider=provider,
            connection_token=token,
            account=account,
            key=key,
            management_key_configured=management is not None,
        )
        failed = any(amount.reason in _TRANSIENT for amount in (reading.account, reading.key))
        failures = min(4, (previous.failures if previous else 0) + 1) if failed else 0
        delay = min(_MAX_RETRY_DELAY, _TTL * 2 ** max(0, failures - 1))
        self._cache[token] = _CacheEntry(result, time.monotonic() + delay, failures, scope)
        self._cache.move_to_end(token)
        while len(self._cache) > _MAX_ENTRIES:
            self._cache.popitem(last=False)
        return result

    async def _read_provider(
        self, provider: str, api_key: str, management: str | None
    ) -> CreditReading:
        try:
            return await self._providers[provider].read(api_key, management)
        except Exception:
            # Provider exceptions can contain request headers. Keep them off the HTTP boundary.
            return CreditReading(
                account=unavailable("lookup_failed"), key=unavailable("lookup_failed")
            )

    async def aclose(self) -> None:
        """Cancel and await app-owned requests before credential storage is shut down."""
        tasks = tuple(self._inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()
        self._cache.clear()

    async def configure(
        self, account: str, provider: str, api_key: str, management_key: str
    ) -> None:
        adapter = self._providers.get(provider)
        if adapter is None:
            raise ManagementKeyRejected()
        result = await self._read_provider(provider, api_key, management_key)
        if result.account.status != "available":
            raise ManagementKeyRejected()
        payload = json.dumps({"key": management_key, "inference": _fingerprint(api_key)})
        try:
            # INVARIANT: the injected production store is ORMStore; it encrypts this slot.
            await self._store.write(_SERVICE, _slot(account, provider), payload)
        except Exception:
            raise CreditStoreUnavailable() from None
        self._invalidate(account, provider)

    async def remove(self, account: str, provider: str) -> None:
        try:
            await self._store.delete(_SERVICE, _slot(account, provider))
        except Exception:
            raise CreditStoreUnavailable() from None
        self._invalidate(account, provider)

    def _invalidate(self, account: str, provider: str) -> None:
        scope = (account, provider)
        for token in [token for token, entry in self._cache.items() if entry.scope == scope]:
            del self._cache[token]

    async def _management(self, account: str, provider: str, api_key: str) -> str | None:
        try:
            raw = await self._store.read(_SERVICE, _slot(account, provider))
        except Exception:
            raise CreditStoreUnavailable() from None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("invalid credential")
            key = payload.get("key")
            if payload.get("inference") != _fingerprint(api_key):
                return None
            if not isinstance(key, str) or not key:
                raise ValueError("invalid credential")
            return key
        except (ValueError, TypeError):
            raise CreditStoreUnavailable() from None


def _slot(account: str, provider: str) -> str:
    return json.dumps([account, provider], separators=(",", ":"))


def _fingerprint(secret: str) -> str:
    # WHY: this binding is stored only INSIDE the encrypted credential blob, never on the wire.
    return hashlib.sha256(secret.encode()).hexdigest()


def _retain(current: CreditAmount, previous: CreditAmount) -> CreditAmount:
    if current.reason in _TRANSIENT and previous.amount_usd is not None:
        return previous.model_copy(update={"status": "stale", "reason": current.reason})
    return current
