from __future__ import annotations

import json
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError, OperationalError
from tortoise.expressions import F

from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.store import (
    CacheUnavailable,
    RequestCacheWrite,
    TortoiseRequestCacheStore,
)
from aigateway.db import build_tortoise_config

_KEY = "a" * 64
_RESPONSE = {
    "id": "cmpl-1",
    "model": "anthropic/claude-haiku-4-5",
    "choices": [{"message": {"role": "assistant", "content": "SECRET-ANSWER"}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 3},
}


class _Gate:
    def __init__(self, *, available: bool = True) -> None:
        self._available = available

    def cache_available(self) -> bool:
        return self._available


def _write(key_hash: str = _KEY, **overrides) -> RequestCacheWrite:
    values = {
        "key_hash": key_hash,
        "prompt_hash": "p" * 64,
        "provider": "anthropic",
        "model": "anthropic/claude-haiku-4-5",
        "response": _RESPONSE,
        "response_size_bytes": 128,
    }
    values.update(overrides)
    return RequestCacheWrite(**values)  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = tmp_path / "global-cache.sqlite3"
    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{db_path}"),
        _enable_global_fallback=True,
    )
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()


@pytest_asyncio.fixture
async def gate() -> _Gate:
    return _Gate()


@pytest_asyncio.fixture
async def store(db, gate: _Gate) -> TortoiseRequestCacheStore:
    return TortoiseRequestCacheStore(availability=gate)


# --- the frozen write contract -------------------------------------------------------------------


def test_write_carries_no_expiry_identity_or_prompt() -> None:
    """Plan §8.5 and §10 — the DTO cannot even express what must never be persisted.

    No ``expires_at`` (v2 always writes NULL), no account/profile/credential identity, no prompt or
    canonical key DTO. Pinned structurally so a later field addition is a deliberate contract change
    rather than a quiet one.
    """
    assert {field.name for field in dataclass_fields(RequestCacheWrite)} == {
        "key_hash",
        "prompt_hash",
        "provider",
        "model",
        "response",
        "response_size_bytes",
        "metadata",
    }


# --- store / read round trip ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_if_absent_then_get_round_trips_the_response(store) -> None:
    entry = _write()

    assert await store.set_if_absent(entry) == "stored"

    assert (await store.get(_KEY)).response == _RESPONSE
    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.response_json == json.dumps(_RESPONSE, separators=(",", ":"), ensure_ascii=False)


@pytest.mark.asyncio
async def test_get_preserves_the_exact_lexical_decimal_for_accounting(store) -> None:
    await store.set_if_absent(_write())
    row = await RequestCacheEntry.get(key_hash=_KEY)
    row.response_json = '{"id":"cmpl","choices":[],"usage":{"cost":0.0038799200000000002}}'
    await row.save(update_fields=["response_json"])

    entry = await store.get(_KEY)

    assert entry is not None
    assert entry.response["usage"]["cost"] == Decimal("0.0038799200000000002")
    assert type(entry.response["usage"]["cost"]) is Decimal


@pytest.mark.asyncio
async def test_write_persists_null_expiry(store) -> None:
    await store.set_if_absent(_write())

    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.expires_at is None


@pytest.mark.asyncio
async def test_null_expiry_row_is_readable_however_old_it_is(store) -> None:
    """Plan §8.11 — NULL is unexpired, not "expired at the epoch"."""
    await store.set_if_absent(_write())
    row = await RequestCacheEntry.get(key_hash=_KEY)
    row.created_at = datetime.now(UTC) - timedelta(days=365)
    await row.save(update_fields=["created_at"])

    assert (await store.get(_KEY)).response == _RESPONSE


@pytest.mark.asyncio
async def test_get_misses_on_an_unknown_key(store) -> None:
    assert await store.get("z" * 64) is None


@pytest.mark.asyncio
async def test_the_ttl_purge_keeps_indefinite_rows_and_deletes_expired_rows(store) -> None:
    await store.set_if_absent(_write())
    dead = "e" * 64
    await store.set_if_absent(_write(dead))
    aged = await RequestCacheEntry.get(key_hash=dead)
    aged.expires_at = datetime.now(UTC) - timedelta(seconds=5)
    await aged.save(update_fields=["expires_at"])

    assert await store.delete_expired() == 1
    assert (await store.get(_KEY)).response == _RESPONSE


