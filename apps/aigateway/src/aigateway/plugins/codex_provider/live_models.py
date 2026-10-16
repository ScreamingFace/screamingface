"""OME-1634 — the live Codex model list, per ChatGPT account.

FEATURE: live Codex model discovery — the models a signed-in ChatGPT account can use, read
from ``GET /backend-api/codex/models`` instead of a static list (whose slugs went dead: every
one of them was refused even on a plus plan, verified 2026-10-16).

WHY per account, not through the OME-972 injected client: the endpoint needs the account's
bearer token and answers per account, while the listing port (``discover_live_models``) is
process-wide and its injected client is deliberately credential-free. So this directory
dials ONLY with a credential a dispatch hands it (today: the refusal path), caches per
account id, and the listing port serves the most recently refreshed list without dialing.
It never enumerates stored profiles — no cross-tenant credential reads.

INVARIANT (fail closed, all-or-nothing): a malformed, empty, or oversized catalog raises a
sanitized ``DiscoveryError`` and never replaces the last good list. Live data changes what is
LISTED and what a refusal suggests — never what is dispatchable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    HttpxDiscoveryClient,
    fetch_discovery_json,
)
from aigateway.core.parameter_discovery_cache import (
    CacheLimits,
    MonotonicClock,
    ObservationCache,
    SystemMonotonicClock,
)
from aigateway.core.plugin_base import ModelDiscoverySource, ModelEntry

from .auth import account_id_from_token

# WHY this client_version: the backend filters its list by client version; 0.154.0 is the
# version the 2026-10-16 live probe returned the current models for.
CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models?client_version=0.154.0"
_ALLOWED_ORIGINS = frozenset({"https://chatgpt.com"})
_ORIGINATOR = "codex_cli_rs"
_GATEWAY_PREFIX = "codex/"
_MAX_LISTED = 200
_MAX_SLUG_LENGTH = 128
_MAX_ACCOUNTS = 256

_REVISION = "codex:models:list-v1"
_TTL_S = 300.0
_STALE_TTL_S = 3600.0
_FAILURE_TTL_S = 30.0

# WHY a short listing TTL: the catalog's refresh only reads this process's directory (no
# dial), so it can follow a new account refresh quickly at no upstream cost.
LIVE_MODELS_DISCOVERY_SOURCE = ModelDiscoverySource(
    key="codex:models:list",
    revision=_REVISION,
    ttl_s=30.0,
    stale_ttl_s=_STALE_TTL_S,
    failure_ttl_s=_FAILURE_TTL_S,
)

ClientFactory = Callable[[dict[str, str]], DiscoveryHttpClient]


def _default_client_factory(headers: dict[str, str]) -> DiscoveryHttpClient:
    return HttpxDiscoveryClient(headers=headers)


def parse_listed_slugs(payload: Any) -> tuple[str, ...]:
    """The ``visibility == "list"`` slugs of a catalog, first-seen order, deduplicated.

    STRICT: the envelope must be ``{"models": [...]}`` and every row an object with a
    non-empty string ``slug`` and a string ``visibility``; anything else is
    ``malformed_json`` — a row that cannot be read makes the census untrustworthy.
    """
    if not isinstance(payload, dict):
        raise DiscoveryError("malformed_json")
    rows = cast("dict[str, Any]", payload).get("models")
    if not isinstance(rows, list):
        raise DiscoveryError("malformed_json")
    listed: dict[str, None] = {}
    for row in cast("list[Any]", rows):
        if not isinstance(row, dict):
            raise DiscoveryError("malformed_json")
        typed = cast("dict[str, Any]", row)
        slug = typed.get("slug")
        visibility = typed.get("visibility")
        if not isinstance(slug, str) or not slug or len(slug) > _MAX_SLUG_LENGTH:
            raise DiscoveryError("malformed_json")
        if not isinstance(visibility, str):
            raise DiscoveryError("malformed_json")
        if visibility == "list":
            listed[slug] = None
    if not listed:
        raise DiscoveryError("model_catalog_empty")
    if len(listed) > _MAX_LISTED:
        raise DiscoveryError("model_catalog_too_large")
    return tuple(listed)


def gateway_entries(slugs: tuple[str, ...]) -> tuple[ModelEntry, ...]:
    return tuple(
        ModelEntry(model_name=f"{_GATEWAY_PREFIX}{slug}", litellm_params={"model": f"codex/{slug}"})
        for slug in slugs
    )


class CodexModelDirectory:
    """Per-account cached Codex model lists plus the most recent one for the listing."""

    def __init__(
        self,
        *,
        clock: MonotonicClock | None = None,
        client_factory: ClientFactory | None = None,
        limits: DiscoveryLimits | None = None,
    ) -> None:
        self._clock = clock if clock is not None else SystemMonotonicClock()
        self._client_factory = client_factory or _default_client_factory
        self._limits = limits if limits is not None else DiscoveryLimits()
        self._cache = ObservationCache(
            clock=self._clock,
            limits=CacheLimits(
                ttl_s=_TTL_S,
                stale_ttl_s=_STALE_TTL_S,
                max_entries=_MAX_ACCOUNTS,
                failure_ttl_s=_FAILURE_TTL_S,
            ),
        )
        self._latest: tuple[tuple[str, ...], float] | None = None

    async def slugs_for(
        self, access_token: str | None, *, account_id: str | None = None
    ) -> tuple[str, ...] | None:
        """This account's listed slugs, or ``None`` when unknown (never raises DiscoveryError).

        # WHY no dial without an account id: the backend scopes the list by
        # ``ChatGPT-Account-Id`` and the cache keys by it — without one there is
        # nothing to ask for and nothing to key.
        """
        account = account_id or account_id_from_token(access_token)
        if not access_token or not account:
            return None
        headers = {
            "Authorization": f"Bearer {access_token}",
            "ChatGPT-Account-Id": account,
            "originator": _ORIGINATOR,
            "accept": "application/json",
        }

        async def _refresh() -> tuple[str, ...]:
            payload = await fetch_discovery_json(
                CODEX_MODELS_URL,
                allowed_origins=_ALLOWED_ORIGINS,
                client=self._client_factory(headers),
                limits=self._limits,
            )
            slugs = parse_listed_slugs(payload)
            self._latest = (slugs, self._clock.now())
            return slugs

        outcome = await self._cache.get_or_refresh(account, revision=_REVISION, refresh=_refresh)
        return cast("tuple[str, ...] | None", outcome.value)

    def latest(self) -> tuple[str, ...] | None:
        """The most recently refreshed account list, inside the cache's trust window."""
        if self._latest is None:
            return None
        slugs, stored_at = self._latest
        # INVARIANT: the same window the cache serves a stale value in (ttl + stale).
        if self._clock.now() - stored_at > _TTL_S + _STALE_TTL_S:
            return None
        return slugs


# AIDEV-NOTE: process-wide singleton, read through the module attribute at call time so tests
# swap it with ``patch.object(live_models, "DIRECTORY", ...)``.
DIRECTORY = CodexModelDirectory()


async def available_models_for(
    access_token: str | None, *, account_id: str | None
) -> list[str] | None:
    """Gateway ids the account can use, or ``None`` when its list is unknown."""
    slugs = await DIRECTORY.slugs_for(access_token, account_id=account_id)
    if slugs is None:
        return None
    return [entry.model_name for entry in gateway_entries(slugs)]


def latest_listing() -> tuple[ModelEntry, ...]:
    """The listing rows from the most recent account refresh, or ``no_snapshot``."""
    slugs = DIRECTORY.latest()
    if slugs is None:
        raise DiscoveryError("no_snapshot")
    return gateway_entries(slugs)
