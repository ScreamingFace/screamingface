"""OME-479 §5.2/§5.3 — the shared discovery runtime behind the DETAILED contract.

FEATURE: honest freshness on ``/v1/model-parameters``. This is the one place that
turns a provider's declared discovery source into a cached snapshot plus the
locked v1 ``freshness`` window (§6.2). It owns the bounded HTTP client, the
observation cache and the wall clock, so no provider has to invent a cache policy
and no route has to hand-roll a timestamp.

INVARIANT (evidence, never authorization): a snapshot returned here NEVER enables
a parameter — only a provider-local rule does. Callers overlay this evidence onto
rules; on its own it authorizes nothing.

INVARIANT (off the critical path): only listing/contract surfaces consume this —
the detailed-contract route's per-model observations, model admission (OME-879),
and the live model catalog (OME-972) via the shared client/limits. Chat dispatch
holds no reference to it, so no chat request can ever wait on a network fetch.

INVARIANT (no caller URLs): ``observe`` takes a model id and nothing else. The URL
comes from the provider's own fixed allowlisted constants — never a caller-supplied
or response-derived URL, never a followed redirect.

INVARIANT (credentials, narrowed by OME-1026): no credential is in scope on the
``observe`` path, which reads PUBLIC catalogs only. That is not true of every consumer
of the shared client: the PRIVATE profile catalog
(``core.profile_model_catalog``) dials a provider's credentialed-only listing with ONE
authenticated profile's OWN stored credential, projected into headers by that
profile's credential strategy and sent only to the provider's own allowlisted origin.
Its result is cached under that profile's private identity and served only to its
owner. There is deliberately NO deployment-wide discovery credential: an
operator-configured key would make one party's entitlements the whole deployment's
listing, which is why ``PUBLIC_GLOBAL`` discovery is defined as "no credential was
used to fetch it" rather than "no credential was needed".
AIDEV-NOTE: adding request logging or an httpx event hook to this shared client can
now touch an ACCOUNT credential — one profile's own. It could not before OME-1026.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from .parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    DiscoverySourceRef,
)

if TYPE_CHECKING:
    from .chat_parameters import ProviderDiscoverySnapshot
    from .parameter_discovery_cache import CacheLimits, CacheOutcome
    from .profile_models import AuthMode

# Unit separator: forbidden in a source name, a canonical model id and a revision
# alike, so the joined key cannot collide across differently-split triples.
_KEY_SEP = "\x1f"


class EvidenceCache(Protocol):
    """The cache port this runtime needs — bounded, revision-guarded, single-flight."""

    @property
    def limits(self) -> CacheLimits: ...

    async def get_or_refresh(
        self, key: str, *, revision: str, refresh: Callable[[], Awaitable[Any]]
    ) -> CacheOutcome: ...


class DiscoverablePlugin(Protocol):
    """The provider port this runtime drives (both hooks default to "no source")."""

    def chat_discovery_source(self, *, model: str) -> DiscoverySourceRef | None: ...

    async def discover_chat_parameter_snapshot(
        self,
        *,
        model: str,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
    ) -> ProviderDiscoverySnapshot | None: ...


class AuthScopedDiscoverablePlugin(Protocol):
    """The provider port BEFORE one contract read's auth mode is bound.

    A provider whose auth modes reach DIFFERENT upstreams cannot answer "is there
    a dynamic source for this model" without the resolved mode: an api-key path
    may talk to an API that publishes a machine-readable schema while the same
    provider's OAuth path talks to one that does not.
    """

    def chat_discovery_source(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> DiscoverySourceRef | None: ...

    async def discover_chat_parameter_snapshot(
        self,
        *,
        model: str,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
        auth_type: AuthMode | None = None,
    ) -> ProviderDiscoverySnapshot | None: ...


@dataclass(frozen=True)
class _AuthScopedView:
    """One provider seen through one contract read's resolved auth mode."""

    plugin: AuthScopedDiscoverablePlugin
    auth_type: AuthMode | None

    def chat_discovery_source(self, *, model: str) -> DiscoverySourceRef | None:
        return self.plugin.chat_discovery_source(model=model, auth_type=self.auth_type)

    async def discover_chat_parameter_snapshot(
        self,
        *,
        model: str,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
    ) -> ProviderDiscoverySnapshot | None:
        return await self.plugin.discover_chat_parameter_snapshot(
            model=model, client=client, limits=limits, auth_type=self.auth_type
        )


def auth_scoped(
    plugin: AuthScopedDiscoverablePlugin, auth_type: AuthMode | None
) -> DiscoverablePlugin:
    """Bind a contract read's auth mode to a provider's discovery hooks.

    # WHY the mode is bound HERE rather than threaded through ``observe``: the
    # runtime never reads it. It caches by (source, model, revision) and dials
    # whatever the provider declared. Passing a value the runtime only forwards
    # would put provider-shaped knowledge in ``DiscoverablePlugin`` and break every
    # auth-independent provider and test double that satisfies it today.
    #
    # INVARIANT (cache identity): auth is deliberately ABSENT from the cache key. A
    # provider whose snapshot CONTENT varies by mode must say so in the ref itself —
    # a different ``source`` or ``revision`` keys separately. Declaring no ref at
    # all (the honest answer when an upstream publishes nothing) forms no key.
    # INVARIANT: binds BOTH hooks with the SAME mode, so a provider's one predicate
    # cannot be consulted with two different answers.
    """
    return _AuthScopedView(plugin=plugin, auth_type=auth_type)


