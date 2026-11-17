"""Process-wide cache of credential strategy instances (SF-282).

Concurrent ``POST /v1/chat/completions`` requests for the same credential must
share ONE strategy instance so its ``asyncio.Lock`` single-flights the OAuth
refresh. Without this, each request built a fresh ``BaseOAuthStrategy`` with its
own per-instance lock, so a fan-out (e.g. a 33-row eval) refreshed the same
rotating OAuth token N times in parallel and the provider rejected the racers
(Anthropic returns ``429 refresh_token_conflict``).

``get_or_create`` and ``evict`` are intentionally **synchronous**: asyncio is
single-threaded and neither method contains an ``await``, so check-then-insert
is atomic without a lock. The actual refresh single-flight is the shared
strategy's own lock (``BaseOAuthStrategy._lock``), not this cache.

The cache MUST be evicted on every credential mutation (OAuth re-auth, delete,
manual refresh) so a cached, not-yet-expired access token cannot outlive the
stored credential. API-key strategies hold no in-memory token (they read the
store on every call), so api-key paths do not require eviction.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# (provider, auth_type, credential_name) — provider distinguishes same-named
# connections across providers; auth_type distinguishes oauth vs api_key strategies.
StrategyKey = tuple[str, str, str]


class CredentialStrategyCache:
    """Caches one credential-strategy instance per (provider, auth_type, name)."""

    def __init__(self) -> None:
        self._cache: dict[StrategyKey, Any] = {}

    def get_or_create(
        self,
        *,
        provider: str,
        auth_type: str,
        credential_name: str,
        build: Callable[[], Any],
    ) -> Any:
        """Return the cached strategy for the key, building + caching on miss.

        ``build`` is only invoked on a miss. A ``None`` build result is not
        cached (matches ``credential_strategy_from`` returning ``None``).
        """
        key = (provider, auth_type, credential_name)
        strategy = self._cache.get(key)
        if strategy is None:
            strategy = build()
            if strategy is not None:
                self._cache[key] = strategy
        return strategy

    def evict(self, credential_name: str) -> int:
        """Drop every cached strategy for ``credential_name`` (any provider/auth).

        Returns the count evicted. Call on any mutation of the credential.
        """
        stale = [key for key in self._cache if key[2] == credential_name]
        for key in stale:
            self._cache.pop(key, None)
        return len(stale)

    def clear(self) -> None:
        self._cache.clear()


def credential_strategy_cache(app: Any) -> CredentialStrategyCache:
    """Get-or-create the app-wide cache on ``app.state`` (token-service pattern)."""
    state = getattr(app, "state", None)
    if state is None:
        raise RuntimeError("AIGateway app state is unavailable")
    cache = getattr(state, "credential_strategy_cache", None)
    if not isinstance(cache, CredentialStrategyCache):
        cache = CredentialStrategyCache()
        state.credential_strategy_cache = cache
    return cache
