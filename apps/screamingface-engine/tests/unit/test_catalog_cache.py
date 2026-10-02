from __future__ import annotations

import asyncio

import pytest

from screamingface_engine.catalog.cache import CachedCatalog
from screamingface_engine.catalog.port import (
    CatalogBadResponse,
    CatalogError,
    CatalogUnavailable,
    Credential,
    ModelCatalog,
    compute_etag,
)

pytestmark = pytest.mark.asyncio


def _credential(name: str) -> Credential:
    return Credential.derive({"X-User-Email": f"{name}@example.com"})


CRED_A = _credential("caller-a")
CRED_B = _credential("caller-b")


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSource:
    def __init__(self, *, delay: float = 0.0, fail: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.fail = fail
        self._delay = delay
        self._live = 0
        self.max_concurrent = 0

    async def fetch(self, credential: Credential) -> ModelCatalog:
        self.calls.append(credential.key)
        self._live += 1
        self.max_concurrent = max(self.max_concurrent, self._live)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            if self.fail is not None:
                raise self.fail
            body: dict[str, object] = {"object": "list", "data": [{"id": credential.key}]}
            return ModelCatalog(body=body, etag=compute_etag(body))
        finally:
            self._live -= 1


class ExplodingSource:
    async def fetch(self, credential: Credential) -> ModelCatalog:
        raise AssertionError("upstream must not be called on this path")


def build(source: object, clock: FakeClock, **kwargs: object) -> CachedCatalog:
    defaults: dict[str, object] = {
        "ttl_s": 300.0,
        "stale_max_s": 3600.0,
        "error_backoff_s": 30.0,
        "max_entries": 256,
        "upstream_concurrency": 8,
        "clock": clock,
    }
    defaults.update(kwargs)
    return CachedCatalog(source, **defaults)  # type: ignore[arg-type]


async def test_cold_miss_fetches_once_and_returns_the_catalog() -> None:
    source = FakeSource()
    cache = build(source, FakeClock())
    catalog = await cache.fetch(CRED_A)
    assert catalog.body["data"] == [{"id": CRED_A.key}]
    assert source.calls == [CRED_A.key]


async def test_hit_inside_the_ttl_performs_no_upstream_call() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock)
    first = await cache.fetch(CRED_A)
    clock.advance(299.0)
    second = await cache.fetch(CRED_A)
    assert source.calls == [CRED_A.key]
    assert second is first


async def test_entry_older_than_the_ttl_is_refetched() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock)
    await cache.fetch(CRED_A)
    clock.advance(301.0)
    await cache.fetch(CRED_A)
    assert source.calls == [CRED_A.key, CRED_A.key]


async def test_a_fresh_hit_never_touches_upstream_even_concurrently() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock)
    await cache.fetch(CRED_A)
    cache._source = ExplodingSource()  # type: ignore[attr-defined]
    results = await asyncio.gather(*(cache.fetch(CRED_A) for _ in range(10)))
    assert len({id(item) for item in results}) == 1


async def test_two_credentials_never_observe_each_others_catalog() -> None:
    source = FakeSource()
    cache = build(source, FakeClock())
    first = await cache.fetch(CRED_A)
    second = await cache.fetch(CRED_B)
    assert first.body["data"] == [{"id": CRED_A.key}]
    assert second.body["data"] == [{"id": CRED_B.key}]
    assert sorted(source.calls) == sorted([CRED_A.key, CRED_B.key])


async def test_a_second_credential_does_not_hit_the_first_ones_warm_entry() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock)
    await cache.fetch(CRED_A)
    source.calls.clear()
    await cache.fetch(CRED_B)
    assert source.calls == [CRED_B.key]


async def test_twenty_concurrent_misses_on_one_key_cause_exactly_one_fetch() -> None:
    source = FakeSource(delay=0.02)
    cache = build(source, FakeClock())
    results = await asyncio.gather(*(cache.fetch(CRED_A) for _ in range(20)))
    assert len(source.calls) == 1
    assert all(item.etag == results[0].etag for item in results)


async def test_distinct_keys_are_not_serialised_behind_each_other() -> None:
    source = FakeSource(delay=0.05)
    cache = build(source, FakeClock())
    creds = [_credential(f"caller-{index}") for index in range(5)]
    await asyncio.gather(*(cache.fetch(cred) for cred in creds))
    assert len(source.calls) == 5
    assert source.max_concurrent > 1


async def test_a_failed_refresh_serves_the_previous_entry() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock)
    warm = await cache.fetch(CRED_A)
    clock.advance(301.0)
    source.fail = CatalogUnavailable("upstream down")
    served = await cache.fetch(CRED_A)
    assert served.etag == warm.etag


async def test_stale_service_stops_at_stale_max() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock, stale_max_s=600.0)
    await cache.fetch(CRED_A)
    clock.advance(601.0)
    source.fail = CatalogUnavailable("upstream down")
    with pytest.raises(CatalogUnavailable):
        await cache.fetch(CRED_A)


async def test_concurrent_waiters_receive_the_same_stale_value_as_the_leader() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock)
    warm = await cache.fetch(CRED_A)
    clock.advance(301.0)
    source.fail = CatalogUnavailable("upstream down")
    source._delay = 0.02
    source.calls.clear()
    results = await asyncio.gather(*(cache.fetch(CRED_A) for _ in range(5)))
    assert all(item.etag == warm.etag for item in results)
    assert len(source.calls) == 1, "the failing refresh must be single-flighted too"