@dataclass(frozen=True)
class DiscoveryOutcome:
    """What one contract read learned from discovery: the evidence and its window."""

    snapshot: ProviderDiscoverySnapshot | None
    freshness: dict[str, Any]


@dataclass(frozen=True)
class _Observed:
    """The cached value: a snapshot bound to the wall-clock instant it was fetched.

    # WHY the timestamp is cached WITH the snapshot rather than derived on read:
    # the published window must describe when the EVIDENCE was observed. Stamping
    # it at read time would restamp a cache hit — and would restamp a STALE hit
    # as if the source had just answered.
    """

    snapshot: ProviderDiscoverySnapshot
    observed_at: datetime


def _window(observed_at: datetime | None, expires_at: datetime | None) -> dict[str, Any]:
    return {
        "observed_at": _iso(observed_at),
        "expires_at": _iso(expires_at),
        "stale": False,
        "degraded": False,
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def static_discovery_outcome() -> DiscoveryOutcome:
    """The window for a contract with no dynamic source: never observed.

    # WHY null timestamps rather than ``degraded``: "this provider publishes no
    # machine-readable catalog" is a different claim from "its catalog went
    # unreachable". Reporting degradation for the former would tell a client the
    # contract is untrustworthy when it is exactly as trustworthy as it will ever
    # be — the static observations ARE the evidence.
    # AIDEV-NOTE: returns a FRESH dict each call. The document composer embeds it
    # by reference, so a shared constant would let one response mutate another's.
    """
    return DiscoveryOutcome(snapshot=None, freshness=_window(None, None))


class DiscoveryRuntime:
    """Fetches a provider's public evidence through the bounded client and cache."""

    def __init__(
        self,
        *,
        client: DiscoveryHttpClient,
        cache: EvidenceCache,
        limits: DiscoveryLimits,
        now_utc: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._cache = cache
        self._limits = limits
        self._now_utc = now_utc

    @property
    def limits(self) -> DiscoveryLimits:
        return self._limits

    @property
    def client(self) -> DiscoveryHttpClient:
        # OME-879: the admit route reuses the SAME bounded transport for its
        # catalog-membership check, so admission gains no new egress surface.
        return self._client

    @property
    def cache(self) -> EvidenceCache:
        return self._cache

    async def observe(self, plugin: DiscoverablePlugin, *, model: str) -> DiscoveryOutcome:
        """Return this provider's cached evidence for ``model`` and its freshness window.

        # INVARIANT: the cache identity is (source, canonical model, source
        # revision) — evidence observed for one triple is never served for
        # another, so a parser change or a source swap cannot silently reuse
        # values gathered under the old reading.
        """
        ref = plugin.chat_discovery_source(model=model)
        if ref is None:
            return static_discovery_outcome()

        async def _refresh() -> _Observed:
            snapshot = await plugin.discover_chat_parameter_snapshot(
                model=model, client=self._client, limits=self._limits
            )
            if snapshot is None:
                # A provider that declares a source and then reports NOT ATTEMPTED
                # is inconsistent. Returning normally would have the cache store
                # "no evidence" as a successful refresh — labelled fresh, and
                # evicting the last good snapshot. Fail the attempt instead.
                raise DiscoveryError("no_snapshot")
            if snapshot.source_revision != ref.revision:
                # INVARIANT (OME-648): the entry is keyed by the revision the provider
                # declared BEFORE the fetch, while the evidence carries its own stamp.
                # Storing a disagreeing snapshot would file it under a reading that did
                # not produce it, and then serve it for that reading until the window
                # closed — the revision guard's whole purpose, defeated from inside.
                # Same disposal as any other bad attempt: fail, so the last good entry
                # survives and the honest stale/degraded signal reaches the client.
                raise DiscoveryError("revision_mismatch")
            return _Observed(snapshot=snapshot, observed_at=self._now_utc())

        outcome = await self._cache.get_or_refresh(
            _cache_key(ref, model), revision=ref.revision, refresh=_refresh
        )
        return self._compose(outcome)

    def _compose(self, outcome: CacheOutcome) -> DiscoveryOutcome:
        # INVARIANT (§5.3): ``degraded`` is exactly the outcome that carries no
        # value — the cache never labels a usable entry degraded, and never omits
        # the label for a missing one.
        observed: _Observed | None = None if outcome.freshness == "degraded" else outcome.value
        if observed is None:
            # Fail-closed: no snapshot AND no window. A degraded contract must not
            # carry timestamps that imply evidence stands behind it.
            return DiscoveryOutcome(
                snapshot=None,
                freshness={
                    "observed_at": None,
                    "expires_at": None,
                    "stale": False,
                    "degraded": True,
                },
            )
        expires_at = observed.observed_at + timedelta(seconds=self._cache.limits.ttl_s)
        freshness = _window(observed.observed_at, expires_at)
        freshness["stale"] = outcome.freshness == "stale"
        return DiscoveryOutcome(snapshot=observed.snapshot, freshness=freshness)


def _cache_key(ref: DiscoverySourceRef, model: str) -> str:
    return _KEY_SEP.join((ref.source, model, ref.revision))
