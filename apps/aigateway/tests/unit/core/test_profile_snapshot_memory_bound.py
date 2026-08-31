"""OME-1026 remediation F7 — the private snapshot cache needs a MEMORY bound.

FEATURE: bounded private discovery memory. The private catalog is filled by
authenticated requests, so what it retains has to be bounded by something an
operator can size — not by a count of identities whose contents are unbounded.

STORY: as an operator I can predict this cache's footprint from configuration,
regardless of how large any single provider's catalog turns out to be.

INVARIANT (why the identity bound was not enough): the store held 512 identities and
Anthropic permits up to 2,000 models per snapshot, so the honest worst case was over
one million retained ``ModelEntry`` objects PER WORKER. The old comment claiming
identity-based bounding kept one oversized catalog from crowding other tenants was
exactly backwards: an identity bound lets ONE tenant's 2,000-row catalog occupy the
same slot weight as forty ordinary ones.

INVARIANT (the guarantee this file pins): retained rows NEVER exceed the configured
row budget. There is no carve-out — owner decision, OME-1026 final pass F7. An earlier
revision exempted the most recently stored snapshot so that a catalog bigger than the
whole budget could still be cached; that made the configured maximum not a maximum. A
snapshot larger than the budget is now refused, with a sanitized damped failure so the
refusal does not become an egress amplifier, and the identity keeps its last good
snapshot instead.

AIDEV-NOTE: the two carve-out cases below were re-pinned to this contract in the
OME-1026 final pass. They are the ONLY prior tests this file changed, and the change
was directed by the owner rather than chosen to make new code pass.
"""

from __future__ import annotations

import pytest

from aigateway.core.parameter_discovery import DiscoveryError
from aigateway.core.plugin_base import ModelDiscoverySource, ModelEntry
from aigateway.core.profile_snapshot_store import CACHE_BUDGET_REASON, ProfileSnapshotStore