async def test_a_cold_failure_raises_and_caches_nothing() -> None:
    source = FakeSource(fail=CatalogBadResponse("garbage"))
    cache = build(source, FakeClock())
    with pytest.raises(CatalogBadResponse):
        await cache.fetch(CRED_A)
    assert cache.entry_count == 0


async def test_concurrent_cold_failures_all_raise_and_cache_nothing() -> None:
    source = FakeSource(delay=0.02, fail=CatalogBadResponse("garbage"))
    cache = build(source, FakeClock())
    results = await asyncio.gather(*(cache.fetch(CRED_A) for _ in range(5)), return_exceptions=True)
    assert all(isinstance(item, CatalogBadResponse) for item in results)
    assert len(source.calls) == 1
    assert cache.entry_count == 0


async def test_a_failed_refresh_on_a_known_key_backs_off_before_retrying() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock, error_backoff_s=30.0)
    await cache.fetch(CRED_A)
    clock.advance(301.0)
    source.fail = CatalogUnavailable("down")
    await cache.fetch(CRED_A)
    assert len(source.calls) == 2
    clock.advance(10.0)
    await cache.fetch(CRED_A)
    assert len(source.calls) == 2, "inside the backoff window upstream must not be consulted"


async def test_the_backoff_window_expires_and_upstream_is_retried() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock, error_backoff_s=30.0)
    await cache.fetch(CRED_A)
    clock.advance(301.0)
    source.fail = CatalogUnavailable("down")
    await cache.fetch(CRED_A)
    clock.advance(31.0)
    await cache.fetch(CRED_A)
    assert len(source.calls) == 3


async def test_recovery_clears_the_failure_state() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock)
    await cache.fetch(CRED_A)
    clock.advance(301.0)
    source.fail = CatalogUnavailable("down")
    await cache.fetch(CRED_A)
    clock.advance(31.0)
    source.fail = None
    fresh = await cache.fetch(CRED_A)
    assert fresh.body["data"] == [{"id": CRED_A.key}]
    clock.advance(301.0)
    source.fail = CatalogUnavailable("down again")
    await cache.fetch(CRED_A)
    assert len(source.calls) == 4, "a recovered key must not still be inside the old backoff"


async def test_the_entry_count_is_capped_and_the_oldest_key_is_evicted() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock, max_entries=3)
    creds = [_credential(f"caller-{index}") for index in range(4)]
    for cred in creds:
        await cache.fetch(cred)
    assert cache.entry_count == 3
    source.calls.clear()
    await cache.fetch(creds[0])
    assert source.calls == [creds[0].key], "the first key should have been evicted"


async def test_reading_a_key_makes_it_recently_used() -> None:
    source = FakeSource()
    clock = FakeClock()
    cache = build(source, clock, max_entries=2)
    first, second, third = (_credential(f"caller-{index}") for index in range(3))
    await cache.fetch(first)
    await cache.fetch(second)
    await cache.fetch(first)
    await cache.fetch(third)
    source.calls.clear()
    await cache.fetch(first)
    assert source.calls == [], "first was recently used and must have survived eviction"


async def test_concurrent_upstream_fetches_never_exceed_the_bulkhead() -> None:
    source = FakeSource(delay=0.02)
    cache = build(source, FakeClock(), upstream_concurrency=2)
    creds = [_credential(f"caller-{index}") for index in range(10)]
    await asyncio.gather(*(cache.fetch(cred) for cred in creds))
    assert len(source.calls) == 10
    assert source.max_concurrent <= 2


async def test_a_saturated_bulkhead_fails_fast_instead_of_queueing_forever() -> None:
    """The bulkhead protects aigateway; the wait bound protects THIS process.

    Cache keys derive from verified caller identities, so distinct callers bypass single-flight
    and every request takes the
    cold-miss path. Without a bound on the wait, those queue behind the upstream
    call with no ceiling — indistinguishable, from the
    caller's side, from a hang.
    """
    started = asyncio.Event()

    class _Blocking:
        async def fetch(self, credential: Credential) -> ModelCatalog:
            started.set()
            await asyncio.sleep(3600)
            raise AssertionError("unreachable")

    cache = CachedCatalog(_Blocking(), upstream_concurrency=1, bulkhead_wait_s=0.05)
    holder = asyncio.ensure_future(cache.fetch(_credential("first")))
    await asyncio.wait_for(started.wait(), timeout=1)

    with pytest.raises(CatalogError, match="saturated"):
        await cache.fetch(_credential("second"))

    holder.cancel()


async def test_the_bulkhead_slot_is_released_when_upstream_fails() -> None:
    """A slot leaked on the error path would shrink the bulkhead by one per failure until every
    request timed out waiting — an outage that never recovers on its own."""

    class _Failing:
        async def fetch(self, credential: Credential) -> ModelCatalog:
            raise CatalogError("upstream down")

    cache = CachedCatalog(_Failing(), upstream_concurrency=1, bulkhead_wait_s=0.05)
    for i in range(5):
        with pytest.raises(CatalogError):
            await cache.fetch(_credential(f"caller-{i}"))

    # If slots leaked, this raises "saturated" rather than the upstream's own error.
    with pytest.raises(CatalogError, match="upstream down"):
        await cache.fetch(_credential("final"))
