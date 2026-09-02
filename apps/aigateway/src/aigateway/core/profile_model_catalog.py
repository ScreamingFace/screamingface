"""OME-1026 — the PRIVATE per-profile live model catalog.

FEATURE: profile-scoped live model discovery. A provider whose catalog answers
"what may THIS credential call" (Anthropic today; direct OpenAI/Gemini next) gets
ONE private snapshot per authenticated account profile, fetched with that
profile's own stored credential and served only to its owner.

STORY: as an account owner who already stored an API key, I open my profile's
model list and see the models my own key can call — without re-entering the key,
and without my entitlements becoming the deployment's public listing.

This module owns ORCHESTRATION: the refusal gates that decide whether a
credentialed dial may happen at all, the bounded background refresh, and
supersede on credential change. The snapshot MEMORY and its freshness policy live
in :mod:`aigateway.core.profile_snapshot_store`.

INVARIANT (why the shared catalog cannot leak this): ``ModelCatalog`` refuses a
``PROFILE_CREDENTIAL`` provider outright, and a provider in that scope implements
``discover_profile_models`` — never the public ``discover_live_models``. So a
credential-derived listing has no code path into any DEPLOYMENT-GLOBAL cache:
``GET /v1/models`` shows it only to the caller whose effective credential fetched
it (OME-1026 U3), keyed by account + logical profile + durable revision.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from .background_error_sink import mark_observed
from .background_refresh import BackgroundRefreshManager
from .discovery_budget import user_wait_budget
from .effective_credential import DiscoveryCredentialTarget, profile_discovery_target
from .errors import AuthError, CredentialNotFoundError
from .model_discovery_scope import DiscoveryScope, ProviderAuthContext
from .parameter_discovery import DiscoveryError
from .profile_snapshot_store import (
    ProfileCacheKey,
    ProfileIdentity,
    ProfileModelSnapshot,
    ProfileSnapshotStore,
    profile_credential_revision,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Any

    from ..config import Settings
    from .parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
    from .parameter_discovery_cache import MonotonicClock
    from .plugin_base import ModelDiscoverySource, ModelEntry
    from .profile_models import AuthType, Profile

logger = logging.getLogger(__name__)

__all__ = [
    "PrivateModelListingProvider",
    "ProfileModelCatalog",
    "ProfileModelSnapshot",
    "build_profile_model_catalog",
    "profile_credential_revision",
]


class PrivateModelListingProvider(Protocol):
    """The provider surface this catalog consumes (hexagonal port).

    # WHY a Protocol and not ``ProviderPluginBase``: the catalog needs exactly
    # these members, and depending on the whole plugin contract would couple a
    # cache to every unrelated provider hook.
    """

    custom_llm_provider: str

    def model_discovery_scope(self) -> DiscoveryScope: ...

    def model_discovery_source(self) -> ModelDiscoverySource | None: ...

    def profile_discovery_unsupported_reason(self, *, auth_type: AuthType) -> str | None: ...

    async def discover_profile_models(
        self,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
        auth: ProviderAuthContext,
    ) -> tuple[ModelEntry, ...] | None: ...


class ProfileModelCatalog:
    """Bounded, deduplicated, stale-while-revalidate private catalogs."""

    def __init__(
        self,
        *,
        clock: MonotonicClock | None = None,
        max_identities: int,
        max_inflight_refreshes: int,
        wait_budget_s: float = 3.0,
        max_rows: int | None = None,
    ) -> None:
        # The user-facing budget. Bounds the WAIT only: a refresh that outlasts it
        # keeps running, and the next request observes its result.
        self.wait_budget_s = wait_budget_s
        # ``max_rows=None`` defers to the store's own documented default (F7), so a
        # caller that does not care about the memory budget cannot accidentally set one.
        store_bounds = {} if max_rows is None else {"max_rows": max_rows}
        self._store = ProfileSnapshotStore(
            clock=clock, max_identities=max_identities, **store_bounds
        )
        self._refreshes: BackgroundRefreshManager[ProfileCacheKey] = BackgroundRefreshManager(
            max_inflight=max_inflight_refreshes
        )

    @property
    def clock(self) -> MonotonicClock:
        return self._store.clock

    @property
    def tracked_identities(self) -> int:
        return self._store.tracked_identities

    @property
    def retained_rows(self) -> int:
        """Total private listing rows this process is holding (OME-1026 F7)."""
        return self._store.retained_rows

    @property
    def max_rows(self) -> int:
        """The HARD ceiling on :attr:`retained_rows` — no carve-out (OME-1026 F7)."""
        return self._store.max_rows

    @property
    def inflight_refreshes(self) -> int:
        return self._refreshes.inflight

    async def snapshot_for(
        self,
        plugin: PrivateModelListingProvider,
        *,
        account_id: str,
        profile: Profile,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None,
        auth_provider: Callable[[], Awaitable[ProviderAuthContext]],
        credential_generation: int,
        wait_budget_s: float | None = None,
    ) -> ProfileModelSnapshot:
        """``snapshot_for_target`` for a bare Profile + its durable generation.

        Kept as the Profile-shaped entry point so every pre-U2 caller (the explicit
        profile endpoint, the post-commit credential lifecycle) and its tests keep
        working verbatim; the ONE implementation lives in ``snapshot_for_target``.
        """
        return await self.snapshot_for_target(
            plugin,
            account_id=account_id,
            target=profile_discovery_target(profile, credential_generation),
            client=client,
            limits=limits,
            auth_provider=auth_provider,
            wait_budget_s=wait_budget_s,
        )

    async def snapshot_for_target(
        self,
        plugin: PrivateModelListingProvider,
        *,
        account_id: str,
        target: DiscoveryCredentialTarget,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None,
        auth_provider: Callable[[], Awaitable[ProviderAuthContext]],
        wait_budget_s: float | None = None,
    ) -> ProfileModelSnapshot:
        """This effective credential's private listing, with its trust label.

        ``target`` is any effective credential — hosted Profile or local Connection
        (OME-1026 U2); the catalog consumes only its name, auth type, authenticated
        state and durable revision, so both backings share every gate, bound and
        isolation property below.

        ``auth_provider`` is called ONLY when a dial is actually about to happen,
        and only from inside the background refresh.

        ``wait_budget_s`` overrides the instance budget for ONE call. A caller that
        only needs the work STARTED passes ``0.0``: the refresh begins and this
        coroutine returns without waiting, because the wait is a separate object from
        the work (see ``BackgroundRefreshManager.wait_up_to``).

        # INVARIANT (no needless decryption): every refusal below and every cache
        # hit returns without invoking it, so a gated-off provider, an OAuth
        # profile, an unauthenticated profile, and a warm cache all cost zero
        # credential reads. This is the per-request half of the rule that forbids
        # decrypting every tenant credential at startup.
        """
        provider = plugin.custom_llm_provider
        name = target.profile_name

        refusal = self._refusal_reason(plugin, target)
        if refusal is not None:
            return ProfileModelSnapshot(provider, name, "fallback", None, refusal)
        source = plugin.model_discovery_source()
        if source is None:  # pragma: no cover - _refusal_reason already checked it
            return ProfileModelSnapshot(provider, name, "fallback", None, "discovery_disabled")

        key: ProfileCacheKey = (
            account_id,
            provider,
            name,
            target.credential_revision,
        )
        # What we could answer with no refresh at all: a fresh snapshot, or a damped
        # verdict while a recent failure suppresses retries. ``stale`` rides along —
        # it is the fall-back payload for every remaining branch.
        offline, stale = self._store.offline_answer(key, source=source)
        if offline is not None:
            return offline

        task = self._refreshes.start_or_join(
            key,
            lambda: self._refresh(
                plugin,
                key=key,
                client=client,
                limits=limits,
                auth_provider=auth_provider,
            ),
        )
        if task is None:
            # Closed, or at capacity for a NEW identity. Degrading this one caller to
            # stale-or-seeds is already the documented answer for a slow refresh;
            # queueing would grow a backlog under exactly the load that caused it.
            return self._store.degraded(key, stale=stale, reason="refresh_deferred")

        if stale is not None:
            # Stale-while-revalidate: we already hold an answer worth showing, so
            # spending the user's budget to maybe upgrade it is the worse trade. The
            # refresh started above keeps running behind this response.
            return self._store.degraded(key, stale=stale, reason=None)

        budget = self.wait_budget_s if wait_budget_s is None else wait_budget_s
        if budget <= 0:
            # START-ONLY (OME-1026 F6). A caller with no budget must not OBSERVE the
            # outcome at all.
            # INVARIANT (deterministic semantics): the previous code still gave the task
            # its first step, so a refresh that failed IMMEDIATELY was re-raised while
            # the same bug one loop pass later was not — a timing-dependent 5xx on the
            # credential-publication path, after the credential had already committed.
            # The failure is not lost: it is retained by the manager's error channel for
            # ``assert_no_unexpected``.
            # WHY the yield: it lets the refresh actually BEGIN before this coroutine
            # returns, which is the whole point of warming a listing post-commit.
            await asyncio.sleep(0)
            return ProfileModelSnapshot(provider, name, "refreshing", None, None)
        finished = await self._refreshes.wait_up_to(task, timeout=budget)
        if not finished:
            return ProfileModelSnapshot(provider, name, "refreshing", None, None)

        # ``_terminal_reason`` re-raises anything that is not a discovery failure, so
        # a programming error cannot arrive here disguised as a fallback.
        # WHY ``source`` goes in (adversarial B5): a FAILED attempt leaves the previous
        # snapshot untouched, so the store must date those rows rather than assume this
        # attempt wrote them.
        return self._store.settled_answer(key, source=source, reason=self._terminal_reason(task))

    def invalidate(self, *, account_id: str, provider: str, profile_name: str) -> None:
        """Retire one profile's private catalog: drop its snapshots, supersede its refresh.

        Called after a credential is stored or replaced, after ownership changes, and
        after the profile is deleted — always POST-COMMIT, so the cache reflects a
        durable fact rather than an intention that may still roll back.

        # INVARIANT (a superseded refresh cannot publish over the new owner): the
        # in-flight task is cancelled AND its identity carries the old
        # ``credential_revision``, so even a task that stored a snapshot between the
        # cancel request and its next suspension point wrote under a key no later
        # caller reads.
        """
        identity: ProfileIdentity = (account_id, provider, profile_name)
        self._store.drop(identity)
        for key in self._refreshes.tracked_keys():
            if key[:3] == identity:
                self._refreshes.cancel(key)

    async def drain(self) -> None:
        """Await every in-flight refresh without cancelling any.

        A deterministic observation point: after this returns, background work
        started by earlier requests has landed in the store.
        """
        await self._refreshes.drain()

    async def aclose(self) -> None:
        """Cancel and await in-flight refreshes, then forget every snapshot."""
        await self._refreshes.aclose()
        self._store.clear()

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _refusal_reason(
        plugin: PrivateModelListingProvider, target: DiscoveryCredentialTarget
    ) -> str | None:
        """Why this credential gets no private discovery at all — decided before any I/O.

        # AIDEV-NOTE (why the scope default is fail-CLOSED here while
        # ``ModelCatalog._scope_of`` defaults to public): the hazards are mirror
        # images. There, a provider that declares no scope has no private path to
        # leak, so public is safe. Here, such a provider never asked for a
        # credentialed dial, so refusing is safe. Each default denies its own hazard.
        """
        scope = plugin.model_discovery_scope()
        if scope is DiscoveryScope.NONE:
            return "discovery_disabled"
        if scope is not DiscoveryScope.PROFILE_CREDENTIAL:
            return "not_profile_scoped"
        if plugin.model_discovery_source() is None:
            return "discovery_disabled"
        if not target.authenticated:
            # A PENDING or ERROR credential is not worth spending a request on.
            return "profile_not_authenticated"
        return plugin.profile_discovery_unsupported_reason(auth_type=target.auth_type)

    async def _refresh(
        self,
        plugin: PrivateModelListingProvider,
        *,
        key: ProfileCacheKey,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None,
        auth_provider: Callable[[], Awaitable[ProviderAuthContext]],
    ) -> None:
        """One credentialed attempt: read the credential, dial, publish or record failure.

        # INVARIANT: this coroutine RETURNS nothing. Its whole effect is on the
        # store, so a caller that joined an in-flight refresh reads its own answer
        # back under its OWN identity — a task started for a superseded credential
        # can therefore never hand its result to the new owner.
        """
        provider = key[1]
        try:
            # WHY the revision is overwritten here: the store is KEYED by this token.
            # If a route or a credential strategy could pass a different value, the
            # token the provider sees would no longer identify the snapshot the store
            # holds under it. One source of truth, enforced rather than conventional.
            auth = replace(await auth_provider(), credential_revision=key[3])
            if not auth.headers:
                # Fail closed: a profile whose credential vanished must not produce
                # an unauthenticated dial that a provider might answer generically.
                raise DiscoveryError("missing_credential")
            entries = await plugin.discover_profile_models(client=client, limits=limits, auth=auth)
        except AssertionError:
            # INVARIANT: the test suite's no-egress tripwire raises AssertionError.
            # Absorbing it would turn a forbidden real dial into a quiet "fallback",
            # and a test that actually reached the internet would pass green.
            raise
        except (CredentialNotFoundError, AuthError):
            # A concurrent delete or a rotated-away credential. Expected, not a bug:
            # recorded as a normal failed attempt so retries are damped too.
            sanitized = DiscoveryError("missing_credential")
            self._store.record_failure(key, sanitized)
            raise sanitized from None
        except DiscoveryError as error:
            self._store.record_failure(key, error)
            raise
        except Exception as error:
            # Sanitized: the TYPE names the bug class for operators; the message may
            # carry upstream content and is dropped. No account id and no profile name
            # — the latter is user-supplied text in a log line. The original error stays
            # loud so an awaited caller or the bounded background sink observes the bug.
            logger.warning(
                "private model listing refresh failed unexpectedly provider=%s type=%s",
                provider,
                type(error).__name__,
            )
            raise
        if entries is None:
            # A None under a DECLARED source is an inconsistency, not an empty
            # catalog: caching it as success would evict the last good listing.
            missing_snapshot = DiscoveryError("no_snapshot")
            self._store.record_failure(key, missing_snapshot)
            raise missing_snapshot
        self._store.store(key, entries)
        logger.info("private model listing refreshed provider=%s models=%d", provider, len(entries))

    @staticmethod
    def _terminal_reason(task: asyncio.Task[Any]) -> str | None:
        """The sanitized reason a FINISHED refresh produced, or ``None`` on success.

        # INVARIANT (loud on bugs): a ``DiscoveryError`` is a normal failed attempt.
        # Anything else is a programming error and is re-raised to the caller rather
        # than folded into "fallback".
        """
        if task.cancelled():
            # The credential was replaced (or the profile deleted) while this ran.
            return "refresh_superseded"
        exc = task.exception()
        if exc is None:
            return None
        if isinstance(exc, DiscoveryError):
            return exc.reason
        # This bug is about to reach a caller, so the background retention sink must not
        # ALSO hold it — otherwise test teardown would fail for an error the test
        # deliberately asserted (OME-1026 F6).
        mark_observed(exc)
        raise exc


def build_profile_model_catalog(*, settings: Settings) -> ProfileModelCatalog | None:
    """The app-lifetime private catalog, or ``None`` under the discovery kill switch.

    INVARIANT: ``AIGW_DISCOVERY_ENABLED=false`` silences ALL discovery egress — the
    private catalog obeys the same switch as the public one and the parameter
    runtime, so one flag audits to zero discovery traffic.

    # WHY these bounds are reused rather than newly invented (owner brief: do not
    # invent an arbitrary limit):
    #   * ``AIGW_DISCOVERY_CACHE_MAX_ENTRIES`` (512) already bounds discovery cache
    #     records; snapshots are records of the same kind, one per identity.
    #   * the in-flight task map is bounded by the SAME number because a task and a
    #     snapshot are both per-identity; real upstream concurrency is bounded by
    #     request concurrency, not by this map.
    #   * ``AIGW_DISCOVERY_TIMEOUT_SECONDS`` is how long ONE discovery dial may take,
    #     CLAMPED by ``user_wait_budget`` to the 3-second product promise (F2). The
    #     raw setting could not serve as the wait: it accepts any positive value, so an
    #     operator raising it for a slow provider would raise every user's wait with it.
    # The one bound that could NOT be reused is the memory budget
    # (``AIGW_DISCOVERY_PROFILE_CACHE_MAX_ROWS``, F7): nothing existing expresses
    # "total rows retained", because no other cache holds an unbounded payload per
    # record. Its default is stated and justified in ``profile_snapshot_store``.
    # AIDEV-NOTE: what is NOT decided here is per-account FAIRNESS — one busy tenant
    # can evict another's snapshot from the shared 512 and can occupy in-flight
    # slots. That is a product decision (per-account quotas), deliberately reported
    # rather than invented.
    """
    if not settings.discovery_enabled:
        return None
    return ProfileModelCatalog(
        max_identities=settings.discovery_cache_max_entries,
        max_inflight_refreshes=settings.discovery_cache_max_entries,
        wait_budget_s=user_wait_budget(settings.discovery_timeout_seconds),
        max_rows=settings.discovery_profile_cache_max_rows,
    )
