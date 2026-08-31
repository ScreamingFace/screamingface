"""OME-1026 — bounded per-profile snapshot memory and its freshness policy.

FEATURE: the memory half of profile-scoped live model discovery. This module owns
WHAT may be served for one private identity and for how long; the orchestration
half — gates, credentialed refresh, supersede — lives in
:mod:`aigateway.core.profile_model_catalog`.

INVARIANT (the load-bearing one): the identity is the TUPLE
``(account_id, provider, profile_name, credential_revision)``. Nothing keyed that
way can be read by another account, and a snapshot gathered under a previous
credential generation cannot be served under the new one.

INVARIANT (no secret in an identity): ``credential_revision`` is derived from
profile OWNERSHIP metadata (auth type + the durable ownership GENERATION the
profile index bumps inside its publication CAS), never from the credential and
never from a wall-clock stamp — see :func:`profile_credential_revision`.
Identities are compared, logged, and held for the process lifetime; a
key-derived value — even a hash — would put credential-dependent data in all
three places.

WHY this is not ``ObservationCache`` (the OME-479 public cache): that one awaits
its refresh callable while HOLDING the single-flight lock, and serves a stale
value only when a refresh actually FAILED — never pre-emptively. Both rules are
right for capability evidence and wrong here: this path must answer within a
small user-facing budget while the refresh keeps running, which needs the wait
and the work to be separable. Bending the shared cache's documented semantics to
fit would change behaviour for parameter discovery too.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .parameter_discovery import DiscoveryError
from .parameter_discovery_cache import MonotonicClock, SystemMonotonicClock

if TYPE_CHECKING:
    from .plugin_base import ModelDiscoverySource, ModelEntry
    from .profile_models import Profile

# fresh: a live snapshot within its TTL.
# stale: a last-good snapshot past TTL, served while a refresh runs behind it.
# refreshing: no snapshot yet; a refresh is in flight and outlasted our wait.
# fallback: no snapshot to serve — the caller lists the provider's compiled seeds.
ProfileSnapshotStatus = Literal["fresh", "stale", "refreshing", "fallback"]

# A TUPLE, never a joined string: a profile name is user-supplied, so a separator
# inside it could otherwise alias a sibling identity, and "invalidate this
# profile" would become prefix matching instead of field equality.
ProfileIdentity = tuple[str, str, str]  # account_id, provider, profile_name
ProfileCacheKey = tuple[str, str, str, str]  # + credential_revision

UNKNOWN_REASON = "unavailable"

# The reason recorded when a snapshot is refused for exceeding the whole row budget.
# Part of the closed reason vocabulary: sanitized, stable, and never upstream text.
# WHY not the existing ``model_catalog_too_large``: that one is the PROVIDER refusing
# its own walk (upstream holds more models than the provider's declared cap), and an
# operator fixes it by raising that cap or investigating upstream. This one is THIS
# WORKER's retention budget being smaller than the catalog, fixed by raising
# ``AIGW_DISCOVERY_PROFILE_CACHE_MAX_ROWS``. Two different actions need two codes.
CACHE_BUDGET_REASON = "cache_row_budget_exceeded"

# WHY 16384 rows (OME-1026 F7 — an owner-approved number, not a derived one): it holds
# eight maximum-size provider catalogs (Anthropic caps its own walk at 2,000 models) or
# several hundred ordinary ones, while the previous identity-only bound admitted
# 512 x 2,000 = over a million rows per worker. Operators size it with
# AIGW_DISCOVERY_PROFILE_CACHE_MAX_ROWS.
# INVARIANT (a ROW-COUNT bound, deliberately not a byte bound): this counts retained
# ``ModelEntry`` objects. No per-row byte figure is claimed anywhere, because none has
# been measured — a ``litellm_params`` dict is provider-shaped and an unmeasured
# multiplication would read as a memory guarantee the code does not make.
_DEFAULT_MAX_ROWS = 16_384


def profile_credential_revision(profile: Profile, credential_generation: int) -> str:
    """A NON-SECRET generation token for the credential behind ``profile``.

    ``credential_generation`` is the durable, strictly-advancing counter the profile
    index bumps INSIDE the atomic CAS that publishes a credential
    (``ProfileIndex.credential_generations``), so it changes exactly once per
    credential owner change and is unique across workers and restarts.

    # INVARIANT: derived from ownership metadata ONLY (see the module docstring) —
    # never from key material, and (OME-1026 F3) no longer from the wall clock.
    # WHY NOT ``last_refreshed_at``, which this replaced: it is assigned
    # ``datetime.now(UTC)`` at publication, so two replacements inside one clock tick
    # produced EQUAL identities and the first key's snapshot was served as fresh under
    # the second. Process-local invalidation hid that on the rotating worker and could
    # not help any other worker at all.
    # WHY it belongs in the identity rather than being handled by eviction hooks
    # alone: even if every invalidation call site were forgotten, a snapshot
    # gathered under the previous credential can never be SERVED under the new one.
    # ``auth_type`` is kept as free defence in depth: a switch bumps the generation
    # too, but a mismatched pair can never alias.
    """
    return f"{profile.auth_type}@gen{credential_generation}"


@dataclass(frozen=True)
class ProfileModelSnapshot:
    """What one profile's private catalog can show right now.

    ``entries`` is ``None`` whenever there is no live listing to serve; the caller
    then lists the provider's compiled ``register_models()`` seeds, exactly as
    ``GET /v1/models`` does for a degraded public provider.

    # AIDEV-NOTE: listing is not dispatch readiness. A model appearing here says
    # the profile's credential can SEE it, not that the gateway will route to it.
    """

    provider: str
    profile_name: str
    status: ProfileSnapshotStatus
    entries: tuple[ModelEntry, ...] | None = None
    # Sanitized, closed vocabulary (a DiscoveryError reason or a refusal code) —
    # never upstream text. Set on fallback, and on stale to say why the list is
    # not advancing.
    reason: str | None = None


@dataclass
class _Record:
    """One identity's memory: the last good snapshot AND the last failure.

    # WHY both in one record: a failure must be able to DAMP retries without
    # discarding the snapshot it may still serve as stale.
    """

    entries: tuple[ModelEntry, ...] | None = None
    stored_at: float = 0.0
    failed_at: float | None = None
    reason: str | None = None


class ProfileSnapshotStore:
    """A bounded LRU of private listings, plus the policy for serving them.

    Two INDEPENDENT bounds, because neither implies the other:

    * ``max_identities`` — how many private listings may be remembered at once.
    * ``max_rows`` — how many ``ModelEntry`` rows may be retained in TOTAL.

    INVARIANT (F7): retained rows stay within ``max_rows``. NO carve-out, for any
    snapshot, ever — a listing larger than the whole budget is REFUSED by
    :meth:`store` rather than admitted, because a configured maximum that a single
    snapshot may exceed is not a maximum. That refusal is recorded as a sanitized
    failure so the provider's failure TTL damps the retry, which is what keeps the
    memory bound from becoming an egress amplifier.

    INVARIANT (adversarial B5): freshness is decided by TTL arithmetic on
    ``stored_at``, in :meth:`offline_answer` and :meth:`settled_answer` alike. "This
    identity has entries" is never a freshness test — see :meth:`settled_answer`.

    # AIDEV-NOTE: what these bounds still do NOT decide is per-account FAIRNESS. One
    # busy tenant can evict another's snapshot from the shared budget. That is a
    # product decision (per-account quotas), deliberately reported, not invented.
    """

    def __init__(
        self,
        *,
        clock: MonotonicClock | None = None,
        max_identities: int,
        max_rows: int = _DEFAULT_MAX_ROWS,
    ) -> None:
        if max_identities <= 0:
            raise ValueError("max_identities must be positive")
        if max_rows <= 0:
            raise ValueError("max_rows must be positive")
        self.clock: MonotonicClock = clock if clock is not None else SystemMonotonicClock()
        self._max_identities = max_identities
        self._max_rows = max_rows
        # OrderedDict doubles as the LRU: touched keys move to the end, eviction
        # pops from the front.
        # WHY NOT identities alone, as this bounded before: an identity's CONTENTS are
        # unbounded from core's point of view — the provider caps its own walk, and
        # Anthropic's cap is 2,000 models. 512 identities x 2,000 rows is over a
        # million retained entries per worker, so an identity count bounded the number
        # of tenants remembered and said nothing about memory. The earlier comment here
        # claimed the opposite; it was wrong, and the row budget replaces it.
        self._records: OrderedDict[ProfileCacheKey, _Record] = OrderedDict()

    @property
    def max_rows(self) -> int:
        """The hard ceiling on :attr:`retained_rows`. Never exceeded, ever."""
        return self._max_rows

    @property
    def tracked_identities(self) -> int:
        return len(self._records)

    @property
    def retained_rows(self) -> int:
        """Total ``ModelEntry`` rows held across every identity.

        # WHY recomputed instead of maintained incrementally: every mutation path
        # (store, replace, failure, drop, clear, eviction) would have to adjust a
        # running counter correctly, and one missed path makes the bound silently
        # wrong in the direction of unbounded growth. The dict is bounded by
        # ``max_identities``, so this sum is cheap and cannot drift.
        """
        return sum(len(record.entries) for record in self._records.values() if record.entries)

    def offline_answer(
        self,
        key: ProfileCacheKey,
        *,
        source: ModelDiscoverySource,
    ) -> tuple[ProfileModelSnapshot | None, tuple[ModelEntry, ...] | None]:
        """``(answer_needing_no_refresh, stale_payload)`` for this identity.

        A non-``None`` first element means the caller must NOT start a refresh:
        either the snapshot is fresh, or a recent failure is damping retries. The
        second element is the last-good listing while it remains inside the stale
        window — the payload every degraded branch downstream falls back to.
        """
        provider, name = key[1], key[2]
        record = self._lookup(key)
        now = self.clock.now()
        stale: tuple[ModelEntry, ...] | None = None
        if record is not None and record.entries is not None:
            age = now - record.stored_at
            if age <= source.ttl_s:
                return ProfileModelSnapshot(provider, name, "fresh", record.entries, None), None
            if age <= source.ttl_s + source.stale_ttl_s:
                stale = record.entries
        if self._damped(record, source, now):
            reason = (record.reason if record is not None else None) or UNKNOWN_REASON
            return self.degraded(key, stale=stale, reason=reason), stale
        return None, stale

    def settled_answer(
        self,
        key: ProfileCacheKey,
        *,
        source: ModelDiscoverySource,
        reason: str | None,
    ) -> ProfileModelSnapshot:
        """The answer after a refresh we waited for has finished.

        ``reason`` is the finished attempt's sanitized failure code, if any. An
        ACCEPTED attempt just stamped ``stored_at``, so the TTL check below labels it
        ``fresh`` — and a FAILED one is classified against the clock like any ordinary
        read: inside the stale window it is served as ``stale`` carrying why the list
        is not advancing, beyond it not served at all.

        # INVARIANT (adversarial B5): this uses the SAME arithmetic as
        # ``offline_answer`` and never infers freshness from ``entries is not None``.
        # WHY that inference was wrong: ``store`` deliberately LEAVES the previous
        # snapshot in place when it refuses an oversized replacement (stale beats
        # seeds), and ``record_failure`` never touches ``entries`` at all. So after a
        # failed attempt the rows present are the PREVIOUS ones, of any age whatever.
        # An independent probe was served entries older than ``ttl + stale_ttl``
        # labelled ``fresh`` with no reason — the strongest trust label this API has,
        # on the one answer that had earned the weakest.
        """
        record = self._lookup(key)
        if record is None or record.entries is None:
            return self.degraded(key, stale=None, reason=reason or UNKNOWN_REASON)
        age = self.clock.now() - record.stored_at
        if age <= source.ttl_s:
            return ProfileModelSnapshot(key[1], key[2], "fresh", record.entries, None)
        stale = record.entries if age <= source.ttl_s + source.stale_ttl_s else None
        return self.degraded(key, stale=stale, reason=reason or UNKNOWN_REASON)

    def degraded(
        self,
        key: ProfileCacheKey,
        *,
        stale: tuple[ModelEntry, ...] | None,
        reason: str | None,
    ) -> ProfileModelSnapshot:
        """Serve the last-good listing if we still have one, else defer to seeds.

        # WHY stale beats seeds: the seeds are a compiled guess about the provider,
        # while a stale snapshot is what this profile's own credential actually
        # returned. Both carry the reason, so the caller can say why it is not moving.
        """
        record = self._records.get(key)
        if stale is not None:
            return ProfileModelSnapshot(
                key[1], key[2], "stale", stale, (record.reason if record else None) or reason
            )
        return ProfileModelSnapshot(key[1], key[2], "fallback", None, reason or UNKNOWN_REASON)

    def store(self, key: ProfileCacheKey, entries: tuple[ModelEntry, ...]) -> None:
        """Cache one identity's snapshot, or REFUSE it for exceeding the row budget.

        INVARIANT (OME-1026 F7): :attr:`retained_rows` never exceeds :attr:`max_rows`,
        with no carve-out. A snapshot larger than the entire budget is not cached at
        all — caching it would breach the bound by construction, and exempting it
        (as an earlier revision did) meant the configured maximum was not a maximum.

        Raises ``DiscoveryError(CACHE_BUDGET_REASON)`` in that case, having first recorded
        a sanitized failure so the provider's own failure TTL damps the retry. Without
        the damping an oversized catalog would re-dial upstream with the caller's
        credential on every single request — a memory bound turned into an egress
        amplifier. The caller's existing degraded path then answers with this same
        profile's stale snapshot when it still has one, and the provider's compiled
        seeds otherwise.

        # WHY refusing beats truncating: a partial catalog is indistinguishable from a
        # complete one to every consumer, so a silently trimmed listing would publish
        # ids as "the models this credential can call" while omitting some. A refusal
        # is visible, damped, and leaves the last good answer in place.
        """
        record = self._record_for(key)
        if len(entries) > self._max_rows:
            error = DiscoveryError(CACHE_BUDGET_REASON)
            record.failed_at = self.clock.now()
            record.reason = error.reason
            # The previous snapshot, if any, is deliberately LEFT in place: it is this
            # same identity's last good answer and stale beats seeds.
            self._trim()
            raise error
        record.entries = entries
        record.stored_at = self.clock.now()
        record.failed_at = None
        record.reason = None
        self._trim()

    def record_failure(self, key: ProfileCacheKey, error: DiscoveryError) -> None:
        record = self._record_for(key)
        record.failed_at = self.clock.now()
        record.reason = error.reason
        self._trim()

    def drop(self, identity: ProfileIdentity) -> None:
        """Forget every credential generation of one profile's listing."""
        for key in [key for key in self._records if key[:3] == identity]:
            del self._records[key]

    def clear(self) -> None:
        self._records.clear()

    @staticmethod
    def _damped(record: _Record | None, source: ModelDiscoverySource, now: float) -> bool:
        """Whether a recent failure should suppress another dial.

        # FEATURE: a revoked key must not cost one upstream 401 per page load. The
        # window comes from the provider's own declared source policy, so a provider
        # that tolerates eager retries can set it to zero.
        """
        if record is None or record.failed_at is None or source.failure_ttl_s <= 0:
            return False
        return (now - record.failed_at) <= source.failure_ttl_s

    def _lookup(self, key: ProfileCacheKey) -> _Record | None:
        record = self._records.get(key)
        if record is not None:
            self._records.move_to_end(key)
        return record

    def _record_for(self, key: ProfileCacheKey) -> _Record:
        record = self._records.get(key)
        if record is None:
            record = _Record()
            self._records[key] = record
        self._records.move_to_end(key)
        return record

    def _trim(self) -> None:
        # WHY evicting a SNAPSHOT is safe while evicting a TASK is not: dropping a
        # snapshot costs one later re-dial, whereas dropping a task would abandon
        # work a caller is awaiting.
        while len(self._records) > self._max_identities:
            self._records.popitem(last=False)
        # The row budget, applied after the identity bound. NO carve-out (OME-1026 F7):
        # the configured maximum is a hard maximum.
        # WHY the record just written still cannot be evicted for its own size: eviction
        # pops from the FRONT and ``store`` moved that record to the END, so it is the
        # last candidate — and by the time it were reached the total would be its own
        # length, which ``store`` has already refused to let exceed the budget. The
        # oversized refusal is what makes the old ``len > 1`` guard unnecessary rather
        # than merely unwanted.
        while self._records and self.retained_rows > self._max_rows:
            self._records.popitem(last=False)