@pytest.mark.asyncio
async def test_the_persisted_row_holds_no_prompt_identity_or_credential(store) -> None:
    """Plan §8.5 / requirements §8.6 — checked on the DB ROW, not just the write DTO.

    The DTO test above proves the contract cannot *express* identity; this proves the row does not
    *contain* it. Every text column is inspected, so a future field that starts smuggling a prompt,
    an account id or a token into the row fails here rather than in review.
    """
    prompt = "SECRET-PROMPT-TEXT"
    account = "acct-000000000000000000000001"
    token = "sk-ant-SECRET-CREDENTIAL"
    response = {"id": "cmpl", "choices": [{"message": {"content": "answer"}}]}
    await store.set_if_absent(_write(response=response))

    row = await RequestCacheEntry.get(key_hash=_KEY)
    stored = {name: value for name, value in row.__dict__.items() if isinstance(value, str)}
    haystack = "\n".join(f"{name}={value}" for name, value in stored.items())
    for forbidden in (prompt, account, token):
        assert forbidden not in haystack, f"{forbidden!r} must never reach the row: {stored}"

    assert json.loads(row.response_json) == response


# --- first-successful-insert-wins ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_writer_loses_the_race_and_the_winner_survives(store) -> None:
    """Plan §8.12 and §5.3 — create-only; a racing fill never overwrites the stored winner."""
    assert await store.set_if_absent(_write()) == "stored"

    loser = _write(response={"id": "cmpl-2", "choices": [{"message": {"content": "B"}}]})
    assert await store.set_if_absent(loser) == "race_lost"

    assert await RequestCacheEntry.filter(key_hash=_KEY).count() == 1
    assert (await store.get(_KEY)).response == _RESPONSE


# --- atomic hit metadata -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_hit_increments_hit_count_once(store) -> None:
    """Plan §8.13 — a hit records exactly one hit."""
    await store.set_if_absent(_write())

    await store.get(_KEY)
    await store.get(_KEY)

    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.hit_count == 2
    assert row.last_hit_at is not None


@pytest.mark.asyncio
async def test_a_concurrent_increment_is_not_lost_by_the_hit_update(db, gate: _Gate) -> None:
    store = TortoiseRequestCacheStore(availability=gate)
    await store.set_if_absent(_write())

    await RequestCacheEntry.filter(key_hash=_KEY).update(hit_count=F("hit_count") + 5)

    entry = await store.get(_KEY)
    assert entry is not None
    assert entry.response == _RESPONSE

    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.hit_count == 6, "the concurrent increment was overwritten — the update is not atomic"


@pytest.mark.asyncio
async def test_hit_metadata_failure_still_returns_the_hit(store, monkeypatch) -> None:
    """Plan §5.4 and §8.16 — a metadata write failure does not fail an otherwise valid hit."""
    await store.set_if_absent(_write())

    async def _broken_update(*_args, **_kwargs) -> int:
        raise OperationalError("metadata update failed")

    monkeypatch.setattr("aigateway.core.request_cache.store.record_hit_metadata", _broken_update)

    assert (await store.get(_KEY)).response == _RESPONSE


@pytest.mark.asyncio
async def test_unexpected_hit_metadata_failure_still_returns_the_hit(store, monkeypatch) -> None:
    """Plan §5.4 — metadata is best-effort after the response is validated."""
    await store.set_if_absent(_write())

    async def _broken_update(*_args, **_kwargs) -> int:
        raise RuntimeError("unexpected metadata update failure")

    monkeypatch.setattr("aigateway.core.request_cache.store.record_hit_metadata", _broken_update)

    assert (await store.get(_KEY)).response == _RESPONSE


# --- write failure -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_finite_response_is_not_stored(store) -> None:
    response = {
        "id": "cmpl-non-finite",
        "choices": [{"message": {"content": "answer"}}],
        "score": float("nan"),
    }

    assert await store.set_if_absent(_write(response=response)) == "not_stored"
    assert not await RequestCacheEntry.filter(key_hash=_KEY).exists()