_SOURCE = ModelDiscoverySource(
    key="fake:models:list",
    revision="fake-v1",
    ttl_s=300.0,
    stale_ttl_s=3600.0,
    failure_ttl_s=30.0,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def now(self) -> float:
        return self.value


def _rows(count: int) -> tuple[ModelEntry, ...]:
    return tuple(
        ModelEntry(model_name=f"model-{index}", litellm_params={"model": f"fake/model-{index}"})
        for index in range(count)
    )


def _key(index: int) -> tuple[str, str, str, str]:
    return (f"acct-{index}", "fake", "work", "api_key@gen1")


# ── the total weight, not the identity count ──────────────────────────────────


def test_the_store_reports_its_retained_row_weight() -> None:
    """Observability first: a bound nobody can read is a bound nobody can operate."""
    store = ProfileSnapshotStore(clock=_Clock(), max_identities=8, max_rows=1_000)

    assert store.retained_rows == 0
    store.store(_key(0), _rows(7))
    assert store.retained_rows == 7
    store.store(_key(1), _rows(3))
    assert store.retained_rows == 10


def test_row_weight_is_bounded_even_when_the_identity_count_is_not() -> None:
    """The reported case: identities well under their limit, rows far over.

    Ten identities against a limit of 64 — the identity bound never fires — each
    holding 100 rows against a 250-row budget.
    """
    store = ProfileSnapshotStore(clock=_Clock(), max_identities=64, max_rows=250)

    for index in range(10):
        store.store(_key(index), _rows(100))

    assert store.tracked_identities < 10, "the row budget must have evicted something"
    assert store.retained_rows <= 250, store.retained_rows


def test_eviction_for_weight_is_least_recently_used() -> None:
    """Which snapshot is dropped still follows the LRU order, not insertion order."""
    store = ProfileSnapshotStore(clock=_Clock(), max_identities=64, max_rows=250)
    store.store(_key(0), _rows(100))
    store.store(_key(1), _rows(100))

    # Touch identity 0, making identity 1 the least recently used.
    fresh, _stale = store.offline_answer(_key(0), source=_SOURCE)
    assert fresh is not None and fresh.status == "fresh"

    store.store(_key(2), _rows(100))

    assert store.offline_answer(_key(0), source=_SOURCE)[0] is not None, "the touched one stays"
    assert store.offline_answer(_key(1), source=_SOURCE) == (None, None), "the LRU one goes"


def test_replacing_one_identitys_snapshot_does_not_double_count_it() -> None:
    """A refresh REPLACES rows. Counting them twice would evict for phantom weight."""
    store = ProfileSnapshotStore(clock=_Clock(), max_identities=64, max_rows=250)

    for _ in range(20):
        store.store(_key(0), _rows(100))

    assert store.retained_rows == 100, store.retained_rows
    assert store.tracked_identities == 1


def test_a_single_snapshot_larger_than_the_whole_budget_is_refused() -> None:
    """Re-pinned (owner decision, F7): the maximum is a maximum.

    # WHY refusing beats exempting: caching a snapshot bigger than the budget breaches
    # the bound by construction, so the exemption meant an operator could not predict
    # the footprint from configuration at all — one oversized catalog defeated the
    # number they set. It also beats TRUNCATING, which would publish a partial listing
    # indistinguishable from a complete one.
    """
    store = ProfileSnapshotStore(clock=_Clock(), max_identities=64, max_rows=10)

    with pytest.raises(DiscoveryError) as caught:
        store.store(_key(0), _rows(500))

    assert caught.value.reason == CACHE_BUDGET_REASON
    assert store.retained_rows <= store.max_rows
    assert store.retained_rows == 0, store.retained_rows
    answer, stale = store.offline_answer(_key(0), source=_SOURCE)
    assert stale is None, "nothing was retained, so there is nothing stale to serve"
    assert answer is not None and answer.entries is None, answer
    assert answer.status == "fallback" and answer.reason == CACHE_BUDGET_REASON, answer


def test_a_refused_oversized_snapshot_is_damped_not_redialed() -> None:
    """The refusal must not become an egress amplifier.

    # WHY this replaces the old "the carve-out lasts one snapshot" case: with no
    # carve-out the danger moves from memory to egress — an identity that can never
    # cache would re-dial the provider with the caller's credential on every request.
    # The recorded failure makes the provider's own failure TTL suppress that.
    """
    clock = _Clock()
    store = ProfileSnapshotStore(clock=clock, max_identities=64, max_rows=10)

    with pytest.raises(DiscoveryError):
        store.store(_key(0), _rows(500))

    # A non-None first element is precisely "the caller must NOT start a refresh".
    answer, _stale = store.offline_answer(_key(0), source=_SOURCE)
    assert answer is not None, "an oversized catalog must not be re-dialed every request"
    assert answer.status == "fallback" and answer.reason == CACHE_BUDGET_REASON, answer

    # ...and once the provider's own failure window passes, the identity may try again.
    clock.value += _SOURCE.failure_ttl_s + 1.0
    after, _ = store.offline_answer(_key(0), source=_SOURCE)
    assert after is None, "the damping window is the PROVIDER's, not a permanent refusal"
    store.store(_key(0), _rows(4))
    assert store.retained_rows == 4


def test_an_oversized_replacement_leaves_the_last_good_snapshot_in_place() -> None:
    """Stale beats seeds: a refusal must not destroy what the identity already had."""
    store = ProfileSnapshotStore(clock=_Clock(), max_identities=64, max_rows=10)
    store.store(_key(0), _rows(6))

    with pytest.raises(DiscoveryError):
        store.store(_key(0), _rows(500))

    assert store.retained_rows == 6, "the previous snapshot survives the refusal"
    assert store.retained_rows <= store.max_rows


def test_cumulative_stores_never_exceed_the_row_budget() -> None:
    """The bound holds across MANY identities, not just one oversized store."""
    store = ProfileSnapshotStore(clock=_Clock(), max_identities=512, max_rows=50)

    for index in range(40):
        store.store(_key(index), _rows(9))
        assert store.retained_rows <= store.max_rows, (index, store.retained_rows)

    assert store.retained_rows <= 50


def test_a_failure_record_carries_no_row_weight() -> None:
    """A damping record is a timestamp and a reason — it must not evict a snapshot."""
    from aigateway.core.parameter_discovery import DiscoveryError

    store = ProfileSnapshotStore(clock=_Clock(), max_identities=64, max_rows=250)
    store.store(_key(0), _rows(200))

    for index in range(1, 40):
        store.record_failure(_key(index), DiscoveryError("bad_status", status=401))

    assert store.retained_rows == 200, store.retained_rows
    assert store.offline_answer(_key(0), source=_SOURCE)[0] is not None, "the snapshot survived"


def test_dropping_and_clearing_both_release_the_weight() -> None:
    store = ProfileSnapshotStore(clock=_Clock(), max_identities=64, max_rows=1_000)
    store.store(("acct-a", "fake", "work", "api_key@gen1"), _rows(50))
    store.store(("acct-a", "fake", "work", "api_key@gen2"), _rows(50))
    store.store(("acct-b", "fake", "work", "api_key@gen1"), _rows(50))

    store.drop(("acct-a", "fake", "work"))

    # Both generations of that one profile go, and only those.
    assert store.retained_rows == 50, store.retained_rows
    store.clear()
    assert store.retained_rows == 0


def test_the_identity_bound_still_applies_under_a_generous_row_budget() -> None:
    """The two bounds are independent: neither replaces the other."""
    store = ProfileSnapshotStore(clock=_Clock(), max_identities=3, max_rows=1_000_000)

    for index in range(10):
        store.store(_key(index), _rows(1))

    assert store.tracked_identities == 3
    assert store.retained_rows == 3