@pytest.mark.asyncio
async def test_database_write_failure_reports_not_stored(store, monkeypatch) -> None:
    """Plan §5.4 — a persistence failure is reported, never raised onto the request path."""

    async def _broken_create(*_args, **_kwargs):
        raise OperationalError("insert failed")

    monkeypatch.setattr(RequestCacheEntry, "create", _broken_create)

    assert await store.set_if_absent(_write()) == "not_stored"


@pytest.mark.asyncio
async def test_a_constraint_other_than_the_key_is_not_reported_as_a_lost_race(
    store, monkeypatch
) -> None:
    """A NOT NULL violation must not read as healthy contention.

    INVARIANT: ``race_lost`` means "the winner's row is in the table". ``IntegrityError`` covers
    NOT NULL as well as UNIQUE, so mapping the whole class to ``race_lost`` misreports a schema
    problem as someone else having stored it first — and the deployment that hits this is a real
    one: skip migration 0009 (``migration.enabled: false``, a non-Helm install, an overlooked
    migrate-Job failure) and ``expires_at`` is still NOT NULL, so every v2 fill violates it.

    The consequence is what makes this worth a test rather than a comment: the cache never fills,
    every request pays full provider cost, the only trace is at ``logger.debug``, and a dashboard
    shows 100% ``race_lost`` against an EMPTY table — which is indistinguishable from a healthy
    contended cache. The signal an operator would look at points AWAY from the defect.
    """

    async def _not_null_violation(*_args, **_kwargs):
        raise IntegrityError("NOT NULL constraint failed: request_cache_entries.expires_at")

    monkeypatch.setattr(RequestCacheEntry, "create", _not_null_violation)

    assert await store.set_if_absent(_write()) == "not_stored"
    assert not await RequestCacheEntry.filter(key_hash=_KEY).exists()


@pytest.mark.asyncio
async def test_a_failed_confirming_read_reports_not_stored_rather_than_raising(
    store, monkeypatch
) -> None:
    """The read that classifies the conflict is itself on the request path, so it must not raise.

    Distinguishing ``race_lost`` from ``not_stored`` costs one query, and a query can fail. The
    module invariant is that no failure in here escapes as an unhandled exception, so an unusable
    database during classification degrades to ``not_stored`` — the safe answer, because the caller
    already has its response and only the bookkeeping is lost.
    """

    async def _conflict(*_args, **_kwargs):
        raise IntegrityError("duplicate key value violates unique constraint")

    def _broken_filter(*_args, **_kwargs):
        raise OperationalError("connection is closed")

    monkeypatch.setattr(RequestCacheEntry, "create", _conflict)
    monkeypatch.setattr(RequestCacheEntry, "filter", _broken_filter)

    assert await store.set_if_absent(_write()) == "not_stored"


# --- rows this worker cannot decode: refuse to serve, NEVER delete --------------------------------


@pytest.mark.asyncio
async def test_an_undecodable_row_is_refused_and_never_deleted(store) -> None:
    await store.set_if_absent(_write())
    other = "c" * 64
    await store.set_if_absent(_write(other))
    row = await RequestCacheEntry.get(key_hash=_KEY)
    row.response_json = "not-json"
    await row.save(update_fields=["response_json"])

    with pytest.raises(CacheUnavailable):
        await store.get(_KEY)

    assert await RequestCacheEntry.filter(key_hash=_KEY).exists(), "the row must survive untouched"
    assert await RequestCacheEntry.filter(key_hash=other).exists()


@pytest.mark.asyncio
async def test_a_plaintext_json_object_row_is_served(store) -> None:
    await store.set_if_absent(_write())
    row = await RequestCacheEntry.get(key_hash=_KEY)
    row.response_json = json.dumps({"id": "injected", "choices": ["ATTACKER-CONTROLLED"]})
    await row.save(update_fields=["response_json"])

    assert (await store.get(_KEY)).response == {
        "id": "injected",
        "choices": ["ATTACKER-CONTROLLED"],
    }


@pytest.mark.asyncio
async def test_a_payload_that_is_not_a_json_object_is_refused_and_kept(store) -> None:
    """A plaintext row that parses but is not an object must not be served.

    ``json.loads`` happily returns a list, a bare string or a number, so "it parsed"
    is not the same claim as "it is a response body". The route builds its reply from this dict, so
    a list would surface as an ``AttributeError`` deep inside dispatch instead of a clean bypass.

    INVARIANT: the refusal still deletes nothing. This shares the never-delete path with an
    undecodable row, so a payload-shape bug cannot walk the shared corpus either.
    """
    await store.set_if_absent(_write())
    row = await RequestCacheEntry.get(key_hash=_KEY)
    row.response_json = json.dumps(["not", "an", "object"])
    await row.save(update_fields=["response_json"])

    with pytest.raises(CacheUnavailable):
        await store.get(_KEY)

    assert await RequestCacheEntry.filter(key_hash=_KEY).exists(), "the row must survive untouched"


@pytest.mark.parametrize("non_finite", ["NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"])
@pytest.mark.asyncio
async def test_a_payload_with_non_finite_json_is_refused_and_kept(store, non_finite: str) -> None:
    assert await store.set_if_absent(_write()) == "stored"
    row = await RequestCacheEntry.get(key_hash=_KEY)
    row.response_json = f'{{"id":"cmpl","choices":[],"score":{non_finite}}}'
    await row.save(update_fields=["response_json"])

    with pytest.raises(CacheUnavailable):
        await store.get(_KEY)

    assert await RequestCacheEntry.filter(key_hash=_KEY).exists()


@pytest.mark.asyncio
async def test_a_row_with_a_past_expiry_is_refused_without_being_rewritten(store) -> None:
    """Writes currently use NULL, while a future TTL may put a timestamp in the same lane.

    The reader refuses an expired row without deleting or rewriting it; cleanup remains the explicit
    responsibility of ``delete_expired``.

    AIDEV-NOTE: the refusal is a MISS (``None``), so the route dispatches and then tries to fill —
    and the fill returns ``race_lost``, because the create-only writer will not replace an existing
    row. Refill semantics belong to the deferred TTL work.
    """
    await store.set_if_absent(_write())
    await RequestCacheEntry.filter(key_hash=_KEY).update(
        expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )

    assert await store.get(_KEY) is None

    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.expires_at is not None, "the row must not have been rewritten"
    assert await store.set_if_absent(_write()) == "race_lost"


# --- degraded workers ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_degraded_worker_performs_no_read_write_or_delete(db) -> None:
    """Plan §8.10, §8.15 and §5.4 — a degraded worker touches nothing.

    The pre-existing rows must still be there afterwards.

    The closed gate must **raise**, not return ``None``. ``None`` is this module's miss signal, and
    a miss makes the route dispatch AND fill — so returning it here would have a degraded worker
    writing to the very cache it is not allowed to touch.
    """
    seeded = TortoiseRequestCacheStore(availability=_Gate())
    await seeded.set_if_absent(_write())

    degraded = TortoiseRequestCacheStore(availability=_Gate(available=False))

    assert degraded.cache_available() is False
    with pytest.raises(CacheUnavailable):
        await degraded.get(_KEY)
    assert await degraded.set_if_absent(_write("d" * 64)) == "not_stored"

    assert await RequestCacheEntry.filter(key_hash=_KEY).exists(), "shared row must survive"
    assert not await RequestCacheEntry.filter(key_hash="d" * 64).exists()


@pytest.mark.asyncio
async def test_cache_available_reflects_the_availability_gate(db, gate: _Gate) -> None:
    store = TortoiseRequestCacheStore(availability=gate)
    assert store.cache_available() is True

    assert TortoiseRequestCacheStore(availability=_Gate(available=False)).cache_available() is False


# --- runtime read failure ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_database_read_failure_raises_cache_unavailable(store, monkeypatch) -> None:
    """Plan §5.4 and §8.16 — a read failure is a bounded, typed bypass signal, not a miss.

    ``get`` returning ``None`` means "no such entry", which the route reports as a MISS and
    then fills. A database outage is not a miss, and the route has to report
    ``X-AIGW-Cache: bypass`` with reason ``cache_unavailable`` — so the two outcomes cannot share
    one return value.
    """

    async def _broken_get(*_args, **_kwargs):
        raise OperationalError("select failed")

    monkeypatch.setattr(RequestCacheEntry, "get_or_none", _broken_get)

    with pytest.raises(CacheUnavailable):
        await store.get(_KEY)
